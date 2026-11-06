#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# fleet-rollout.sh — IREN_MKZ ObsVM-side Alloy fleet driver (the "push Alloy to
# every GB300 node" mechanism). Invoked by the systemd timer nvis-fleet-rollout
# (see /opt/observability/iren_mkz/systemd/) and safe to run by hand.
#
# What it does each pass:
#   1. flock — refuse to overlap a still-running pass (reentrant/idempotent).
#   2. Discover UP GB300 nodes from BCM (cmsh), fall back to the static roster.
#   3. In bounded batches: push the identity/WAL guard before running the staged,
#      idempotent installer, then reassert the guard and validate all endpoints.
#   5. Write a Prometheus textfile heartbeat for the fleet-health exporter.
#
# All connection/target values come from the environment (systemd unit / .env).
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/lib-node-labels.sh"

# ── config (env, with IREN_MKZ defaults) ─────────────────────────────────────
CLUSTER_NAME="${CLUSTER_NAME:-IREN_MKZ}"
DGX_FLAVOR="${DGX_FLAVOR:-GB300}"
OBSVM_FABRIC_IP="${OBSVM_FABRIC_IP:-192.0.2.9}"      # proven ObsVM fabric address
VM_RW_PORT="${VM_RW_PORT:-8429}"                       # host-published VictoriaMetrics
LOKI_PUSH_URL="${LOKI_PUSH_URL:-http://${OBSVM_FABRIC_IP}:3100/loki/api/v1/push}"
SHARE="${SHARE:-/cm/shared/nvis/bin}"                  # BCM-shared staging dir (NFS to all nodes)
SSH_USER="${SSH_USER:-root}"
SSH_JUMP="${SSH_JUMP:-}"                               # e.g. root@iren-hn1 ; empty = direct on-fabric
BCM_SSH="${BCM_SSH:-bcm-hn}"                           # ssh alias to BCM head (key ~/.ssh/id_bcm)
BCM_CATEGORY="${BCM_CATEGORY:-hgx-gb300}"
BCM_CMSH="${BCM_CMSH:-/cm/local/apps/cmd/bin/cmsh}"
BATCH="${BATCH:-24}"
RETRIES="${RETRIES:-3}"
ROSTER="${ROSTER:-/opt/observability/iren_mkz/recon/nodes_all.txt}"
TEXTFILE="${RECONCILE_TEXTFILE:-/opt/observability/iren_mkz/selfheal/shared/reconcile.prom}"
LOCK="${LOCK:-/opt/observability/iren_mkz/selfheal/shared/fleet-rollout.lock}"
REPAIR_SCRIPT="${REPAIR_SCRIPT:-${HERE}/repair-alloy-identity.sh}"
RESULTS="${RESULTS:-${HERE}/fleet-rollout-results.tsv}"
FLEET_NODE_REGEX="${FLEET_NODE_REGEX:-}"
[[ -n "$FLEET_NODE_REGEX" ]] || FLEET_NODE_REGEX='^example50-dh01-[d-q][0-9][0-9]-[0-9]+$'
export CLUSTER_NAME DGX_FLAVOR SHARE SSH_USER SSH_JUMP BATCH RETRIES LOKI_PUSH_URL VM_RW_PORT

log(){ echo "[fleet-rollout $(date -u +%FT%TZ)] $*"; }

# ── reentrancy: single pass at a time ────────────────────────────────────────
exec 9>"$LOCK" || { log "cannot open lock $LOCK"; exit 1; }
if ! flock -n 9; then
  log "another pass is running (lock held) — exiting cleanly"; exit 0
fi

t0=$(date +%s)

# ── 1. discover UP GB300 nodes ───────────────────────────────────────────────
# Primary: BCM live inventory (only UP nodes are reachable during bring-up).
# Fallback: static roster (recon/nodes_all.txt), status column == UP.
declare -a NODES=()
if [[ -n "${FLEET_NODES:-}" ]]; then
  read -r -a NODES <<< "$FLEET_NODES"
  log "explicit fleet override contains ${#NODES[@]} nodes"
elif bcm_out="$(ssh -o BatchMode=yes -o ConnectTimeout=15 "$BCM_SSH" \
     "${BCM_CMSH} -c 'device list -c ${BCM_CATEGORY} -f hostname:40,status:20'" 2>/dev/null)"; then
  mapfile -t NODES < <(printf '%s\n' "$bcm_out" \
    | awk 'tolower($0) ~ /(^| )up( |$)/ {print $1}' \
    | grep -E '^example50-dh01-[d-q][0-9]{2}-[0-9]+$' || true)
  log "BCM reported ${#NODES[@]} UP ${BCM_CATEGORY} nodes"
fi
if [[ "${#NODES[@]}" -eq 0 && -f "$ROSTER" ]]; then
  mapfile -t NODES < <(awk '$0 !~ /^#/ && toupper($NF)=="UP" {print $1}' "$ROSTER" \
    | grep -E '^example50-dh01-[d-q][0-9]{2}-[0-9]+$' || true)
  log "fallback roster: ${#NODES[@]} UP nodes from ${ROSTER}"
fi
if [[ "${#NODES[@]}" -gt 0 ]]; then
  declare -a FILTERED_NODES=()
  for n in "${NODES[@]}"; do
    [[ "$n" =~ $FLEET_NODE_REGEX ]] && FILTERED_NODES+=("$n")
  done
  NODES=("${FILTERED_NODES[@]}")
  log "scope regex=${FLEET_NODE_REGEX} selected ${#NODES[@]} UP nodes"
fi
if [[ "${#NODES[@]}" -eq 0 ]]; then
  log "no UP nodes to onboard this pass (fleet still in bring-up) — heartbeat only"
  # emit heartbeat and exit success (blank never means healthy: coverage is a separate metric)
fi

# ── 2. repair image-cloned identity, ensure agents, and verify every endpoint ─
# The repair runs before install-node so a stale WAL stamped with another tray's
# labels is archived before any configuration rewrite can replay it.  The
# installer is then a fast no-op on a healthy node, but restores missing agents
# after a reimage.  A final repair installs the boot guard on newly built nodes.
[[ -s "$REPAIR_SCRIPT" ]] || { log "missing repair script: $REPAIR_SCRIPT"; exit 1; }
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ConnectTimeout=10 -o ServerAliveInterval=10 -o BatchMode=yes)
[[ -n "$SSH_JUMP" ]] && SSH_OPTS+=(-J "$SSH_JUMP")

run_node(){
  local host="$1" out line verdict detail attempt rw_url env_prefix remote
  rw_url="http://${OBSVM_FABRIC_IP}:${VM_RW_PORT}/api/v1/write"
  env_prefix="$(printf 'OBSVM_FABRIC_IP=%q RW_URL=%q RELAY_RW_PORT=%q LOKI_PUSH_URL=%q CLUSTER_NAME=%q DGX_FLAVOR=%q SHARE=%q FORCE=0 ' \
    "$OBSVM_FABRIC_IP" "$rw_url" "$VM_RW_PORT" "$LOKI_PUSH_URL" "$CLUSTER_NAME" "$DGX_FLAVOR" "$SHARE")"
  remote="tmp=\$(mktemp /tmp/nvis-alloy-repair.XXXXXX); trap 'rm -f \"\$tmp\"' EXIT; cat >\"\$tmp\"; chmod 0755 \"\$tmp\"; pre=0; if command -v alloy >/dev/null && [ -s /etc/alloy/config.alloy ]; then timeout 165s \"\$tmp\" || pre=\$?; fi; install_rc=0; if [ -x ${SHARE}/install-node.sh ]; then env ${env_prefix} timeout 300s bash ${SHARE}/install-node.sh || install_rc=\$?; fi; final=0; timeout 165s \"\$tmp\" || final=\$?; svc=0; for s in alloy node_exporter cgroup-exporter dcgm-exporter; do systemctl is-active --quiet \"\$s\" || svc=1; done; ep=1; for check in 1 2 3 4 5 6; do ep=0; curl -fsS --max-time 5 http://127.0.0.1:12345/-/ready >/dev/null || ep=1; for p in 9100 9306 9400; do curl -fsS --max-time 5 http://127.0.0.1:\$p/metrics >/dev/null || ep=1; done; [ \$ep -eq 0 ] && break; sleep 3; done; if [ \$pre -eq 0 ] && [ \$install_rc -eq 0 ] && [ \$final -eq 0 ] && [ \$svc -eq 0 ] && [ \$ep -eq 0 ]; then verdict=PASS; else verdict=FAIL; fi; echo NVIS_FLEET_RESULT host=\$(hostname -s) pre=\$pre install=\$install_rc final=\$final services=\$svc endpoints=\$ep verdict=\$verdict"
  for attempt in $(seq 1 "$RETRIES"); do
    out="$(ssh "${SSH_OPTS[@]}" "${SSH_USER}@${host}" "$remote" < "$REPAIR_SCRIPT" 2>&1)"
    line="$(printf '%s\n' "$out" | grep '^NVIS_FLEET_RESULT' | tail -1)"
    [[ -n "$line" ]] && break
    printf '%s' "$out" | grep -qE 'Connection reset|kex_exchange|Connection closed|timed out|No route to host|Permission denied' || break
    sleep $(( attempt * 3 ))
  done
  if [[ -n "$line" ]]; then
    verdict="$(sed -n 's/.*verdict=\([A-Z]*\).*/\1/p' <<<"$line")"
    detail="${line#NVIS_FLEET_RESULT host=* }"
  else
    verdict=FAIL
    detail="no_result_line: $(printf '%s' "$out" | tr '\n' '|' | tail -c 200)"
  fi
  printf '%s\t%s\t%s\n' "$host" "${verdict:-FAIL}" "$detail"
}

total=${#NODES[@]}; pass=0; fail=0
: > "$RESULTS"
if (( total > 0 )); then
  tmpd="$(mktemp -d)"; trap 'rm -rf "$tmpd"' EXIT
  idx=0
  while (( idx < total )); do
    batch=( "${NODES[@]:idx:BATCH}" )
    log ">> repair batch=$((idx/BATCH+1)) nodes=${#batch[@]}"
    pids=()
    for n in "${batch[@]}"; do
      ( run_node "$n" > "${tmpd}/${n}" ) & pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p"; done
    for n in "${batch[@]}"; do
      r="$(cat "${tmpd}/${n}" 2>/dev/null)"
      [[ -n "$r" ]] || r="$(printf '%s\tFAIL\tno_output' "$n")"
      printf '%s\n' "$r" >> "$RESULTS"
      if [[ "$(cut -f2 <<<"$r")" == PASS ]]; then pass=$((pass+1)); else fail=$((fail+1)); fi
    done
    idx=$((idx+BATCH))
  done
fi

# ── 4. heartbeat textfile (consumed by fleet-health exporter :9123) ──────────
t1=$(date +%s); dur=$((t1-t0)); rc=0; [[ "$fail" -gt 0 ]] && rc=1
mkdir -p "$(dirname "$TEXTFILE")"
{
  echo "# TYPE nvis_alloy_reconcile_up gauge"
  echo "nvis_alloy_reconcile_up{cluster=\"$CLUSTER_NAME\"} 1"
  echo "# TYPE nvis_alloy_reconcile_last_run_rc gauge"
  echo "nvis_alloy_reconcile_last_run_rc{cluster=\"$CLUSTER_NAME\"} $rc"
  echo "# TYPE nvis_alloy_reconcile_nodes_total gauge"
  echo "nvis_alloy_reconcile_nodes_total{cluster=\"$CLUSTER_NAME\"} $total"
  echo "# TYPE nvis_alloy_reconcile_nodes_pass gauge"
  echo "nvis_alloy_reconcile_nodes_pass{cluster=\"$CLUSTER_NAME\"} $pass"
  echo "# TYPE nvis_alloy_reconcile_nodes_fail gauge"
  echo "nvis_alloy_reconcile_nodes_fail{cluster=\"$CLUSTER_NAME\"} $fail"
  echo "# TYPE nvis_alloy_reconcile_last_duration_seconds gauge"
  echo "nvis_alloy_reconcile_last_duration_seconds{cluster=\"$CLUSTER_NAME\"} $dur"
  echo "# TYPE nvis_alloy_reconcile_last_run_timestamp_seconds gauge"
  echo "nvis_alloy_reconcile_last_run_timestamp_seconds{cluster=\"$CLUSTER_NAME\"} $t1"
} > "${TEXTFILE}.tmp" && mv "${TEXTFILE}.tmp" "$TEXTFILE"

log "pass done total=$total pass=$pass fail=$fail dur=${dur}s rc=$rc"
exit 0
