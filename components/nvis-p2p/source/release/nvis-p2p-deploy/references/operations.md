# Phase gates and exception policy

Read this before a live first deployment, major expansion, rollback, or multi-node repair.

| Phase | Entry gate | Exit gate |
|---|---|---|
| Discovery | Required variables and secret paths supplied | Release/inputs valid; no collision |
| Server | Rendered config valid | Required health checks pass |
| Canary clients | Eligible canary nonempty | Peer socket, units, digests valid |
| Persistence | Canonical size/digest valid | Receipt per selected image |
| Canary sync | Peer/persistence healthy | Current-wave `failed=0`; receipts valid |
| Expansion | Canary accepted | Explicit complete/deferred roster per SU |
| Close | No unclassified node | No pending; reachable eligible complete |

Retry boundedly: timeout, temporary no-route, connection reset, transient systemd start failure, or an active transfer making measurable progress.

Defer without blind retry: host-key change, public-key denial, unexpected identity, wrong architecture/page size, unsafe secret mode, insufficient disk, checksum/catalog mismatch, permission anomaly, invalid roster, or missing authorization.

An inactive service without the current marker is `FAILED marker_missing`. A full-size partial is incomplete until export, digest, atomic install, receipt, and marker all succeed.

Scale from a tiny canary to an SU, then multiple SUs. Increase concurrency only after measuring scheduler, Redis, seeds, object store, fabric, and disk. Retain requested/eligible/deferred rosters, rendered-config digest, persistence receipts, operation metadata/logs, sync tracking/summary, verification TSV, and exact exceptions.

