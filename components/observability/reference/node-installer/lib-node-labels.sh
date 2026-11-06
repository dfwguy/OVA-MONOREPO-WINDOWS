#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# lib-node-labels.sh — IREN_MKZ GB300 hostname → observability label + shard map
#
# Pure-bash, no deps. Sourced by BOTH:
#   - install-node.sh  (runs ON each node; derives labels for the Alloy config)
#   - fleet-rollout.sh (runs ON the ObsVM; derives each node's Prometheus shard)
#
# Source of truth for the naming grammar:
#   /opt/observability/iren_mkz/fabric/node_naming_map.md
#   example50-dh01-<SUletter><RR>-<tray>
#     SUletter  d..j  = SU1..SU7   (datahall WH1D..WH1J)
#     RR        rack ordinal 01-08 & 15-22 (09-14 = network/leaf racks, not compute)
#     tray      node index within the NVL72 rack (11..37, 18 hosts/rack)
#
# Usage:
#   source lib-node-labels.sh
#   nvis_derive_labels "example50-dh01-h05-33"
#   echo "$NVIS_SU $NVIS_SU_LETTER $NVIS_DATAHALL $NVIS_RACK $NVIS_SHARD $NVIS_RW_PORT"
#
# Sets (globals): NVIS_SU_LETTER NVIS_SU_INDEX NVIS_SU NVIS_DATAHALL
#                 NVIS_RACK_ORDINAL NVIS_RACK NVIS_TRAY_INDEX NVIS_RACKTYPE
#                 NVIS_BAND NVIS_SHARD NVIS_RW_PORT
# Returns 0 on a parseable compute hostname, 1 otherwise (labels left as "unknown").
# ─────────────────────────────────────────────────────────────────────────────

# GPU-per-host for GB300 NVL72 (8K design = 2016 hosts × 4 = 8064 GPU).
# Prometheus shard rule (PROGRAM_BRIEF): <=500 GPU per shard => <=125 hosts/shard.
NVIS_GPUS_PER_HOST="${NVIS_GPUS_PER_HOST:-4}"

# Base UDP/TCP port for the per-shard Prometheus remote_write receivers on the ObsVM.
# Shard receivers occupy NVIS_SHARD_PORT_BASE .. +NN (reserve 9200-9299).
NVIS_SHARD_PORT_BASE="${NVIS_SHARD_PORT_BASE:-9200}"

nvis_su_index_from_letter() { # d..j -> 1..7
  case "$1" in
    d) echo 1;; e) echo 2;; f) echo 3;; g) echo 4;;
    h) echo 5;; i) echo 6;; j) echo 7;;
    # 16K extension letters (SU8..SU14) — extend here as datahalls are named.
    k) echo 8;; l) echo 9;; m) echo 10;; n) echo 11;;
    o) echo 12;; p) echo 13;; q) echo 14;;
    *) echo 0;;
  esac
}

# Rack-ordinal band -> a|b|c so each SU (288 hosts) splits into 3 shards <=500 GPU.
#   a = ordinals 01-05  (5 racks, 90 hosts, 360 GPU)
#   b = ordinals 06-08,15,16 (5 racks, 90 hosts, 360 GPU)
#   c = ordinals 17-22  (6 racks, 108 hosts, 432 GPU)
nvis_band_from_ordinal() { # RR(int) -> a|b|c|x
  local o=$((10#$1))
  if   (( o>=1  && o<=5  )); then echo a
  elif (( (o>=6 && o<=8) || o==15 || o==16 )); then echo b
  elif (( o>=17 && o<=22 )); then echo c
  else echo x   # 09-14 network/leaf racks — not compute, should not appear
  fi
}

nvis_derive_labels() { # $1 = short hostname
  local h="$1"
  NVIS_SU_LETTER=unknown; NVIS_SU_INDEX=0; NVIS_SU=unknown; NVIS_DATAHALL=unknown
  NVIS_RACK_ORDINAL=unknown; NVIS_RACK=unknown; NVIS_TRAY_INDEX=unknown
  NVIS_RACKTYPE="GB300_72x1"; NVIS_BAND=x; NVIS_SHARD=unknown; NVIS_RW_PORT=0

  if [[ ! "$h" =~ ^example50-dh01-([d-q])([0-9]{2})-([0-9]+)$ ]]; then
    return 1
  fi
  local L="${BASH_REMATCH[1]}" RR="${BASH_REMATCH[2]}" TRAY="${BASH_REMATCH[3]}"
  NVIS_SU_LETTER="$L"
  NVIS_SU_INDEX="$(nvis_su_index_from_letter "$L")"
  NVIS_SU="SU${NVIS_SU_INDEX}"
  local U; U="$(printf '%s' "$L" | tr '[:lower:]' '[:upper:]')"
  NVIS_DATAHALL="WH1${U}"
  NVIS_RACK_ORDINAL="$RR"
  NVIS_RACK="WH1${U}$((10#$RR))"          # WH1H5, WH1H16 (no leading zero, per map)
  NVIS_TRAY_INDEX="$TRAY"
  NVIS_BAND="$(nvis_band_from_ordinal "$RR")"
  NVIS_SHARD="shard-${L}-${NVIS_BAND}"
  # Deterministic per-shard receiver port: base + (su-1)*3 + band_offset(a=0,b=1,c=2)
  local boff=0
  case "$NVIS_BAND" in a) boff=0;; b) boff=1;; c) boff=2;; *) boff=9;; esac
  NVIS_RW_PORT=$(( NVIS_SHARD_PORT_BASE + (NVIS_SU_INDEX-1)*3 + boff ))
  return 0
}
