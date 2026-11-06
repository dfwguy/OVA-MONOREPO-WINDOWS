#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# stage-binaries.sh — populate the cluster-shared dir ($SHARE) that install-node.sh
# copies from. Run ONCE from a host that can reach the internet (or a mirror) and
# can write to the share (e.g. the head node / an admin box with the NFS mounted).
#
# Detects CPU arch automatically (arm64 for Grace / amd64 for x86) so the same
# share serves both. dcgm-exporter has no standalone release tarball — it ships
# inside NVIDIA's container image, so it is extracted from there if `docker`/
# `nerdctl` is available, otherwise you must drop the binary in by hand.
#
# Env overrides:
#   SHARE                 target dir (default /cm/shared/nvis/bin)
#   NODE_EXPORTER_VER     default 1.8.2
#   ALLOY_VER             default 1.5.1
#   CGROUP_EXPORTER_VER   default 1.2.0    (treydock/cgroup_exporter)
#   DCGM_EXPORTER_IMAGE   default nvcr.io/nvidia/k8s/dcgm-exporter:3.3.9-3.6.1-ubuntu22.04
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SHARE="${SHARE:-/cm/shared/nvis/bin}"
NODE_EXPORTER_VER="${NODE_EXPORTER_VER:-1.8.2}"
ALLOY_VER="${ALLOY_VER:-1.5.1}"
CGROUP_EXPORTER_VER="${CGROUP_EXPORTER_VER:-1.2.0}"
DCGM_EXPORTER_IMAGE="${DCGM_EXPORTER_IMAGE:-nvcr.io/nvidia/k8s/dcgm-exporter:3.3.9-3.6.1-ubuntu22.04}"

# TARGET arch — the arch of the NODES the binaries run on, NOT this staging host.
# Override with GOARCH=arm64 when staging on an x86 head for Grace/arm64 DGX.
if [[ -n "${GOARCH:-}" ]]; then
  echo ">> GOARCH overridden to ${GOARCH} (target-node arch)"
else
  case "$(uname -m)" in
    aarch64|arm64) GOARCH=arm64 ;;
    x86_64|amd64)  GOARCH=amd64 ;;
    *) echo "unsupported arch $(uname -m)" >&2; exit 1 ;;
  esac
fi
echo ">> staging into ${SHARE} for GOARCH=${GOARCH}"
mkdir -p "${SHARE}"
tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT

fetch(){ curl -fSL --retry 3 "$1" -o "$2"; }

# ── node_exporter ────────────────────────────────────────────────────────────
if [[ "${SKIP_NODE:-}" == "1" ]]; then
  echo ">> SKIP_NODE=1 — not staging node_exporter (run.ai provides :9100)"
else
echo ">> node_exporter ${NODE_EXPORTER_VER}"
fetch "https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VER}/node_exporter-${NODE_EXPORTER_VER}.linux-${GOARCH}.tar.gz" "${tmp}/ne.tgz"
tar -xzf "${tmp}/ne.tgz" -C "${tmp}"
install -m0755 "${tmp}/node_exporter-${NODE_EXPORTER_VER}.linux-${GOARCH}/node_exporter" "${SHARE}/node_exporter"
fi

# ── grafana alloy ────────────────────────────────────────────────────────────
# idempotent: skip the github download if already staged (re-runs often have the
# proxy unset for kubectl, so github is unreachable — but the binary is already here)
if [[ -f "${SHARE}/alloy" ]]; then
  echo ">> alloy already staged — leaving as-is (skip download)"
else
  echo ">> alloy ${ALLOY_VER}"
  fetch "https://github.com/grafana/alloy/releases/download/v${ALLOY_VER}/alloy-linux-${GOARCH}.zip" "${tmp}/alloy.zip"
  ( cd "${tmp}" && unzip -oq alloy.zip )
  install -m0755 "${tmp}/alloy-linux-${GOARCH}" "${SHARE}/alloy"
fi

# ── cgroup_exporter (treydock) ───────────────────────────────────────────────
if [[ "${SKIP_CGROUP:-}" == "1" ]]; then
  echo ">> SKIP_CGROUP=1 — not staging cgroup_exporter"
elif [[ -f "${SHARE}/cgroup_exporter" ]]; then
  echo ">> cgroup_exporter already staged — leaving as-is"
else
echo ">> cgroup_exporter ${CGROUP_EXPORTER_VER}"
fetch "https://github.com/treydock/cgroup_exporter/releases/download/v${CGROUP_EXPORTER_VER}/cgroup_exporter-${CGROUP_EXPORTER_VER}.linux-${GOARCH}.tar.gz" "${tmp}/cge.tgz"
tar -xzf "${tmp}/cge.tgz" -C "${tmp}"
install -m0755 "${tmp}/cgroup_exporter-${CGROUP_EXPORTER_VER}.linux-${GOARCH}/cgroup_exporter" "${SHARE}/cgroup_exporter"
fi

# ── dcgm-exporter (extract from the NVIDIA container image) ───────────────────
if [[ "${SKIP_DCGM:-}" == "1" ]]; then
  echo ">> SKIP_DCGM=1 — not staging dcgm-exporter (run.ai provides :9400 on the node)"
elif [[ -f "${SHARE}/dcgm-exporter" ]]; then
  echo ">> dcgm-exporter already staged — leaving as-is"
else
  RUNTIME=""
  command -v docker  >/dev/null 2>&1 && RUNTIME=docker
  command -v nerdctl >/dev/null 2>&1 && RUNTIME="${RUNTIME:-nerdctl}"
  if [[ -n "${RUNTIME}" ]]; then
    echo ">> dcgm-exporter — extracting from ${DCGM_EXPORTER_IMAGE} via ${RUNTIME}"
    cid="$(${RUNTIME} create "${DCGM_EXPORTER_IMAGE}")"
    ${RUNTIME} cp "${cid}:/usr/bin/dcgm-exporter" "${SHARE}/dcgm-exporter" 2>/dev/null \
      || ${RUNTIME} cp "${cid}:/usr/local/bin/dcgm-exporter" "${SHARE}/dcgm-exporter"
    ${RUNTIME} rm -f "${cid}" >/dev/null
    chmod 0755 "${SHARE}/dcgm-exporter"
  else
    echo "!! dcgm-exporter NOT staged: no docker/nerdctl to extract from ${DCGM_EXPORTER_IMAGE}."
    echo "   Copy the dcgm-exporter binary (matching your GPU driver/DCGM) to ${SHARE}/dcgm-exporter by hand."
  fi
fi

# ── dcgm-counters.csv + install-node.sh + lib + textfile collectors ──────────
here="$(cd "$(dirname "$0")" && pwd)"
install -m0644 "${here}/dcgm/dcgm-counters.csv"                    "${SHARE}/dcgm-counters.csv"
install -m0755 "${here}/install-node.sh"                          "${SHARE}/install-node.sh"
install -m0755 "${here}/repair-alloy-identity.sh"                 "${SHARE}/repair-alloy-identity.sh"
# lib-node-labels.sh is REQUIRED on-node: install-node.sh sources it from $SHARE
# to derive su/rack/datahall/tray labels + the shard. Stage it alongside.
install -m0755 "${here}/lib-node-labels.sh"                       "${SHARE}/lib-node-labels.sh"
install -m0755 "${here}/textfile-collectors/hca_verbs_collector.sh"   "${SHARE}/hca_verbs_collector.sh"

# ── DCGM install-if-missing debs (IREN_MKZ) ──────────────────────────────────
# install-node.sh:ensure_dcgm installs DCGM from ${SHARE}/dcgm-debs/*.deb when the
# host-engine is absent and there is no apt repo/internet. Drop the
# datacenter-gpu-manager*.deb (matching the Blackwell-Ultra driver) in here.
mkdir -p "${SHARE}/dcgm-debs"
if ! compgen -G "${SHARE}/dcgm-debs/*.deb" >/dev/null; then
  echo "!! ${SHARE}/dcgm-debs is empty — drop datacenter-gpu-manager*.deb here for offline"
  echo "   DCGM install-if-missing (nodes with an apt repo will apt-get it instead)."
fi

echo ">> staged contents of ${SHARE}:"
ls -l "${SHARE}"
echo ">> done. Now run alloy-rollout.sh (or fleet-rollout.sh) from the ObsVM/admin host."
