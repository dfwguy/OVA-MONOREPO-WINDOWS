# CI/CD factory publication contract

Return to [README](../README.md). This kit follows the factory's artifact-intake, validation and human-reviewed publication boundary. Having a GitLab CI file does not enroll a project in the resident controller or prove the controller is operating on it.

## Intake and remediation

1. Retrieve the authorized source and verify its supplied integrity metadata in a local review workspace.
2. Treat deployment snapshots as evidence, not generic launch instructions. Remove customer identifiers, live inventory, fixed-site paths, historical batch jobs and secret-bearing payloads from the distributable tree.
3. Rebuild customer-neutral documentation/configuration/helpers. Keep platform-dependent settings explicit and official workload semantics intact.
4. Validate current source/configuration/integrity boundaries, documentation navigation, and passive publication policy. Perform external secret/malware/license/provenance checks where required by the delivery path.
5. Publish a feature branch and MR with the exact source commit, change summary, validation evidence and remaining live-environment limitations.
6. Observe the exact commit's GitLab pipeline and resolve failures without bypassing policy. Human reviewers approve and merge.

The initial imported snapshot remains in pre-existing Git history unless the repository owner authorizes a coordinated history migration. Deleting the files from a revision removes them from that revision's distributable tree; it does not purge old Git objects. Do not force-push shared history or claim historical erasure without performing and verifying that separate operation.

## Validation performed by this project

| Check | Evidence | Boundary |
| --- | --- | --- |
| Input validation tests | Test cases for placeholders, source pinning, node/scale and secret/reference errors | Structural inputs only |
| Payload integrity tests | Tampering, added/missing files, unsafe paths/links, credential paths, internal cache links | Reviewed file payloads |
| Repository publication check | File inventory, disallowed identifiers/addresses/jobs/archives, credential patterns, local Markdown links | Tracked distributable tree |
| Python compile | Standard-library helper/test syntax | No remote execution |
| CI lint | Effective GitLab configuration accepted by target GitLab | Pipeline structure only |
| Pipeline run | Exact source-SHA terminal status and retained reports | CPU-only repository validation |

CI uses the group's Linux Docker runner tags and a Python image, contains no deployment secrets, runs no customer commands and publishes a bounded validation report. No container/model downloads are necessary for its tests. Live installation/fabric/recipe validation remains in the operator's environment.

## Optional NVFTP envelope delivery

The established control-plane artifact contract uses four sibling files: `<artifact>.MANIFEST.json`, `<artifact>.SHA256SUMS`, `<artifact>.git.bundle`, and `<artifact>.tar.gz`. Source tar and Git bundle must represent the same sanitized committed tree. The manifest declares exact target/source-kind/base commit and the responsible human's classification attestation. Obtain that attestation through the factory process; an agent must not invent it.

Use the deployed control plane's reviewed packaging tool from a clean checkout. Re-run checksum, archive/path safety, history and payload secret scans, malware/provenance review and tar/bundle tree-equivalence gates before ingestion. Publishing an envelope is a separate authorized delivery operation; CI on this repository does not upload to NVFTP automatically.

## Optional resident agent-loop adoption

If the operator wants ongoing issue-driven maintenance, use the approved OVA agentic workflow adoption process. Inspect current template compatibility, project-owned settings, service account scope, protected branch/MR policy, runner availability, retained checkout/worktree location and timer/ledger configuration. Follow its applicable agent/workflow instructions when adopting it; do not install a competing controller or claim adoption from this document alone.

This revision provides the repository checks and publication contract. It does not alter the existing factory's routing allowlists, credentials, services, template policy or timers. Those are governed operational inputs, separate from the target cluster's deployment configuration.
