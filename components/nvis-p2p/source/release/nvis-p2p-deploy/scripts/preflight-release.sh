#!/usr/bin/env bash
set -euo pipefail

required_vars=(
  NVIS_P2P_RELEASE NVIS_P2P_CONTROL_IP NVIS_P2P_MANAGEMENT_IP
  NVIS_P2P_CANONICAL_DIR NVIS_P2P_INVENTORY NVIS_P2P_SSH_USER
  NVIS_P2P_NODE_CONTAINER_DIR NVIS_P2P_OBJECT_DATA NVIS_P2P_SEED_CACHE
  NVIS_P2P_SEED2_CACHE NVIS_P2P_CONSOLE_PORT NVIS_P2P_SU_COUNT
  NVIS_P2P_NODES_PER_SU NVIS_P2P_EXPECTED_ARCH NVIS_P2P_EXPECTED_PAGE_SIZE
  NVIS_P2P_MANAGER_ENV_FILE NVIS_P2P_DFSTORE_IMPORT_ENV_FILE
  NVIS_P2P_DFSTORE_READONLY_ENV_FILE NVIS_P2P_OBJECT_ROOT_PASSWORD_FILE
)
missing=()
for name in "${required_vars[@]}"; do
  [[ -n ${!name:-} ]] || missing+=("$name")
done
if ((${#missing[@]})); then
  printf 'NVIS_P2P_PREFLIGHT_MISSING variable=%s\n' "${missing[@]}" >&2
  exit 64
fi

root=$(realpath -e -- "$NVIS_P2P_RELEASE")
[[ $root == /* && $root != / ]] || { echo 'NVIS_P2P_PREFLIGHT_BAD_RELEASE_PATH' >&2; exit 64; }
required_files=(
  catalog/images.json catalog/images.tsv configs/peer.template.yaml
  deploy/systemd/nvis-p2p-peer.service deploy/systemd/nvis-p2p-catalog-sync.service
  scripts/catalog-operation.sh scripts/preflight-catalog-fleet.sh
  scripts/deploy-catalog-peer-fleet.sh scripts/sync-catalog-service-fleet.sh
  scripts/verify-catalog-node.sh
)
for path in "${required_files[@]}"; do
  [[ -r $root/$path ]] || { printf 'NVIS_P2P_PREFLIGHT_MISSING_ASSET path=%s\n' "$path" >&2; exit 66; }
done

for path in "$NVIS_P2P_CANONICAL_DIR" "$NVIS_P2P_INVENTORY" \
  "$NVIS_P2P_OBJECT_DATA" "$NVIS_P2P_SEED_CACHE" "$NVIS_P2P_SEED2_CACHE"; do
  [[ $path == /* && -e $path ]] || { printf 'NVIS_P2P_PREFLIGHT_BAD_PATH path=%s\n' "$path" >&2; exit 66; }
done
for path in "$NVIS_P2P_MANAGER_ENV_FILE" "$NVIS_P2P_DFSTORE_IMPORT_ENV_FILE" \
  "$NVIS_P2P_DFSTORE_READONLY_ENV_FILE" "$NVIS_P2P_OBJECT_ROOT_PASSWORD_FILE"; do
  [[ $path == /* && -f $path ]] || { printf 'NVIS_P2P_PREFLIGHT_BAD_SECRET_FILE path=%s\n' "$path" >&2; exit 66; }
  mode=$(stat -c '%a' "$path")
  (( (8#$mode & 8#077) == 0 )) || { printf 'NVIS_P2P_PREFLIGHT_UNSAFE_SECRET_MODE path=%s mode=%s\n' "$path" "$mode" >&2; exit 67; }
done

[[ $NVIS_P2P_CONSOLE_PORT =~ ^[0-9]+$ && $NVIS_P2P_CONSOLE_PORT -le 65535 ]] || { echo 'NVIS_P2P_PREFLIGHT_BAD_CONSOLE_PORT' >&2; exit 64; }
[[ $NVIS_P2P_SU_COUNT =~ ^[1-9][0-9]*$ && $NVIS_P2P_NODES_PER_SU =~ ^[1-9][0-9]*$ ]] || { echo 'NVIS_P2P_PREFLIGHT_BAD_FLEET_DIMENSIONS' >&2; exit 64; }

python3 -m json.tool "$root/catalog/images.json" >/dev/null
bash -n "$root"/scripts/*.sh
printf 'NVIS_P2P_PREFLIGHT_OK release=%s catalog_rows=%s inventory_rows=%s\n' \
  "$root" \
  "$(awk -F '\t' 'NR>1{n++} END{print n+0}' "$root/catalog/images.tsv")" \
  "$(awk 'NF && $1 !~ /^#/ {seen[$1]=1} END{print length(seen)}' "$NVIS_P2P_INVENTORY")"
