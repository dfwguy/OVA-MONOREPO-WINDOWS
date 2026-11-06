#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
# ci-local.sh -- run the CI test jobs locally, in the images CI runs them in.
#
#   bin/ci-local.sh [python|frontend|integration|all] [TREE]
#
# python    the `python-test` job: python:3.12-slim, the job's apt and pip installs, the whole
#           backend suite with coverage, then the coverage floor.
# frontend  the `typescript-check` and `frontend-test` jobs: node:24-slim, tsc + eslint, vitest with
#           coverage, the production build and the offline check.
# integration the `integration-test` job: backend/tests/integration/ against the bundle the frontend
#           job built into TREE/static/spa (run `frontend` first, or `all`, which orders them).
# TREE      the checkout to test (default: this repository). Point it at a scratch worktree to test a
#           commit without whatever else is uncommitted in your working tree.
#
# Why not just run the suites on the laptop: a Mac is not where any of this runs. BSD `stat` has no
# `-c`, and /bin/bash 3.2 drops output written through `exec > >(tee ...)` and does not stop on a
# failing bare `[[ ]]` under `set -e` -- the P2P script tests failed on macOS for reasons that do not
# exist on the nodes, the app server, or CI. The images here are the reference; the pins below are
# checked against .gitlab-ci.yml by backend/tests/test_ci_job_tooling.py, so they cannot drift.
#
# node_modules and the npm/pip caches live in docker volumes (ci-local-*), never in TREE: the Linux
# build of native packages (esbuild, rolldown) must not overwrite the host's, or the reverse.
set -euo pipefail

PYTHON_IMAGE=python:3.12-slim
NODE_IMAGE=node:24-slim
# The python-test job's apt line, package for package.
PYTHON_APT_PACKAGES="rsync squashfs-tools curl procps"

job=${1:-all}
tree=$(cd "${2:-$(dirname "$0")/..}" && pwd)
command -v docker >/dev/null || { echo "ci-local: docker is required" >&2; exit 2; }
[[ -f $tree/backend/requirements.txt && -f $tree/frontend/package.json ]] || {
  echo "ci-local: $tree is not a Rack Status checkout" >&2; exit 2; }

run_python() {
  echo "== python-test ($PYTHON_IMAGE) on $tree =="
  docker run --rm -v "$tree:/w" -w /w -v ci-local-pip:/root/.cache/pip -e PYTHONDONTWRITEBYTECODE=1 \
    "$PYTHON_IMAGE" bash -c "
      set -euo pipefail
      pip install -q -r backend/requirements.txt -r backend/requirements-dev.txt
      apt-get update -qq && apt-get install -y -qq --no-install-recommends $PYTHON_APT_PACKAGES >/dev/null
      python -m pytest backend/tests/ --ignore=backend/tests/integration -q -p no:cacheprovider --tb=short \
        --cov --cov-config=.coveragerc --cov-report=json:/tmp/coverage.json
      python bin/check-coverage-floor.py /tmp/coverage.json"
}

run_frontend() {
  echo "== typescript-check + frontend-test ($NODE_IMAGE) on $tree =="
  docker run --rm -v "$tree:/w" -w /w/frontend \
    -v ci-local-node-modules:/w/frontend/node_modules -v ci-local-npm:/root/.npm \
    "$NODE_IMAGE" bash -c "
      set -euo pipefail
      npm ci --ignore-scripts --no-audit --no-fund >/dev/null
      npx tsc -b --noEmit
      npm run lint
      npx vitest run --coverage --coverage.reporter=text-summary
      npm run build
      cd .. && bash bin/check-frontend-offline.sh"
}

run_integration() {
  echo "== integration-test ($PYTHON_IMAGE) on $tree =="
  # As in CI: refuse rather than skip -- every case is guarded on the bundle, so without it the job
  # would pass having run nothing.
  [[ -f $tree/static/spa/index.html ]] || {
    echo "ci-local: $tree/static/spa/index.html missing -- run the frontend job first" >&2; return 1; }
  docker run --rm -v "$tree:/w" -w /w -v ci-local-pip:/root/.cache/pip -e PYTHONDONTWRITEBYTECODE=1 \
    "$PYTHON_IMAGE" bash -c "
      set -euo pipefail
      pip install -q -r backend/requirements.txt -r backend/requirements-dev.txt
      python -m pytest backend/tests/integration/ -q -p no:cacheprovider --tb=short"
}

case $job in
  python) run_python ;;
  frontend) run_frontend ;;
  integration) run_integration ;;
  all) rc=0; run_python || rc=1; run_frontend && { run_integration || rc=1; } || rc=1; exit $rc ;;
  *) echo "usage: $0 [python|frontend|integration|all] [TREE]" >&2; exit 64 ;;
esac
