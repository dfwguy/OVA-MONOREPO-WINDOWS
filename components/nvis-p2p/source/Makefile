SHELL := /usr/bin/env bash
.DEFAULT_GOAL := verify

.PHONY: fetch fetch-sources fetch-artifacts build-client-amd64 build-client-arm64-64k install-client-amd64 build-server manifests verify stage render-check install-check

fetch: fetch-sources fetch-artifacts

fetch-sources:
	./scripts/fetch-upstream-sources.sh

fetch-artifacts:
	./scripts/fetch-upstream-artifacts.sh

build-client-amd64:
	./scripts/build-dragonfly-client.sh amd64 upstream/client-v1.4.9

build-client-arm64-64k:
	./scripts/build-dragonfly-client.sh arm64-64k upstream/client-v1.4.9

install-client-amd64:
	./scripts/install-official-client.sh

build-server:
	./scripts/build-dragonfly-server.sh --from-source upstream/dragonfly

manifests:
	./scripts/refresh-release-manifests.sh

verify:
	./scripts/verify-release-inputs.sh

stage:
	./scripts/prepare-release-tree.sh

render-check:
	@test -n "$(CLUSTER_ENV)" || { echo 'CLUSTER_ENV is required' >&2; exit 64; }
	./scripts/render-site-config.py --env "$(CLUSTER_ENV)" --check

install-check:
	@test -n "$(CLUSTER_ENV)" || { echo 'CLUSTER_ENV is required' >&2; exit 64; }
	./scripts/install-nvis-p2p.py --env "$(CLUSTER_ENV)" --check
