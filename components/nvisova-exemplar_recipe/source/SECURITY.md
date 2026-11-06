# Security and private deployment data

Provision credentials through approved secure files or secret managers. Store only references in private deployment configuration. Never add tokens, keys, scheduler authentication secrets, registry credential files, live inventory, raw environment dumps or deployment result archives to Git.

Inspect upstream-generated installation configuration and batch scripts for persisted secret values before staging or sharing. HF cache delivery must exclude token/stored-token files. Offline payload hashing is integrity checking against a trusted manifest; maintain the organization's provenance/signing, malware and license/transfer review separately.

The helper's small-file pattern scan is passive and bounded. It does not establish absence of all secrets in large/binary artifacts. Factory scanning and human inspection remain necessary. Incoming archives and helper source require review before use; do not extract an unreviewed payload into system directories or execute stale batch scripts.

Report credential exposure through the repository owner's approved private incident channel. Do not include secret values in an issue/MR or automatically contact third parties. Stop dependent distribution, preserve bounded non-secret evidence and use the owner's rotation procedure.

For deployment operations, preserve host verification and authorized scope. Driver/kernel changes, GPU resets, reboots and network mutation require the approved maintenance procedure. Repository CI has no authority to deploy to a target cluster.
