# Export, handover and validation-hub reference

Return to [README](../README.md). Preserve every validation attempt and keep scheduler outcome, validation result and qualification separate. Future reference comparisons need workload and hardware/software compatibility, not only a job ID or a throughput number.

## Finalize the campaign

Confirm the agreed campaign end and stop new validation submissions under the operator's procedure. Let running jobs terminate normally. Retain completion/accounting and run directories until all declared final files are hash-verified. Reconcile actual independent scheduler inventory, runner manifests, host inventories, collector jobs, errors and gaps. Classify any unused numeric IDs instead of assuming every number was a run.

The export operation locks publication and snapshots committed state; collectors can continue writing later state. To include final arrivals, first confirm source and queue completion, then export the chosen generation. Exporting a snapshot does not prove all source data has arrived. Do not disable evidence collection merely because a hub transfer is slow.

## Create and independently verify

Run as the installed collection identity with the actual paths:

```sh
export SLURM_HISTORY_CONFIG=/var/lib/slurm-evidence/<cluster>/<epoch>/cluster.json
/var/lib/slurm-evidence/<cluster>/<epoch>/venv/bin/python \
  /var/lib/slurm-evidence/<cluster>/<epoch>/app/history.py export
```

The operation writes a local archive and a SHA-256 sidecar beneath `export/`. Transfer both through the authorized channel. Verify the archive checksum, inspect member names, and extract into an empty recipient review directory using a traversal-safe archive tool. Then run:

```sh
python3 tools/verify_export.py /path/to/extracted-export
# Reconstruct one selected stored payload if needed:
python3 tools/verify_export.py /path/to/extracted-export --stored-sha256 <hash> --output /private/path/reconstructed.log
```

The verifier queries artifact references using DuckDB, verifies ordered contiguous chunk offsets and rebuilds every selected stored payload hash. Original unredacted bytes are not recoverable when redaction changed them. Verify them against retained original source only within the owner's approved environment.

## Hub import contract

| Field | Recipient rule |
| --- | --- |
| Site/tenant, cluster, epoch | Isolate ownership and namespace job IDs; never join across clusters by numeric ID alone |
| Schema/parser versions | Preserve compatibility and units; reject unknown schema with an explicit receipt |
| Artifact version/hash | Idempotent import key; verify stored payload SHA-256 before acceptance |
| Job/step/run identity | Preserve actual identity; unsupported arrays/components remain gaps until adapted |
| Workload/config/environment provenance | Compare compatible versions, scale, model/dtype and validation conditions |
| Result state | Preserve scheduler completion, validation and qualification separately; unknown stays unknown |
| Coverage/errors/redaction | Retain limitations with evidence; gaps cannot be transformed into passes |
| Export checksum and imported generation | Record immutable receipt and deduplicate repeat transfer |
| Authorization/retention | Apply recipient ACLs, approved data classification and lifecycle policy |

The bundle contains no fixed hub endpoint or upload credential. It supplies local verified exports and a schema contract. The actual validation hub needs its own importer/API, authorization and readback receipt. Once integrated, verify row counts, artifact hashes and scope in the destination before accepting handover or deleting local evidence.

Back up the lake before handover. Keep source originals and collector state until the owner confirms archive integrity, retention and recipient acknowledgement. Avoid comparing diagnostic runs with qualification baselines without their applicable criteria.
