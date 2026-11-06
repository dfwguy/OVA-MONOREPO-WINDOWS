#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
# nccl_allreduce.sbatch — direct multi-node NCCL all_reduce (host nccl-tests + mpirun).
# Author: Rafael M. Koike & Cursor Agent ("Ada")
#
# The simple, proven cross-rack NCCL test: run the HOST nccl-tests all_reduce_perf
# across the allocated nodes via mpirun, with the MPI *bootstrap* on the routable
# management net (ob1/tcp over the NS iface) and the NCCL *data path* on the IB
# compute rails (NCCL_IB_HCA). This deliberately avoids llmb-run's containerized
# UCX harness (the container exposes only tcp/IPoIB netdevs, no mlx5 verbs, so
# UCX_NET_DEVICES=mlx5_* fails). Validated on Boston at ~322 GB/s busbw (b05<->b07).
#
# Submit with: sbatch -N <n> --nodelist=<nodes> --ntasks-per-node=<gpus> \
#              --output=<logdir>/nccl-mpi_<label>_%j.out nccl_allreduce.sbatch
#SBATCH --job-name=nccl_allreduce
#SBATCH --exclusive
set -uo pipefail
# Slurm copies the batch script to a spool dir, so BASH_SOURCE points there, not at
# bin/scripts. The launcher exports NVIS_SCRIPTS_DIR so we can find lib/ reliably.
_D="${NVIS_SCRIPTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# GPUs/node: explicit env (from launcher/platform geometry) wins; else auto-detect
# on this node via nvidia-smi (NVL=4, HGX=8, …); else 4. Never hardcode a generation.
GPUS_PER_NODE="${GPUS_PER_NODE:-$(nvidia-smi -L 2>/dev/null | grep -c '^GPU')}"
[ "${GPUS_PER_NODE:-0}" -gt 0 ] 2>/dev/null || GPUS_PER_NODE=4
SIZE_MIN="${NCCL_SIZE_MIN:-8}"
SIZE_MAX="${NCCL_SIZE_MAX:-1G}"

# --- Discover the host toolchain (env overrides win; else newest matching) ------
# Generation-flexible: pick the newest-version cuda*/hpcx-* DIRECTORY present (the
# .tbz tarballs and CPU arch are handled by _pick_first). We intentionally do NOT
# key off the catalog CUDA_MAJ: it can lag the actually-staged toolchain (e.g. Boston
# GB200 is catalogued cuda12 but validated on cuda13/driver-580). For deterministic
# per-cluster pinning set NVIS_HPCX_DIR / NVIS_NCCL_TESTS_BIN / NVIS_NCCL_LIB / NVIS_CUDA_LIB.
# Return the highest-version DIRECTORY matching the first glob group that hits.
# Directory-only (so we never pick a hpcx-*.tbz tarball) and version-sorted
# (so hpcx-...cuda13 wins over ...cuda12), for deterministic, generation-safe picks.
_pick_first() {
  local p d; local -a cand
  for p in "$@"; do
    cand=()
    for d in ${p}; do [ -d "$d" ] && cand+=("$d"); done
    if [ "${#cand[@]}" -gt 0 ]; then
      printf '%s\n' "${cand[@]}" | sort -V | tail -1
      return 0
    fi
  done
}
# Every toolchain path is under the cluster's workspace (project setting connection.workspace_dir ->
# NVIS_WORKSPACE_DIR, exported to this job by run_nccl_mpi.sh's --export=ALL). This used to glob
# /home/*/workspace -- a wildcard standing in for a setting nobody had made -- which matched any
# user's workspace and, when none had the version, failed naming a literal "*".
# shellcheck source=workspace-dir-common.sh
. "${_D}/workspace-dir-common.sh" || exit 2
HPCX_DIR="${NVIS_HPCX_DIR:-$(_pick_first "${WORKSPACE_DIR}/hpcx-*cuda*" "${WORKSPACE_DIR}/hpcx-*" '/opt/hpcx*')}"
# --- NCCL version selection -----------------------------------------------------
# nccl-tests dynamically links libnccl.so.2, so the runtime NCCL version is chosen by
# which vetted lib dir is first on LD_LIBRARY_PATH (all NCCL 2.x share the soname
# libnccl.so.2 — a single test binary runs any 2.x lib). Vetted libs live on the
# NFS-shared workspace (visible on every compute node). Convention:
#   system | 2.28.9  ->  <ws>/nccl/build/lib              (system default host build)
#   <X.Y.Z>          ->  <ws>/nccl-<X.Y.Z>/nccl/build/lib  (vetted per-version build)
# Override the resolved dir with NVIS_NCCL_LIB, or the test binary with NVIS_NCCL_TESTS_BIN.
NVIS_NCCL_VERSION="${NVIS_NCCL_VERSION:-2.30.7}"
case "${NVIS_NCCL_VERSION}" in
  system|default|2.28.9) _nccl_lib_glob="${WORKSPACE_DIR}/nccl/build/lib/libnccl.so.2" ;;
  *)                     _nccl_lib_glob="${WORKSPACE_DIR}/nccl-${NVIS_NCCL_VERSION}/nccl/build/lib/libnccl.so.2" ;;
esac
if [ -n "${NVIS_NCCL_LIB:-}" ]; then
  NCCL_LIB="${NVIS_NCCL_LIB}"
else
  _nccl_lib_so="$(ls -t ${_nccl_lib_glob} 2>/dev/null | head -1)"
  [ -n "${_nccl_lib_so}" ] || { echo "nccl_allreduce: NCCL ${NVIS_NCCL_VERSION} libnccl.so.2 not found (looked: ${_nccl_lib_glob}). Build it on the NFS workspace or choose the 'system' version."; exit 2; }
  NCCL_LIB="$(dirname "${_nccl_lib_so}")"
fi
# Prefer a version-matched nccl-tests build when present; else the system build
# (ABI-compatible: a 2.28-built binary runs any 2.x libnccl loaded via LD_LIBRARY_PATH).
if [ -z "${NVIS_NCCL_TESTS_BIN:-}" ]; then
  case "${NVIS_NCCL_VERSION}" in
    system|default|2.28.9) : ;;
    *) _vt="$(ls -t "${WORKSPACE_DIR}/nccl-${NVIS_NCCL_VERSION}/nccl-tests/build/all_reduce_perf" 2>/dev/null | head -1)"; [ -n "${_vt}" ] && NVIS_NCCL_TESTS_BIN="${_vt}" ;;
  esac
fi
NCCL_TESTS_BIN="${NVIS_NCCL_TESTS_BIN:-$(ls -t "${WORKSPACE_DIR}/nccl/nccl-tests/build/all_reduce_perf" 2>/dev/null | head -1)}"
CUDA_LIB="${NVIS_CUDA_LIB:-$(_pick_first "${WORKSPACE_DIR}/cuda*/targets/*/lib" '/usr/local/cuda*/targets/*/lib')}"

[ -n "${NCCL_TESTS_BIN}" ] && [ -x "${NCCL_TESTS_BIN}" ] || { echo "nccl_allreduce: all_reduce_perf not found (set NVIS_NCCL_TESTS_BIN)"; exit 2; }

# --- Collectives ----------------------------------------------------------------
# NVIS_NCCL_COLLECTIVES (space-separated; run_nccl_mpi.sh --collectives) names the nccl-tests
# collectives this job runs, in order; each is <name>_perf next to all_reduce_perf. Default
# all_reduce, so a launch that names none (single-rack Stage 1) runs exactly as before. Every binary
# is checked before mpirun starts, so a missing one fails the job up front, not after an hour of sweeps.
COLLECTIVES="${NVIS_NCCL_COLLECTIVES:-all_reduce}"
declare -A COLL_BIN=()
for _c in ${COLLECTIVES}; do
  case "${_c}" in all_reduce|alltoall|all_gather|reduce_scatter|sendrecv) ;; *)
    echo "nccl_allreduce: unknown collective '${_c}' in NVIS_NCCL_COLLECTIVES (all_reduce alltoall all_gather reduce_scatter sendrecv)"; exit 2 ;;
  esac
  if [ "${_c}" = all_reduce ]; then COLL_BIN[${_c}]="${NCCL_TESTS_BIN}"; else COLL_BIN[${_c}]="$(dirname "${NCCL_TESTS_BIN}")/${_c}_perf"; fi
  [ -x "${COLL_BIN[${_c}]}" ] || { echo "nccl_allreduce: ${_c}_perf not found next to all_reduce_perf (${COLL_BIN[${_c}]})"; exit 2; }
done
NCOLL=$(set -- ${COLLECTIVES}; echo $#)
# A log of several collectives must be bracketed per collective, which is what the parsers split on.
# Newer nccl-tests builds print "# Collective test starting/concluded:" themselves (2.21.1 does);
# older host builds do not. Add them only for a build that does not, so a log never carries two.
MARK_COLLECTIVES=0
if [ "${NCOLL}" -gt 1 ] && ! grep -aq "Collective test starting" "${NCCL_TESTS_BIN}"; then MARK_COLLECTIVES=1; fi
[ -n "${HPCX_DIR}" ] && [ -d "${HPCX_DIR}" ] || { echo "nccl_allreduce: HPC-X not found (set NVIS_HPCX_DIR)"; exit 2; }

# --- MPI + CUDA/NCCL runtime ----------------------------------------------------
# hpcx-init.sh references unbound vars; do NOT run it under `set -u`.
set +u
# shellcheck disable=SC1090,SC1091
source "${HPCX_DIR}/hpcx-init.sh"; hpcx_load
set -u
export LD_LIBRARY_PATH="${NCCL_LIB}:${CUDA_LIB}:${LD_LIBRARY_PATH:-}"

# Optional fail-closed runtime gate used by the CUDA 13.3+/NCCL 2.31.2 preset.
# Inspect the actual linked library and selected CUDA runtime on every allocated
# node before MPI starts; setting version-looking env vars is not evidence.
if [ "${NVIS_NCCL_RUNTIME_PREFLIGHT:-0}" = "1" ]; then
  # Expected ncclGetVersion is DERIVED from the selected version, and computed HERE in the outer
  # script because the srun '...' block below forbids single quotes (it uses only double quotes).
  # X.Y.Z -> X*10000+Y*100+Z, NCCL's own encoding (2.30.7 -> 23007, 2.31.2 -> 23102); a non-numeric
  # selection (system/default) yields empty and pins nothing.
  NVIS_NCCL_WANT_VER="$(printf '%s' "${NVIS_NCCL_VERSION:-}" | awk -F. 'NF>=3{printf "%d",$1*10000+$2*100+$3}')"
  export NCCL_LIB CUDA_LIB NVIS_NCCL_VERSION NVIS_NCCL_WANT_VER
  if ! srun --kill-on-bad-exit=1 --nodes="${SLURM_JOB_NUM_NODES}" \
    --ntasks="${SLURM_JOB_NUM_NODES}" --ntasks-per-node=1 bash -euo pipefail -c '
      min_cuda="${NVIS_NCCL_MIN_CUDA_VERSION:-13.3}"
      cuda="$(printf "%s" "$CUDA_LIB" | sed -n "s#.*cuda-\{0,1\}\([0-9][0-9]*\.[0-9][0-9]*\).*#\1#p")"
      if [[ -z "$cuda" && -r "$CUDA_LIB/libcudart.so" ]]; then
        cuda="$(strings "$CUDA_LIB/libcudart.so" | sed -n "s/.*CUDA Runtime [vV]\{0,1\}\([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p" | head -1)"
      fi
      # Last resort: the libcudart SONAME carries the version (libcudart.so -> libcudart.so.13.0.96).
      # CUDA 13 toolkits install under <ws>/cuda<major> (no dot in the dir) and their libcudart no
      # longer embeds a "CUDA Runtime X.Y" string, so the two probes above both come up empty here.
      if [[ -z "$cuda" ]]; then
        cuda="$(readlink -f "$CUDA_LIB/libcudart.so" 2>/dev/null | sed -n "s#.*libcudart\.so\.\([0-9][0-9]*\.[0-9][0-9]*\).*#\1#p")"
      fi
      [[ -n "$cuda" ]] || { echo "NCCL_RUNTIME_PREFLIGHT_FAIL $(hostname): selected CUDA_LIB version unavailable: $CUDA_LIB" >&2; exit 10; }
      awk -v got="$cuda" -v want="$min_cuda" "BEGIN {split(got,g,\".\"); split(want,w,\".\"); exit !((g[1]>w[1]) || (g[1]==w[1] && g[2]>=w[2]))}" || {
        echo "NCCL_RUNTIME_PREFLIGHT_FAIL $(hostname): CUDA=$cuda requires>=$min_cuda" >&2; exit 11;
      }
      version="$(LD_LIBRARY_PATH="$NCCL_LIB:$CUDA_LIB:${LD_LIBRARY_PATH:-}" python3 - <<"PY"
import ctypes
v = ctypes.c_int()
lib = ctypes.CDLL("libnccl.so.2")
assert lib.ncclGetVersion(ctypes.byref(v)) == 0
print(v.value)
PY
)"
      [[ -z "$NVIS_NCCL_WANT_VER" || "$version" == "$NVIS_NCCL_WANT_VER" ]] || { echo "NCCL_RUNTIME_PREFLIGHT_FAIL $(hostname): ncclGetVersion=$version requires=$NVIS_NCCL_WANT_VER (NVIS_NCCL_VERSION=${NVIS_NCCL_VERSION:-})" >&2; exit 12; }
      test -d /sys/class/infiniband || { echo "NCCL_RUNTIME_PREFLIGHT_FAIL $(hostname): no InfiniBand sysfs" >&2; exit 13; }
      test -e /dev/infiniband/rdma_cm || { echo "NCCL_RUNTIME_PREFLIGHT_FAIL $(hostname): no rdma_cm" >&2; exit 13; }
      uverbs="$(find /dev/infiniband -maxdepth 1 -name "uverbs*" -type c 2>/dev/null | wc -l)"
      (( uverbs > 0 )) || { echo "NCCL_RUNTIME_PREFLIGHT_FAIL $(hostname): no uverbs character devices" >&2; exit 13; }
      active="$(grep -l "4: ACTIVE" /sys/class/infiniband/*/ports/*/state 2>/dev/null | wc -l)"
      (( active > 0 )) || { echo "NCCL_RUNTIME_PREFLIGHT_FAIL $(hostname): no ACTIVE InfiniBand port" >&2; exit 14; }
      echo "NCCL_RUNTIME_PREFLIGHT_READY $(hostname): CUDA=$cuda NCCL=${NVIS_NCCL_VERSION:-?} active_ib_ports=$active"
    '; then
    echo "NCCL_RUNTIME_PREFLIGHT_FAIL: one or more allocated nodes rejected the CUDA/NCCL/IB runtime" >&2
    exit 15
  fi
fi

# What this launch states (the cluster's nccl_env for its span, the dialog's variables) is captured
# before the fabric tuning below and restored after it: the probe's picks are defaults, and a site's
# stated value is meant to win over them (lib/stated_env.inc.sh).
# shellcheck disable=SC1091
source "${_D}/lib/stated_env.inc.sh"
nvis_stated_env_capture

# --- Fabric: NCCL on the IB rails, bootstrap on the routable NS iface -----------
# shellcheck disable=SC1091
source "${_D}/lib/fabric.inc.sh"
nvis_fabric_export || true            # sets NCCL_IB_HCA + NCCL_SOCKET_IFNAME (on-node)

# --- Per-node HCA auto-detect (NVIS_NCCL_HCA_AUTO=1) -----------------------------
# nvis_fabric_export probes the rails of the BATCH HOST ONLY, and the mpirun line below
# then broadcasts that single NCCL_IB_HCA to EVERY rank with -x. Rail state is a PER-NODE
# property: on 2026-07-28, h07 had 8 IB ports DOWN across 7 of 18 trays (h07-18 had only
# mlx5_1 up) while the batch host h07-11 had all four ACTIVE. Every rank was therefore told
# to use devices it could not open, and NCCL aborted with
#   "Detected mixed local CollNet device counts across ranks (min 1, max 4)"
#   -> "unhandled system error", rc=3, before measuring anything.
#
# With NVIS_NCCL_HCA_AUTO=1 we clear the pinned values so NCCL/UCX enumerate usable devices
# INDEPENDENTLY ON EACH NODE. This mirrors the bring-up harness's allreduce job, which never
# sets NCCL_IB_HCA at all and measures 683-698 GB/s on these same trays.
# NOTE: an EMPTY NCCL_IB_HCA means "any device" to NCCL, not "no devices" — but we must
# `unset` rather than set "", because fabric.inc.sh uses ${NCCL_IB_HCA:-default} which
# re-substitutes on empty.
if [ "${NVIS_NCCL_HCA_AUTO:-0}" = "1" ]; then
  unset NCCL_IB_HCA UCX_NET_DEVICES
  echo "nccl_allreduce: NVIS_NCCL_HCA_AUTO=1 — per-node HCA auto-detect (not pinning NCCL_IB_HCA/UCX_NET_DEVICES)"
fi
nvis_stated_env_restore nccl_allreduce

# --- NCCL network plugin, from the host's own HPC-X ------------------------------
# The cluster names its plugin as a path inside the container image (fabric.net_plugin ->
# NVIS_FABRIC_NET_PLUGIN, e.g. /opt/hpcx/nccl_spectrum-x_plugin/lib/libnccl-net-spcx.so): that is where
# the NeMo and LLMB containers load it. This job runs the host's HPC-X, which ships the same plugin at
# the same path below its own root, so resolve it there. Without this the cluster's NCCL_NET=SPCX
# reached the host job with no plugin loaded, and every rank failed with "Failed to initialize any
# NET plugin" before measuring anything (Nscale NC job 219295, 2026-10-22). A stated NCCL_NET_PLUGIN
# (cluster NCCL environment or launch dialog) wins.
if [ -z "${NCCL_NET_PLUGIN:-}" ] && [ -n "${NVIS_FABRIC_NET_PLUGIN:-}" ] && [ "${NVIS_FABRIC_NET_PLUGIN}" != none ]; then
  _plugin_rel="$(printf '%s\n' "${NVIS_FABRIC_NET_PLUGIN}" | sed -n 's#^.*/hpcx[^/]*/##p')"
  if [ -n "${_plugin_rel}" ] && [ -f "${HPCX_DIR}/${_plugin_rel}" ]; then
    export NCCL_NET_PLUGIN="${HPCX_DIR}/${_plugin_rel}"
    echo "nccl_allreduce: NCCL net plugin ${NCCL_NET_PLUGIN} (the cluster's ${NVIS_FABRIC_NET_PLUGIN}, from this host's HPC-X)"
  fi
fi
case "${NCCL_NET:-}" in
  ""|IB|Socket) ;;
  *) [ -n "${NCCL_NET_PLUGIN:-}" ] || {
       echo "nccl_allreduce: NCCL_NET=${NCCL_NET} needs a network plugin and none was found for this host job:" \
            "set the cluster's fabric.net_plugin to the plugin's path inside HPC-X (e.g." \
            "/opt/hpcx/nccl_spectrum-x_plugin/lib/libnccl-net-spcx.so; found here under ${HPCX_DIR})," \
            "or NCCL_NET_PLUGIN in the cluster's NCCL environment"
       exit 2
     } ;;
esac
# Routable mgmt iface for MPI + NCCL bootstrap. Fall back to the fabric library's own resolver
# (bond0/bond1, else the first up netdev with a global IPv4), never a literal bond0 -- GB300
# nodes have none, and that literal is what aborted mpirun before any collective ran.
NS_IF="${NCCL_SOCKET_IFNAME:-$(_nvis_fabric_ns_ifname)}"

# --- Build hostfile from the allocation -----------------------------------------
NODES="$(scontrol show hostnames "${SLURM_JOB_NODELIST}")"
NNODES="$(printf '%s\n' "${NODES}" | grep -c .)"
NP=$(( NNODES * GPUS_PER_NODE ))
HF="$(mktemp "${TMPDIR:-/tmp}/nccl_hf.XXXXXX")"
printf '%s\n' "${NODES}" | sed "s/\$/ slots=${GPUS_PER_NODE}/" > "${HF}"
trap 'rm -f "${HF}"' EXIT

# Forward custom launch env vars to the remote orted ranks. mpirun only propagates
# explicitly -x'd vars to nodes other than the one running mpirun, so without this a
# custom var (e.g. NCCL_NET_PLUGIN=none from the UI launch dialog) would silently apply
# to the local ranks only, leaving remote ranks on a different config.
#
# Two sources, UNIONED — the launch dialog's keys are ADDED to the scan, never a
# replacement for it:
#   1. scan of the batch env for NCCL_*/UCX_*/OMPI_MCA_* (what lib/fabric.inc.sh exported:
#      the plane selection, UCX_TLS, coll_ucc_enable, …).
#   2. NVIS_EXTRA_ENV_KEYS — the exact keys the app forwarded, ANY prefix, so a custom var
#      outside those three prefixes (HCOLL_*, NVIS_*, …) reaches remote ranks too.
# These used to be either/or, so supplying a single custom key from the UI silently stopped
# forwarding every scanned var: job 127306 sent only OMPI_MCA_coll_hcoll_enable and dropped
# UCX_TLS. OMPI_MCA_* are auto-propagated by mpirun, but we forward them explicitly so they
# are visible in the log line and land on every rank's env.
EXTRA_X=()
_seen=" NCCL_SOCKET_IFNAME NCCL_IB_HCA NCCL_DEBUG "   # forwarded explicitly below

# $1 = env var name. Skips vars that are unset or already queued (the two sources overlap:
# a custom OMPI_MCA_* key is also found by the scan, and -x FOO twice is not valid).
_extra_x_add() {
  _n="$1"
  case "${_seen}" in *" ${_n} "*) return 0 ;; esac
  [ -n "${!_n+x}" ] || return 0
  EXTRA_X+=( -x "${_n}" )
  _seen="${_seen}${_n} "
}

while IFS='=' read -r _k _; do
  case "${_k}" in NCCL_*|UCX_*|OMPI_MCA_*) _extra_x_add "${_k}" ;; esac
done < <(env)
for _k in ${NVIS_EXTRA_ENV_KEYS:-}; do
  _extra_x_add "${_k}"
done
if [ "${#EXTRA_X[@]}" -gt 0 ]; then
  echo "nccl_allreduce: forwarding extra env to all ranks:$(printf ' %s' "${EXTRA_X[@]}" | sed 's/ -x//g')"
fi

# Per-collective watchdog (nccl-tests -T/--timeout, seconds). nccl-tests' testStreamSynchronize
# polls with cudaStreamQuery and, if a single collective's sync exceeds this, calls ncclCommAbort
# (unblocking the stuck kernel) + prints "Test timeout" on the offending host and FAILS — instead
# of hanging forever on a degraded link/plane. 0 disables. Default 120s (a legit all_reduce at 16G
# is seconds, so this only trips on a real stall).
TEST_TIMEOUT="${NVIS_NCCL_TEST_TIMEOUT:-120}"

# Sweep rounds: run the whole all_reduce message-size sweep this many times. Stage-1
# acceptance requires N passing rounds (the app defaults single-rack Stage-1 to 5); the
# cross-rack callers leave it at 1 unless set. Any round failing fails the job (fail-fast).
ROUNDS="${NVIS_NCCL_ROUNDS:-1}"
case "${ROUNDS}" in ''|*[!0-9]*) ROUNDS=1 ;; esac
[ "${ROUNDS}" -ge 1 ] 2>/dev/null || ROUNDS=1

echo "nccl_allreduce: nodes=${NNODES} np=${NP} gpus/node=${GPUS_PER_NODE} sizes=${SIZE_MIN}..${SIZE_MAX} rounds=${ROUNDS} collectives=${COLLECTIVES}"
echo "nccl_allreduce: NCCL version=${NVIS_NCCL_VERSION} lib=${NCCL_LIB}"
echo "nccl_allreduce: bin=${NCCL_TESTS_BIN} per-collective timeout=${TEST_TIMEOUT}s (nccl-tests -T)"
echo "nccl_allreduce: NCCL_IB_HCA=${NCCL_IB_HCA:-<auto>} NCCL_SOCKET_IFNAME=${NS_IF} (MPI bootstrap: ob1/tcp over ${NS_IF})"

# MPI bootstrap over tcp/${NS_IF} (routable cross-rack); NCCL data over IB rails.
# plm=rsh launches orted via ssh across the allocated nodes (works in-allocation).
# The daemons log in as this job's user with that user's own keys, so the agent does not read the
# submitter's ~/.ssh/config: that file serves their interactive work and may remap these very hosts.
# On Nscale NC (job 136390, 270 nodes) a P2P block sent every sys1-*-su* login to the nvis-p2p
# service account with a service key, and every daemon was refused before a collective ran.
# NVIS_MPI_RSH_AGENT overrides it for a site whose node-to-node ssh genuinely needs options.
RSH_AGENT="${NVIS_MPI_RSH_AGENT:-ssh -F /dev/null -o BatchMode=yes -o StrictHostKeyChecking=accept-new}"
echo "nccl_allreduce: orted launch agent: ${RSH_AGENT}"
# One collective's run. Its own NCCL variables -- the cluster's nccl_env.collectives.<name> for this
# launch's span, sent by the app as NVIS_NCCL_ENV_<NAME> (shell code) and NVIS_NCCL_ENV_<NAME>_KEYS --
# apply in this subshell only, so alltoall's tuning never leaks into the allreduce run after it, and
# their names are forwarded with -x so every rank gets them, not only the mpirun host's.
_run_collective() {
  local c="$1" code_var keys_var k
  local -a coll_x=()
  code_var="NVIS_NCCL_ENV_${c^^}"
  keys_var="${code_var}_KEYS"
  if [ -n "${!code_var:-}" ]; then
    eval "${!code_var}"
    echo "nccl_allreduce: ${c}: its own NCCL settings:$(for k in ${!keys_var:-}; do printf ' %s=%s' "${k}" "${!k-}"; done)"
    for k in ${!keys_var:-}; do
      case "${_seen}" in *" ${k} "*) ;; *) coll_x+=( -x "${k}" ) ;; esac
    done
  fi
  local -a cmd=(mpirun -np "${NP}" --hostfile "${HF}" --map-by "ppr:${GPUS_PER_NODE}:node" --bind-to none
    --mca plm rsh --mca plm_rsh_agent "${RSH_AGENT}"
    --mca pml ob1 --mca btl tcp,self --mca btl_tcp_if_include "${NS_IF}"
    --mca oob_tcp_if_include "${NS_IF}"
    -x LD_LIBRARY_PATH -x PATH
    -x NCCL_SOCKET_IFNAME="${NS_IF}"
    ${NCCL_IB_HCA:+-x NCCL_IB_HCA="${NCCL_IB_HCA}"}
    -x NCCL_DEBUG="${NCCL_DEBUG:-WARN}"
    ${EXTRA_X[@]+"${EXTRA_X[@]}"} ${coll_x[@]+"${coll_x[@]}"}
    "${COLL_BIN[${c}]}" -b "${SIZE_MIN}" -e "${SIZE_MAX}" -f 2 -g 1 -T "${TEST_TIMEOUT}")
  # State the program exactly as it runs, so a report can hand it to someone outside Rack Status:
  # the values of everything forwarded by name (-x NAME takes the value from this environment), then
  # the command, with the temporary hostfile shown as "hosts" (one "<node> slots=N" line per node).
  local shown xk
  printf -v shown '%q ' "${cmd[@]}"
  shown="${shown//${HF}/hosts}"
  echo "nccl_allreduce: ${c}: env:$(for xk in ${EXTRA_X[@]+"${EXTRA_X[@]}"} ${coll_x[@]+"${coll_x[@]}"}; do
    case "${xk}" in -x|PATH|*=*) ;; *) printf ' %s=%q' "${xk}" "${!xk-}" ;; esac; done)"
  echo "nccl_allreduce: ${c}: LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-}"
  echo "nccl_allreduce: ${c}: command: ${shown% }"
  "${cmd[@]}"
}

rc=0
for _round in $(seq 1 "${ROUNDS}"); do
  echo "===== nccl_allreduce round ${_round}/${ROUNDS} ====="
  for _c in ${COLLECTIVES}; do
    # Markers only when this build does not print its own (MARK_COLLECTIVES above); a one-collective
    # job (Stage 1) keeps whatever format its build gives it.
    [ "${MARK_COLLECTIVES}" = 1 ] && echo "# Collective test starting: ${_c}_perf"
    ( _run_collective "${_c}" )
    _rc=$?
    [ "${MARK_COLLECTIVES}" = 1 ] && echo "# Collective test concluded: ${_c}_perf"
    if [ "${_rc}" -ne 0 ]; then
      rc=${_rc}
      echo "nccl_allreduce: round ${_round}/${ROUNDS} ${_c} FAILED rc=${_rc} (stopping)"
      break 2
    fi
  done
  echo "nccl_allreduce: round ${_round}/${ROUNDS} OK"
done
echo "nccl_allreduce: exit ${rc}"
exit ${rc}
