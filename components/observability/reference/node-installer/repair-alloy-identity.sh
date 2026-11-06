#!/usr/bin/env bash
# Repair an Alloy config accidentally cloned from another GB300 tray.
#
# The GB300 image enables all four observability services, but older images can
# carry /etc/alloy/config.alloy from the image-building tray.  On every boot this
# guard derives the labels from the real hostname, fixes the current ObsVM sinks,
# validates the River syntax, corrects the service identity, and performs a
# bounded restart only when the config or service override changed.
set -euo pipefail

CONFIG="${NVIS_ALLOY_CONFIG:-/etc/alloy/config.alloy}"
METRICS_URL="${NVIS_OBS_METRICS_URL:-http://192.0.2.9:8429/api/v1/write}"
LOKI_URL="${NVIS_OBS_LOKI_URL:-http://192.0.2.9:3100/loki/api/v1/push}"
HOST="$(hostname -s)"
BACKUP_ROOT="${NVIS_ALLOY_BACKUP_ROOT:-/var/backups/nvis-alloy}"
ALLOY_DATA="${NVIS_ALLOY_DATA:-/var/lib/alloy/data}"
RESTART_TIMEOUT="${NVIS_ALLOY_RESTART_TIMEOUT:-30}"
READY_TIMEOUT="${NVIS_ALLOY_READY_TIMEOUT:-45}"
alloy_was_active=0
systemctl is-active --quiet alloy 2>/dev/null && alloy_was_active=1

case "$HOST" in
  example50-dh01-[d-q][0-9][0-9]-[0-9]*) ;;
  *) echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=unexpected_hostname"; exit 1 ;;
esac

suffix="${HOST#example50-dh01-}"
letter="${suffix:0:1}"
rack_ordinal="${suffix:1:2}"
tray_index="${suffix##*-}"
case "$letter" in
  d) su=SU1;; e) su=SU2;; f) su=SU3;; g) su=SU4;; h) su=SU5;;
  i) su=SU6;; j) su=SU7;; k) su=SU8;; l) su=SU9;; m) su=SU10;;
  n) su=SU11;; o) su=SU12;; p) su=SU13;; q) su=SU14;;
  *) echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=unexpected_su_letter"; exit 1 ;;
esac
upper="$(printf '%s' "$letter" | tr '[:lower:]' '[:upper:]')"
datahall="WH1${upper}"
rack="${datahall}$((10#$rack_ordinal))"

[[ -s "$CONFIG" ]] || {
  echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=missing_alloy_config"
  exit 1
}
command -v alloy >/dev/null || {
  echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=missing_alloy_binary"
  exit 1
}

# Refuse to switch a node to a sink it cannot reach.  The read endpoints prove
# both host routing and service readiness without sending or mutating data.
curl -fsS --max-time 5 "${METRICS_URL%/api/v1/write}/health" >/dev/null || {
  echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=metrics_sink_unreachable"
  exit 1
}
curl -fsS --max-time 5 "${LOKI_URL%/loki/api/v1/push}/ready" >/dev/null || {
  echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=loki_sink_unreachable"
  exit 1
}

tmp="$(mktemp /etc/alloy/.config.alloy.repair.XXXXXX)"
trap 'rm -f "$tmp"' EXIT

# Patch only explicit assignments and concrete GB300 hostnames.  Job-name
# replacements (dcgm-exporter/node-exporter/etc.) are deliberately untouched.
sed -E \
  -e "s#([[:space:]]*url[[:space:]]*=[[:space:]]*)\"http://[^\"]+/api/v1/write\"#\\1\"${METRICS_URL}\"#g" \
  -e "s#([[:space:]]*url[[:space:]]*=[[:space:]]*)\"http://[^\"]+/loki/api/v1/push\"#\\1\"${LOKI_URL}\"#g" \
  -e "s#([[:space:]]*su[[:space:]]*=[[:space:]]*)\"[^\"]*\"#\\1\"${su}\"#g" \
  -e "s#([[:space:]]*su_letter[[:space:]]*=[[:space:]]*)\"[^\"]*\"#\\1\"${letter}\"#g" \
  -e "s#([[:space:]]*datahall[[:space:]]*=[[:space:]]*)\"[^\"]*\"#\\1\"${datahall}\"#g" \
  -e "s#([[:space:]]*rack[[:space:]]*=[[:space:]]*)\"[^\"]*\"#\\1\"${rack}\"#g" \
  -e "s#([[:space:]]*rack_ordinal[[:space:]]*=[[:space:]]*)\"[^\"]*\"#\\1\"${rack_ordinal}\"#g" \
  -e "s#([[:space:]]*tray_index[[:space:]]*=[[:space:]]*)\"[^\"]*\"#\\1\"${tray_index}\"#g" \
  -e "s#example50-dh01-[d-q][0-9]{2}-[0-9]+#${HOST}#g" \
  "$CONFIG" > "$tmp"

# `alloy fmt` parses the complete River file.  A malformed candidate never
# replaces the running config.
alloy fmt "$tmp" >/dev/null

grep -qF "url = \"${METRICS_URL}\"" "$tmp"
grep -qF "url = \"${LOKI_URL}\"" "$tmp"
grep -qF "node         = \"${HOST}\"" "$tmp"
grep -qF "su           = \"${su}\"" "$tmp"
grep -qF "rack         = \"${rack}\"" "$tmp"

changed=0
if ! cmp -s "$tmp" "$CONFIG"; then
  backup_dir="${BACKUP_ROOT}/$(date -u +%Y%m%dT%H%M%SZ)-$$"
  install -d -m0700 "$backup_dir"
  install -m0600 "$CONFIG" "$backup_dir/config.alloy.before-identity-repair"
  install -m0644 "$tmp" "$CONFIG"
  changed=1
fi

# Install the guard locally so the correction is reasserted after every reboot.
if [[ "$0" != /usr/local/sbin/nvis-repair-alloy-identity ]]; then
  install -m0755 "$0" /usr/local/sbin/nvis-repair-alloy-identity
fi
unit=/etc/systemd/system/nvis-alloy-identity-repair.service
unit_tmp="$(mktemp /etc/systemd/system/.nvis-alloy-identity-repair.XXXXXX)"
cat > "$unit_tmp" <<'EOF'
[Unit]
Description=Repair NVIS Alloy sink and hostname-derived identity before startup
After=network-online.target
Before=alloy.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/nvis-repair-alloy-identity

[Install]
WantedBy=multi-user.target
EOF
if [[ ! -e "$unit" ]] || ! cmp -s "$unit_tmp" "$unit"; then
  install -m0644 "$unit_tmp" "$unit"
  systemctl daemon-reload
fi
rm -f "$unit_tmp"
systemctl enable nvis-alloy-identity-repair.service >/dev/null

dropin_dir=/etc/systemd/system/alloy.service.d
dropin="${dropin_dir}/10-nvis-identity.conf"
dropin_tmp="$(mktemp /etc/systemd/system/.alloy-identity.XXXXXX)"
cat > "$dropin_tmp" <<EOF
[Service]
Environment=HOSTNAME=${HOST}
EOF
unit_changed=0
if [[ ! -e "$dropin" ]] || ! cmp -s "$dropin_tmp" "$dropin"; then
  if [[ -e "$dropin" ]]; then
    [[ -n "${backup_dir:-}" ]] || {
      backup_dir="${BACKUP_ROOT}/$(date -u +%Y%m%dT%H%M%SZ)-$$"
      install -d -m0700 "$backup_dir"
    }
    install -m0600 "$dropin" "$backup_dir/10-nvis-identity.conf.before-repair"
  fi
  if [[ -e /etc/systemd/system/alloy.service ]]; then
    [[ -n "${backup_dir:-}" ]] || {
      backup_dir="${BACKUP_ROOT}/$(date -u +%Y%m%dT%H%M%SZ)-$$"
      install -d -m0700 "$backup_dir"
    }
    install -m0600 /etc/systemd/system/alloy.service "$backup_dir/alloy.service.before-identity-repair"
  fi
  install -d -m0755 "$dropin_dir"
  install -m0644 "$dropin_tmp" "$dropin"
  unit_changed=1
fi
rm -f "$dropin_tmp"
systemctl daemon-reload

wait_ready() {
  local elapsed=0
  while (( elapsed < READY_TIMEOUT )); do
    if curl -fsS --max-time 3 http://127.0.0.1:12345/-/ready 2>/dev/null | grep -qi ready; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

bounded_stop() {
  if timeout "${RESTART_TIMEOUT}s" systemctl stop alloy; then
    return 0
  fi
  systemctl kill --kill-who=all --signal=KILL alloy 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    systemctl is-active --quiet alloy || return 0
    sleep 1
  done
  return 1
}

archive_alloy_data() {
  [[ -e "$ALLOY_DATA" ]] || return 0
  [[ -n "${backup_dir:-}" ]] || {
    backup_dir="${BACKUP_ROOT}/$(date -u +%Y%m%dT%H%M%SZ)-$$"
    install -d -m0700 "$backup_dir"
  }
  wal_backup="${backup_dir}/alloy-data.stale"
  [[ ! -e "$wal_backup" ]] || wal_backup="${backup_dir}/alloy-data.stale.$(date -u +%s%N)"
  mv "$ALLOY_DATA" "$wal_backup"
  install -d -m0755 "$ALLOY_DATA"
  wal_recovered=1
}

wal_recovered=0
if (( changed )); then
  # The old WAL contains samples stamped with the cloned node/SU identity and
  # destined for the obsolete sink.  Never replay it under the repaired config.
  # Retain the complete tree as timestamped evidence and start with clean state.
  if (( alloy_was_active )); then
    bounded_stop || {
      echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=alloy_stop_timeout"
      exit 1
    }
  fi
  archive_alloy_data
  if (( alloy_was_active )); then
    timeout "${RESTART_TIMEOUT}s" systemctl start alloy || true
  fi
elif (( unit_changed && alloy_was_active )); then
  # Stop/start explicitly so both phases are bounded.  If Alloy cannot become
  # ready, retain its complete WAL and positions tree under the evidence root,
  # then start with a fresh storage directory.  Nothing is deleted.
  bounded_stop || {
    echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=alloy_stop_timeout"
    exit 1
  }
  timeout "${RESTART_TIMEOUT}s" systemctl start alloy || true
  if ! wait_ready; then
    bounded_stop || {
      echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=alloy_stop_timeout_before_wal_archive"
      exit 1
    }
    archive_alloy_data
    timeout "${RESTART_TIMEOUT}s" systemctl start alloy || true
  fi
fi
effective_environment="$(systemctl show alloy --property=Environment --value 2>/dev/null || true)"
[[ " $effective_environment " == *" HOSTNAME=${HOST} "* ]] || {
  echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=alloy_unit_identity_mismatch"
  exit 1
}
if (( alloy_was_active )); then
  wait_ready || {
    echo "NVIS_RESULT host=${HOST} verdict=FAIL reason=alloy_not_ready"
    exit 1
  }
fi

echo "NVIS_RESULT host=${HOST} su=${su} rack=${rack} node=${HOST} changed=${changed} unit_changed=${unit_changed} alloy_was_active=${alloy_was_active} wal_recovered=${wal_recovered} boot_guard=enabled verdict=PASS"
