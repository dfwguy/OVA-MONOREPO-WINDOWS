#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# install-node.sh — IREN_MKZ GB300 observability agent installer (runs ON a node)
#
# IREN_MKZ-hardened fork of the IREN_MKZ node installer. Installs NATIVE systemd
# units (no container runtime — DGX-OS / Ubuntu, Grace/arm64):
#   - dcgm-exporter   :9400  (connects to local nv-hostengine on localhost:5555)
#   - node_exporter   :9100  (+ textfile collector dir for the .prom scripts)
#   - cgroup_exporter :9306  (per-Slurm-job cpu/mem/io from cgroup v2, keyed by jobid)
#   - grafana alloy   :12345 (scrapes 9400/9100/9306/12345; tails dmesg/kernel/
#                             journal/var-log/NCCL/Slurm; remote_write to the node's
#                             Prometheus SHARD + loki.write to :3100)
#   - IB HCA textfile collector on a systemd timer
#
# IREN_MKZ deltas vs IREN_MKZ (see design/alloy_fleet.md §6):
#   1. DCGM install-if-missing (ensure_dcgm) — detect + install datacenter-gpu-manager.
#   2. Hostname → su/rack/datahall/tray labels via lib-node-labels.sh (external_labels).
#   3. Expanded log set: dmesg/kern/journal/var-log/NCCL/Slurm(+spool).
#   4. remote_write → VictoriaMetrics (RW_URL set by the ObsVM driver).
#
# Idempotent: re-running is a fast no-op when already onboarded (FORCE=1 to redo).
# Reboot-safe: all units WantedBy=multi-user.target / timers.target and `enable`d;
#              binaries copied to LOCAL disk so boot does not depend on $SHARE.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# ── resolve remote_write / loki targets from env (no site values baked in) ────
OBSVM_FABRIC_IP="${OBSVM_FABRIC_IP:-}"
METRICS_TARGET="${METRICS_TARGET:-${OBSVM_FABRIC_IP}}"
RELAY_HOST="${RELAY_HOST:-${METRICS_TARGET}}"
RELAY_RW_PORT="${RELAY_RW_PORT:-8429}"      # host-published VictoriaMetrics port
RELAY_LOKI_PORT="${RELAY_LOKI_PORT:-3100}"
RW_URL="${RW_URL:-http://${RELAY_HOST}:${RELAY_RW_PORT}/api/v1/write}"
LOKI_PUSH_URL="${LOKI_PUSH_URL:-http://${RELAY_HOST}:${RELAY_LOKI_PORT}/loki/api/v1/push}"

CLUSTER_NAME="${CLUSTER_NAME:-IREN_MKZ}"
DGX_FLAVOR="${DGX_FLAVOR:-GB300}"
SHARE="${SHARE:-/cm/shared/nvis/bin}"
TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
COLLECTOR_INTERVAL="${COLLECTOR_INTERVAL:-30s}"
ENABLE_TEXTFILE_COLLECTORS="${ENABLE_TEXTFILE_COLLECTORS:-1}"
FORCE="${FORCE:-0}"
HOST="$(hostname -s)"

# IREN_MKZ expanded-log globs (jobs point NCCL_DEBUG_FILE here; Slurm spool default).
NCCL_LOG_GLOB="${NCCL_LOG_GLOB:-/var/log/nccl/*.log}"
SLURM_SPOOL_GLOB="${SLURM_SPOOL_GLOB:-/var/spool/slurmd/job*/slurm_script}"

log(){ echo "[${HOST}] $*"; }
fail(){ echo "[${HOST}] ERROR: $*" >&2; echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=$*"; exit 1; }

# ── derive su/rack/datahall/tray labels from the hostname ────────────────────
# lib-node-labels.sh is staged next to this script ($SHARE) or shipped alongside.
_here="$(cd "$(dirname "$0")" && pwd)"
_lib=""
for cand in "${_here}/lib-node-labels.sh" "${SHARE}/lib-node-labels.sh"; do
  [[ -f "$cand" ]] && { _lib="$cand"; break; }
done
if [[ -n "$_lib" ]]; then
  # shellcheck source=/dev/null
  source "$_lib"
  nvis_derive_labels "$HOST" || log "WARN: '$HOST' does not match GB300 naming — labels=unknown"
else
  log "WARN: lib-node-labels.sh not found (dir=${_here}, share=${SHARE}) — labels=unknown"
  NVIS_SU=unknown; NVIS_SU_LETTER=unknown; NVIS_DATAHALL=unknown; NVIS_RACK=unknown
  NVIS_RACK_ORDINAL=unknown; NVIS_TRAY_INDEX=unknown; NVIS_RACKTYPE=GB300_72x1
fi

# refuse to push to a broken URL when no target was supplied
if [[ -z "${RELAY_HOST}" && "${RW_URL}" == "http://:${RELAY_RW_PORT}/api/v1/write" ]]; then
  fail "no_target: set OBSVM_FABRIC_IP / METRICS_TARGET or RW_URL (+ LOKI_PUSH_URL)"
fi

# ── idempotency fast-path ────────────────────────────────────────────────────
already_ok(){
  # Check each service individually (systemd is-active with multiple args is
  # unreliable across versions). Only require services we actually install.
  local svcs="alloy"
  [[ "${SKIP_NODE:-}"   == "1" ]] || svcs="node_exporter ${svcs}"
  [[ "${SKIP_DCGM:-}"   == "1" ]] || svcs="dcgm-exporter ${svcs}"
  [[ "${SKIP_CGROUP:-}" == "1" ]] || svcs="cgroup-exporter ${svcs}"
  for svc in ${svcs}; do
    systemctl is-active --quiet "${svc}" 2>/dev/null || return 1
  done
  grep -qF "${RW_URL}" /etc/alloy/config.alloy 2>/dev/null || return 1   # points at CURRENT shard
  grep -q "\"${HOST}\"" /etc/alloy/config.alloy 2>/dev/null || return 1
  [[ "${SKIP_CGROUP:-}" == "1" ]] || grep -q "localhost:9306" /etc/alloy/config.alloy 2>/dev/null || return 1
  return 0
}
if [[ "${FORCE}" != "1" ]] && already_ok; then
  log "ALREADY_ONBOARDED (services active, config → ${RW_URL}, instance=${HOST}, su=${NVIS_SU})"
  echo "NVIS_RESULT host=${HOST} su=${NVIS_SU} node_exporter=OK dcgm=OK cgroup=OK alloy=OK ready=OK verdict=PASS state=preexisting"
  exit 0
fi

# ── ensure DCGM host-engine present + running (install if missing) ───────────
# The brief's headline node-side ask. Non-fatal: dcgm-exporter (Restart=always)
# attaches to localhost:5555 as soon as the host-engine appears.
ensure_dcgm(){
  if dcgmi discovery -l >/dev/null 2>&1; then log "DCGM present (dcgmi ok)"; return 0; fi
  if systemctl list-unit-files 2>/dev/null | grep -qE '^(nvidia-dcgm|dcgm)\.service'; then
    log "DCGM installed but down — enabling nvidia-dcgm.service"
    systemctl enable --now nvidia-dcgm.service 2>/dev/null || \
      systemctl enable --now dcgm.service 2>/dev/null || true
  else
    if compgen -G "${SHARE}/dcgm-debs/*.deb" >/dev/null; then
      log "installing DCGM from staged .debs (${SHARE}/dcgm-debs)"
      dpkg -i "${SHARE}"/dcgm-debs/*.deb 2>/dev/null || apt-get -y -f install 2>/dev/null || true
    elif command -v apt-get >/dev/null 2>&1; then
      log "installing DCGM via apt (datacenter-gpu-manager)"
      DEBIAN_FRONTEND=noninteractive apt-get update -qq 2>/dev/null || true
      DEBIAN_FRONTEND=noninteractive apt-get install -y datacenter-gpu-manager 2>/dev/null || true
    fi
    systemctl enable --now nvidia-dcgm.service 2>/dev/null || \
      systemctl enable --now dcgm.service 2>/dev/null || \
      { nohup nv-hostengine >/dev/null 2>&1 & }   # fallback: raw host-engine on :5555
  fi
  for _i in $(seq 1 6); do dcgmi discovery -l >/dev/null 2>&1 && { log "DCGM up"; return 0; }; sleep 5; done
  log "WARN: DCGM host-engine not confirmed — dcgm-exporter will retry via Restart=always"
  return 0
}
[[ "${SKIP_DCGM:-}" == "1" ]] || ensure_dcgm

# ── sanity: staged binaries present ──────────────────────────────────────────
REQUIRED_BINS="alloy dcgm-counters.csv"
[[ "${SKIP_DCGM:-}"   == "1" ]] || REQUIRED_BINS+=" dcgm-exporter"
[[ "${SKIP_NODE:-}"   == "1" ]] || REQUIRED_BINS+=" node_exporter"
[[ "${SKIP_CGROUP:-}" == "1" ]] || REQUIRED_BINS+=" cgroup_exporter"
for b in ${REQUIRED_BINS}; do
  [[ -f "${SHARE}/${b}" ]] || fail "missing_staged_${b} (checked ${SHARE}; run stage-binaries.sh)"
done

# ── install binaries to LOCAL disk (only if changed; boot must not need $SHARE) ─
install_bin(){ # src dst
  local src="$1" dst="$2"
  if [[ ! -f "${dst}" ]] || ! cmp -s "${src}" "${dst}"; then
    install -m0755 "${src}" "${dst}" || return 1
    log "installed ${dst}"
  fi
}
[[ "${SKIP_NODE:-}" == "1" ]]   || install_bin "${SHARE}/node_exporter"   /usr/local/bin/node_exporter   || fail "copy_node_exporter"
[[ "${SKIP_DCGM:-}" == "1" ]]   || install_bin "${SHARE}/dcgm-exporter"   /usr/local/bin/dcgm-exporter   || fail "copy_dcgm_exporter"
[[ "${SKIP_CGROUP:-}" == "1" ]] || install_bin "${SHARE}/cgroup_exporter" /usr/local/bin/cgroup_exporter || fail "copy_cgroup_exporter"
install_bin "${SHARE}/alloy" /usr/bin/alloy || fail "copy_alloy"

mkdir -p /etc/dcgm-exporter /etc/alloy /var/lib/alloy/data "${TEXTFILE_DIR}"
install -m0644 "${SHARE}/dcgm-counters.csv" /etc/dcgm-exporter/counters.csv

# ── textfile collectors (GPU NVLink + IB HCA verbs) ──────────────────────────
if [[ "${ENABLE_TEXTFILE_COLLECTORS}" == "1" ]]; then
  for c in hca_verbs_collector.sh; do
    if [[ -f "${SHARE}/${c}" ]]; then
      install -m0755 "${SHARE}/${c}" "/usr/local/bin/${c}"
    elif [[ -f "${_here}/textfile-collectors/${c}" ]]; then
      install -m0755 "${_here}/textfile-collectors/${c}" "/usr/local/bin/${c}"
    else
      log "WARN: ${c} not staged in ${SHARE} — skipping its timer"
    fi
  done
fi

# ── locate libdcgm (dcgm-exporter dlopens it at runtime) ─────────────────────
LIBDCGM_DIR="$(dirname "$(find /usr/lib /lib /cm/local/apps/cuda-dcgm -name 'libdcgm.so.4' 2>/dev/null | head -1)")"
if [[ -z "${LIBDCGM_DIR}" || "${LIBDCGM_DIR}" == "." ]]; then
  case "$(uname -m)" in
    aarch64) LIBDCGM_DIR="/usr/lib/aarch64-linux-gnu" ;;   # GB300 = Grace/arm64
    *)       LIBDCGM_DIR="/usr/lib/x86_64-linux-gnu" ;;
  esac
fi
log "libdcgm dir: ${LIBDCGM_DIR}"

# ── systemd unit: node_exporter (with textfile collector directory) ──────────
if [[ "${SKIP_NODE:-}" == "1" ]]; then
  log "SKIP_NODE=1 → host node_exporter owned elsewhere; Alloy serves NVLink/HCA .prom via native textfile reader"
  rm -f /etc/systemd/system/node_exporter.service 2>/dev/null || true
else
cat >/etc/systemd/system/node_exporter.service <<EOF
[Unit]
Description=Prometheus node_exporter (NVIS IREN_MKZ)
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=/usr/local/bin/node_exporter \\
  --web.listen-address=:9100 \\
  --collector.textfile.directory=${TEXTFILE_DIR} \\
  --collector.cpu.info \\
  --collector.netdev \\
  --collector.netstat \\
  --collector.diskstats \\
  --collector.filesystem \\
  --collector.filesystem.fs-types-exclude="^(autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|iso9660|mqueue|nfs|nfs4|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tracefs)$" \\
  --collector.meminfo \\
  --collector.systemd
Restart=always
RestartSec=5
User=root
[Install]
WantedBy=multi-user.target
EOF
fi

# ── systemd unit: dcgm-exporter (uses local nv-hostengine @ localhost:5555) ───
if [[ "${SKIP_DCGM:-}" == "1" ]]; then
  log "SKIP_DCGM=1 → not installing dcgm-exporter"
  rm -f /etc/systemd/system/dcgm-exporter.service 2>/dev/null || true
else
cat >/etc/systemd/system/dcgm-exporter.service <<EOF
[Unit]
Description=NVIDIA DCGM Exporter (NVIS IREN_MKZ)
After=network-online.target nvidia-dcgm.service
Wants=network-online.target
[Service]
Environment=LD_LIBRARY_PATH=${LIBDCGM_DIR}
ExecStart=/usr/local/bin/dcgm-exporter --address=:9400 --remote-hostengine-info=localhost:5555 --collectors=/etc/dcgm-exporter/counters.csv
Restart=always
RestartSec=5
User=root
[Install]
WantedBy=multi-user.target
EOF
fi

# ── systemd unit: cgroup_exporter (per-Slurm-job cgroup v2 metrics) ──────────
if [[ "${SKIP_CGROUP:-}" == "1" ]]; then
  log "SKIP_CGROUP=1 → not installing cgroup_exporter"
  rm -f /etc/systemd/system/cgroup-exporter.service 2>/dev/null || true
else
cat >/etc/systemd/system/cgroup-exporter.service <<EOF
[Unit]
Description=cgroup_exporter (NVIS IREN_MKZ — per-Slurm-job metrics)
After=network-online.target slurmd.service
Wants=network-online.target
[Service]
ExecStart=/usr/local/bin/cgroup_exporter --config.paths=/slurm --collect.proc --web.listen-address=:9306
Restart=always
RestartSec=5
User=root
[Install]
WantedBy=multi-user.target
EOF
fi

# ── textfile collector timers (only for collectors that got staged) ──────────
declare -a COLLECTOR_UNITS=()
if [[ "${ENABLE_TEXTFILE_COLLECTORS}" == "1" ]]; then
  make_collector_timer(){ # unit-basename  /usr/local/bin/script  description
    local unit="$1" bin="$2" desc="$3"
    [[ -x "${bin}" ]] || return 0
    cat >/etc/systemd/system/${unit}.service <<EOF
[Unit]
Description=${desc}
After=node_exporter.service
[Service]
Type=oneshot
Environment=TEXTFILE_DIR=${TEXTFILE_DIR}
ExecStart=${bin}
EOF
    cat >/etc/systemd/system/${unit}.timer <<EOF
[Unit]
Description=Run ${desc} every ${COLLECTOR_INTERVAL}
[Timer]
OnBootSec=30s
OnUnitActiveSec=${COLLECTOR_INTERVAL}
AccuracySec=5s
[Install]
WantedBy=timers.target
EOF
    COLLECTOR_UNITS+=("${unit}.timer")
  }
  make_collector_timer nvis-hca-collector    /usr/local/bin/hca_verbs_collector.sh   "NVIS IB HCA verbs textfile collector"
fi

# ── Alloy River config — external_labels stamp cluster/su/rack/node on ALL ───
# series (metrics) and log streams. gpu is intentionally absent (dcgm-exporter
# emits it per-series; external_labels must not clobber it).
cat >/etc/alloy/config.alloy <<EOF
// ─────────────────────────────────────────────────────────────────────────────
// NVIS GB300 node Alloy agent — instance=${HOST} cluster=${CLUSTER_NAME} su=${NVIS_SU}
// Generated by install-node.sh. Do not edit by hand (re-run installer to update).
// ─────────────────────────────────────────────────────────────────────────────

logging {
  level  = "info"
  format = "logfmt"
}

// Prometheus remote_write → VictoriaMetrics (WAL-buffered: survives receiver downtime)
prometheus.remote_write "obsvm" {
  endpoint {
    url = "${RW_URL}"
  }
  external_labels = {
    cluster      = "${CLUSTER_NAME}",
    dgx_flavor   = "${DGX_FLAVOR}",
    su           = "${NVIS_SU}",
    su_letter    = "${NVIS_SU_LETTER}",
    datahall     = "${NVIS_DATAHALL}",
    rack         = "${NVIS_RACK}",
    rack_ordinal = "${NVIS_RACK_ORDINAL}",
    tray_index   = "${NVIS_TRAY_INDEX}",
    racktype     = "${NVIS_RACKTYPE}",
    node         = "${HOST}",
  }
}

// DCGM exporter (localhost:9400) — honor_timestamps=false per NVIS standard.
// honor_labels via relabel: keep the per-series gpu label dcgm-exporter emits.
prometheus.scrape "dcgm" {
  targets          = [{ __address__ = "localhost:9400" }]
  scrape_interval  = "15s"
  honor_timestamps = false
  forward_to       = [prometheus.relabel.dcgm.receiver]
}
prometheus.relabel "dcgm" {
  forward_to = [prometheus.remote_write.obsvm.receiver]
  rule {
    target_label = "job"
    replacement = "dcgm-exporter"
  }
  rule {
    target_label = "instance"
    replacement = "${HOST}"
  }
}

// node_exporter (localhost:9100)
prometheus.scrape "node_exporter" {
  targets         = [{ __address__ = "localhost:9100" }]
  scrape_interval = "15s"
  forward_to      = [prometheus.relabel.node_exporter.receiver]
}
prometheus.relabel "node_exporter" {
  forward_to = [prometheus.remote_write.obsvm.receiver]
  rule {
    target_label = "job"
    replacement = "node-exporter"
  }
  rule {
    target_label = "instance"
    replacement = "${HOST}"
  }
}

// cgroup_exporter (localhost:9306) — per-Slurm-job cpu/mem/io keyed by jobid
prometheus.scrape "cgroup_exporter" {
  targets         = [{ __address__ = "localhost:9306" }]
  scrape_interval = "15s"
  forward_to      = [prometheus.relabel.cgroup_exporter.receiver]
}
prometheus.relabel "cgroup_exporter" {
  forward_to = [prometheus.remote_write.obsvm.receiver]
  rule {
    target_label = "job"
    replacement = "cgroup-exporter"
  }
  rule {
    target_label = "instance"
    replacement = "${HOST}"
  }
}

// Alloy self-metrics (localhost:12345) — per-node agent health visible centrally
prometheus.scrape "alloy" {
  targets         = [{ __address__ = "localhost:12345" }]
  scrape_interval = "15s"
  forward_to      = [prometheus.relabel.alloy.receiver]
}
prometheus.relabel "alloy" {
  forward_to = [prometheus.remote_write.obsvm.receiver]
  rule {
    target_label = "job"
    replacement = "alloy"
  }
  rule {
    target_label = "instance"
    replacement = "${HOST}"
  }
}

// Loki write → ObsVM :3100 (single, not sharded)
loki.write "obsvm" {
  endpoint {
    url = "${LOKI_PUSH_URL}"
  }
  external_labels = {
    cluster      = "${CLUSTER_NAME}",
    dgx_flavor   = "${DGX_FLAVOR}",
    su           = "${NVIS_SU}",
    su_letter    = "${NVIS_SU_LETTER}",
    datahall     = "${NVIS_DATAHALL}",
    rack         = "${NVIS_RACK}",
    rack_ordinal = "${NVIS_RACK_ORDINAL}",
    tray_index   = "${NVIS_TRAY_INDEX}",
    racktype     = "${NVIS_RACKTYPE}",
    node         = "${HOST}",
  }
}

// ── Log tailing: dmesg / kernel / var-log / DCGM / NCCL / Slurm ──────────────
local.file_match "logfiles" {
  path_targets = [
    { __path__ = "/var/log/syslog",              job = "syslog",     service = "syslog",     instance = "${HOST}" },
    { __path__ = "/var/log/kern.log",            job = "kernel",     service = "kernel",     instance = "${HOST}" },
    { __path__ = "/var/log/dmesg",               job = "dmesg",     service = "dmesg",      instance = "${HOST}" },
    { __path__ = "/var/log/messages",            job = "syslog",     service = "syslog",     instance = "${HOST}" },
    { __path__ = "/var/log/nv-hostengine.log",   job = "dcgm",     service = "dcgm",       instance = "${HOST}" },
    { __path__ = "/var/log/slurm/*.log",         job = "slurm",     service = "slurm",      instance = "${HOST}" },
    { __path__ = "/var/log/slurm*",              job = "slurm",     service = "slurm",      instance = "${HOST}" },
    { __path__ = "${NCCL_LOG_GLOB}",             job = "nccl-debug",     service = "nccl-debug", instance = "${HOST}" },
    { __path__ = "${SLURM_SPOOL_GLOB}",          job = "slurm-job",     service = "slurm-job",  instance = "${HOST}" },
  ]
}
loki.source.file "logfiles" {
  targets    = local.file_match.logfiles.targets
  forward_to = [loki.write.obsvm.receiver]
}

// systemd journal (includes kernel/dmesg via _TRANSPORT=kernel + all unit logs)
loki.source.journal "journal" {
  forward_to    = [loki.write.obsvm.receiver]
  relabel_rules = loki.relabel.journal.rules
  labels = {
    job      = "journal",
    // NVIS: the NVIS dashboards select on `service` (gpu-nvlink-health log panels use
    // service=~".*(kernel|syslog|journal|node).*"). Loki 3 auto-derives service_name, NOT
    // service, so without this the node's logs land in Loki but match no panel.
    service  = "journal",
    instance = "${HOST}",
  }
}
loki.relabel "journal" {
  forward_to = []
  rule {
    source_labels = ["__journal__systemd_unit"]
    target_label = "unit"
  }
  rule {
    source_labels = ["__journal__transport"]
    target_label = "transport"
  }
  rule {
    source_labels = ["__journal_priority_keyword"]
    target_label = "level"
  }
}
EOF

# ── NVLink/HCA textfile .prom served by Alloy when node_exporter is absent ────
if [[ "${SKIP_NODE:-}" == "1" ]] && [[ "${ENABLE_TEXTFILE_COLLECTORS}" == "1" ]]; then
cat >>/etc/alloy/config.alloy <<EOF

// NVLink/HCA textfile collectors — Alloy serves the .prom dir directly.
prometheus.exporter.unix "nvis_textfile" {
  set_collectors = ["textfile"]
  textfile { directory = "${TEXTFILE_DIR}" }
}
prometheus.scrape "nvis_textfile" {
  targets         = prometheus.exporter.unix.nvis_textfile.targets
  scrape_interval = "30s"
  forward_to      = [prometheus.relabel.node_exporter.receiver]
}
EOF
  log "appended Alloy native textfile reader (NVLink/HCA .prom from ${TEXTFILE_DIR})"
fi

# ── systemd unit: alloy ──────────────────────────────────────────────────────
cat >/etc/systemd/system/alloy.service <<EOF
[Unit]
Description=Grafana Alloy (NVIS IREN_MKZ)
After=network-online.target
Wants=network-online.target
[Service]
Environment=HOSTNAME=${HOST}
Environment=NVIS_CLUSTER=${CLUSTER_NAME}
ExecStart=/usr/bin/alloy run /etc/alloy/config.alloy --storage.path=/var/lib/alloy/data --server.http.listen-addr=127.0.0.1:12345 --disable-reporting
Restart=always
RestartSec=5
User=root
[Install]
WantedBy=multi-user.target
EOF

# ── enable + (re)start (enable => survives reboot) ───────────────────────────
systemctl daemon-reload
NVIS_SVCS="alloy"
[[ "${SKIP_NODE:-}" == "1" ]]   || NVIS_SVCS="node_exporter ${NVIS_SVCS}"
[[ "${SKIP_DCGM:-}" == "1" ]]   || NVIS_SVCS="dcgm-exporter ${NVIS_SVCS}"
[[ "${SKIP_CGROUP:-}" == "1" ]] || NVIS_SVCS="cgroup-exporter ${NVIS_SVCS}"
systemctl reset-failed ${NVIS_SVCS} 2>/dev/null || true
for svc in ${NVIS_SVCS}; do
  systemctl enable "${svc}" >/dev/null 2>&1
  systemctl restart "${svc}"
done
for t in "${COLLECTOR_UNITS[@]:-}"; do
  [[ -z "${t}" ]] && continue
  systemctl enable "${t}" >/dev/null 2>&1
  systemctl restart "${t}" 2>/dev/null || true
done

# ── validate node-local endpoints (retry — services warm up over a few s) ────
set +o pipefail
ne_ok=FAIL; dcgm_ok=FAIL; cge_ok=FAIL; alloy_ok=FAIL; ready_ok=FAIL
[[ "${SKIP_NODE:-}"   == "1" ]] && ne_ok=OK
[[ "${SKIP_DCGM:-}"   == "1" ]] && dcgm_ok=OK
[[ "${SKIP_CGROUP:-}" == "1" ]] && cge_ok=OK
for _try in 1 2 3 4 5 6; do
  [[ "${ne_ok}"    == OK ]] || { curl -sf --max-time 5 http://localhost:9100/metrics  2>/dev/null | grep -q '^node_cpu' && ne_ok=OK; }
  [[ "${dcgm_ok}"  == OK ]] || { curl -sf --max-time 8 http://localhost:9400/metrics  2>/dev/null | grep -q 'DCGM_FI'   && dcgm_ok=OK; }
  [[ "${cge_ok}"   == OK ]] || { curl -sf --max-time 5 http://localhost:9306/metrics  2>/dev/null | grep -qE '^(cgroup_exporter_build_info|cgroup_info)' && cge_ok=OK; }
  [[ "${alloy_ok}" == OK ]] || { curl -sf --max-time 5 http://localhost:12345/metrics 2>/dev/null | grep -qE '^(alloy_build_info|go_goroutines)' && alloy_ok=OK; }
  [[ "${ready_ok}" == OK ]] || { curl -sf --max-time 5 http://localhost:12345/-/ready 2>/dev/null | grep -qi ready && ready_ok=OK; }
  [[ "${ne_ok}" == OK && "${dcgm_ok}" == OK && "${cge_ok}" == OK && "${alloy_ok}" == OK && "${ready_ok}" == OK ]] && break
  sleep 5
done

verdict=PASS
# DCGM is non-fatal (Restart=always attaches when host-engine appears); require
# node_exporter + cgroup + alloy + ready. dcgm reported for visibility only.
[[ "${ne_ok}" == OK && "${cge_ok}" == OK && "${alloy_ok}" == OK && "${ready_ok}" == OK ]] || verdict=FAIL

log "su=${NVIS_SU} shard→${RW_URL} node_exporter=${ne_ok} dcgm=${dcgm_ok} cgroup=${cge_ok} alloy=${alloy_ok} ready=${ready_ok}"
if [[ "${verdict}" == FAIL ]]; then
  log "--- diag ---"
  systemctl is-active node_exporter dcgm-exporter cgroup-exporter alloy 2>&1 | tr '\n' ' '; echo
  journalctl -u dcgm-exporter -u cgroup-exporter -u alloy --no-pager -n 15 2>/dev/null
fi
echo "NVIS_RESULT host=${HOST} su=${NVIS_SU} node_exporter=${ne_ok} dcgm=${dcgm_ok} cgroup=${cge_ok} alloy=${alloy_ok} ready=${ready_ok} verdict=${verdict} state=installed"
[[ "${verdict}" == PASS ]] && exit 0 || exit 1
