#!/usr/bin/env bash
set -euo pipefail
kit=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ $(uname -s) == Linux ]] || { echo 'Run this on the approved Linux management host, not Windows.' >&2; exit 64; }
python_bin=${PYTHON_BIN:-python3.12}
command -v "$python_bin" >/dev/null || { echo 'CPython 3.12 with venv/pip is required on the offline Linux host.' >&2; exit 69; }
"$python_bin" - <<'PY'
import sys,platform
assert sys.version_info[:2] == (3,12), 'This wheelhouse targets CPython 3.12 only'
assert platform.python_implementation() == 'CPython'
libc,version=platform.libc_ver()
assert libc == 'glibc' and tuple(map(int,version.split('.')[:2])) >= (2,28), 'glibc >=2.28 required by staged wheels'
PY
case $(uname -m) in
 x86_64) wheels="$kit/offline/wheels-linux-x86_64-py312" ;;
 aarch64|arm64) wheels="$kit/offline/wheels-linux-aarch64-py312" ;;
 *) echo 'Only Linux x86_64 or aarch64 wheels are staged.' >&2; exit 64 ;;
esac
[[ -f "$kit/source/static/spa/index.html" ]] || { echo 'Built SPA missing.' >&2; exit 66; }
[[ ${1:---check} == --check || ${1:---check} == --install ]] || { echo 'Usage: prepare-linux.sh [--check|--install]' >&2; exit 64; }
if [[ ${1:---check} == --check ]]; then
 echo "Preflight OK: $python_bin; $wheels. No files installed and no services started."
 exit 0
fi
cd "$kit/source"
if [[ ! -d .venv ]]; then "$python_bin" -m venv .venv; fi
.venv/bin/python - <<'PY'
import sys
assert sys.version_info[:2] == (3,12), 'Existing .venv is not Python 3.12; preserve it and select another install location'
PY
.venv/bin/python -m pip install --no-index --find-links "$wheels" -r backend/requirements.txt
.venv/bin/python -m pip check
printf '%s\n' "Installed offline. Start from source with:" "NVIS_OFFLINE_WHEELHOUSE='$wheels' BUILD_FRONTEND=0 RACK_WEB_BIND_ADDR=127.0.0.1 RACK_STATUS_DEMO=0 ./start.sh"
