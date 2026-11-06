# CI/CD factory publication contract

Return to [README](../README.md). This project follows the intake and human-reviewed publication pattern used for the Exemplar deployment kit.

1. Download only the authorized NVFTP package; verify supplied checksums and archive paths in a private intake directory.
2. Inspect its portable and deployed-reference implementations separately. Exclude reference deployments, live health receipts, customer raw evidence, identities/inventory, secrets, checkpoints and exports from both Git history and bundles.
3. Create cluster agnostic source, explicit example settings, architecture/documentation, deployment tooling and evidence tests. Do not insert real cluster settings to make a demo work.
4. Run behavior tests, dependency checks, Python compilation, systemd unit verification, tracked-tree publication checks and documentation/SVG validation.
5. Create the private project and publish the reviewed change on a feature branch through a merge request. Retain exact commit, local receipts and pipeline evidence. Humans approve and merge.
6. Build a source download bundle from the committed tracked tree, including a complete payload manifest and archive checksum. CI artifacts contain software only; no fixture lake, target data or secrets.

The NVFTP source archive's hash is retained as provenance. Original source/reference files stay outside the repository, so deleting them in a later commit is not used as a claim of historical removal. Source code and dependency licenses require the applicable internal distribution review; no new third-party license grant is invented.

GitLab CI validates this repository with the group's Linux Docker runner tags. It installs declared test dependencies, runs isolated fixture/behavior tests, validates publication policy, compiles source, checks unit rendering and publishes test reports plus the download bundle. It performs no customer deployment, Slurm mutation or hub upload. Exact-SHA pipeline status is verified before reporting publication as passing.

The repository publication scanner checks known prohibited identifiers, secret patterns, payload/database/archive paths and local Markdown links. These bounded checks are not an exhaustive malware or legal audit. External scanning/attestation remains governed by the delivery environment. Never weaken tests or data-exclusion checks to make CI green.

A CI file alone does not enroll the project in the resident factory issue controller. This delivery does not change its routing allowlists, timers, service-account permissions or workflow policy. If ongoing issue-driven adoption is requested, follow that project's documented adoption process separately. No fake controller-enrollment or multi-agent review receipt is produced.
