#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# alloy-rollout.sh — IREN_MKZ ObsVM-side Alloy fleet pusher, driven by the static
# UP-node list (recon/nodes_up.txt). Self-contained: SSHes each UP GB300 node
# using the roster's compute IP when present,
# derives its Prometheus SHARD from the hostname, and runs the staged, idempotent
# install-node.sh with the right RW_URL. Bounded-parallel + reentrant (flock).
#
# This is the nodes_up.txt-driven sibling of fleet-rollout.sh (which discovers UP
# nodes live from BCM). Use this one when you want a deterministic roster pass
# (e.g. wired to a cron/timer) with no BCM dependency. Both are idempotent and
# reentrant, so running either on a cadence is safe.
#
#   node agent = dcgm-exporter:9400 + node_exporter:9100 + cgroup_exporter:9306
#                + alloy:12345  → remote_write to VictoriaMetrics :8429, logs → :3100
#
# ── Inputs (env, with IREN_MKZ defaults; typically from .env.fleet) ───────────
#   NODES_UP          roster file: "hostname [compute_ip]" per line, #comments ok
#                     (default /opt/observability/iren_mkz/recon/nodes_up.txt)
#   OBSVM_FABRIC_IP   ObsVM on-fabric addr nodes remote_write to (default 192.0.2.9)
#   VM_RW_PORT        host-published VictoriaMetrics port (default 8429)
#   LOKI_PUSH_URL     Loki push endpoint (default http://$OBSVM_FABRIC_IP:3100/loki/api/v1/push)
#   SHARE             BCM-shared staging dir, NFS to nodes (default /cm/shared/nvis/bin)
#   CLUSTER_NAME/DGX_FLAVOR  external labels (default IREN_MKZ / GB300)
#   SSH_USER          login user on the nodes (default root)
#   SSH_JUMP          ProxyJump spec, e.g. root@iren-hn1; empty = direct on-fabric
#   SUDO              1 = ssh unprivileged + elevate on node via passwordless sudo
#   BATCH             parallel nodes per wave (default 24)
#   RETRIES           ssh attempts per node on transient failure (default 3)
#   FORCE             1 = force reinstall even on a healthy node (default 0)
#   LOCK              flock path (default /run/nvis-alloy-rollout.lock)
#   RESULTS           results TSV (default alongside this script)
#   RECONCILE_TEXTFILE  heartbeat .prom for fleet-health :9123
#
# Exit 0 when every UP node onboarded (or nothing UP yet); 1 if any node FAILed.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${HERE}/lib-node-labels.sh"

NODES_UP="${NODES_UP:-/opt/observability/iren_mkz/recon/nodes_up.txt}"
OBSVM_FABRIC_IP="${OBSVM_FABRIC_IP:-192.0.2.9}"
VM_RW_PORT="${VM_RW_PORT:-8429}"
LOKI_PUSH_URL="${LOKI_PUSH_URL:-http://${OBSVM_FABRIC_IP}:3100/loki/api/v1/push}"
SHARE="${SHARE:-/cm/shared/nvis/bin}"
CLUSTER_NAME="${CLUSTER_NAME:-IREN_MKZ}"
DGX_FLAVOR="${DGX_FLAVOR:-GB300}"
SSH_USER="${SSH_USER:-root}"
SSH_JUMP="${SSH_JUMP:-}"
BATCH="${BATCH:-24}"
RETRIES="${RETRIES:-3}"
FORCE="${FORCE:-0}"
LOCK="${LOCK:-/run/nvis-alloy-rollout.lock}"
RESULTS="${RESULTS:-${HERE}/alloy-rollout-results.tsv}"
TEXTFILE="${RECONCILE_TEXTFILE:-/opt/observability/iren_mkz/selfheal/shared/reconcile.prom}"

log(){ echo "[alloy-rollout $(date -u +%FT%TZ)] $*"; }

# ── reentrancy: never let two passes overlap (safe on a tight cron/timer) ─────
exec 9>"$LOCK" || { log "cannot open lock $LOCK"; exit 1; }
if ! flock -n 9; then
  log "another pass is running (lock held) — exiting cleanly"; exit 0
fi

t0=$(date +%s)

# ── read the UP roster (col 1 = hostname), keep GB300-grammar names only ─────
declare -a NODES_ARR=()
declare -A NODE_CONNECT=()
if [[ -f "$NODES_UP" ]]; then
  while read -r host compute_ip _; do
    [[ "$host" =~ ^example50-dh01-[d-q][0-9]{2}-[0-9]+$ ]] || continue
    NODES_ARR+=("$host")
    NODE_CONNECT["$host"]="${compute_ip:-$host}"
  done < <(sed 's/#.*//' "$NODES_UP")
else
  log "roster $NODES_UP not found"
fi

SSH_OPTS=(-o StrictHostKeyChecking=no -o ConnectTimeout=20 -o ServerAliveInterval=10 -o BatchMode=yes)
[[ -n "${SSH_JUMP}" ]] && SSH_OPTS+=(-J "${SSH_JUMP}")

# ── per-node onboard: derive shard, ssh, run staged install-node.sh ──────────
run_node(){ # <hostname> -> "<host>\t<verdict>\t<detail>"
  local host="$1" connect out line verdict detail attempt rw_url env_prefix remote
  if ! nvis_derive_labels "$host"; then
    printf '%s\tFAIL\tunparseable_hostname\n' "$host"; return
  fi
  connect="${NODE_CONNECT[$host]:-$host}"
  rw_url="http://${OBSVM_FABRIC_IP}:${VM_RW_PORT}/api/v1/write"
  env_prefix="$(printf 'OBSVM_FABRIC_IP=%q RW_URL=%q RELAY_RW_PORT=%q LOKI_PUSH_URL=%q CLUSTER_NAME=%q DGX_FLAVOR=%q SHARE=%q FORCE=%q ' \
      "$OBSVM_FABRIC_IP" "$rw_url" "$VM_RW_PORT" "$LOKI_PUSH_URL" "$CLUSTER_NAME" "$DGX_FLAVOR" "$SHARE" "$FORCE")"
  if [[ -n "${SUDO:-}" ]]; then
    remote="sudo -n env ${env_prefix}bash ${SHARE}/install-node.sh"
  else
    remote="${env_prefix}bash ${SHARE}/install-node.sh"
  fi
  for attempt in $(seq 1 "${RETRIES}"); do
    sleep "0.$(( RANDOM % 9 ))"   # jitter to spread sshd load
    out="$(ssh "${SSH_OPTS[@]}" "${SSH_USER}@${connect}" "${remote} 2>/dev/null" 2>&1)"
    line="$(printf '%s\n' "$out" | grep -m1 '^NVIS_RESULT')"
    [[ -n "$line" ]] && break
    if printf '%s' "$out" | grep -qE 'Connection reset|kex_exchange|Connection closed|timed out|Connection refused'; then
      sleep $(( attempt * 3 )); continue
    fi
    break
  done
  if [[ -n "$line" ]]; then
    verdict="$(sed -n 's/.*verdict=\([A-Z]*\).*/\1/p' <<<"$line")"
    detail="$(sed -n 's/^NVIS_RESULT host=[^ ]* //p' <<<"$line")"
  else
    verdict="FAIL"; detail="no_result_line: $(printf '%s' "$out" | tr '\n' '|' | tail -c 160)"
  fi
  printf '%s\t%s\t%s\n' "$host" "${verdict:-FAIL}" "connect=${connect} target=${rw_url} ${detail}"
}

echo "════════════════════════════════════════════════════════════════"
echo "  NVIS IREN_MKZ alloy-rollout (roster=${NODES_UP})"
echo "  up_nodes=${#NODES_ARR[@]}  batch=${BATCH}  jump=${SSH_JUMP:-<direct>}  share=${SHARE}"
echo "════════════════════════════════════════════════════════════════"
: > "${RESULTS}"

pass=0; fail=0; total=0
if [[ "${#NODES_ARR[@]}" -eq 0 ]]; then
  log "no UP GB300 nodes in ${NODES_UP} (fleet in bring-up) — heartbeat only"
else
  tmpd="$(mktemp -d)"; trap 'rm -rf "$tmpd"' EXIT
  total=${#NODES_ARR[@]}; idx=0
  while (( idx < total )); do
    batch=( "${NODES_ARR[@]:idx:BATCH}" )
    echo ">> batch $((idx/BATCH+1)): ${batch[*]}"
    pids=()
    for n in "${batch[@]}"; do
      ( run_node "$n" > "${tmpd}/${n}" ) &
      pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p"; done
    for n in "${batch[@]}"; do
      r="$(cat "${tmpd}/${n}" 2>/dev/null)"
      [[ -z "$r" ]] && r="$(printf '%s\tFAIL\tno_output' "$n")"
      echo "${r}" >> "${RESULTS}"
      v="$(cut -f2 <<<"$r")"
      if [[ "$v" == "PASS" ]]; then ((pass++)); printf '   [PASS] %s\n' "$n"
      else ((fail++)); printf '   [FAIL] %s :: %s\n' "$n" "$(cut -f3 <<<"$r")"; fi
    done
    idx=$((idx+BATCH))
  done
  rm -rf "$tmpd"; trap - EXIT
fi

# ── heartbeat textfile (consumed by fleet-health exporter :9123) ─────────────
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

echo "════════════════════════════════════════════════════════════════"
echo "  RESULT: PASS=${pass}  FAIL=${fail}  total=${total}  dur=${dur}s"
echo "  matrix: ${RESULTS}"
echo "════════════════════════════════════════════════════════════════"
[[ "$fail" -eq 0 ]] && exit 0 || exit 1
