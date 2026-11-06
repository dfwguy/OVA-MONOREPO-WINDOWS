# Download, deploy and start collecting

Return to [README](../README.md). Run installation on a designated collector host. This guide creates collection services; it does not provision Slurm, reimage nodes or run cluster validations.

## Prepare once

The automated baseline is a systemd Linux host with Python 3.12+, `python3-venv`, GNU `findmnt`, account-management tools, `runuser`, OpenSSH and `systemd-analyze`. Install these with the platform's package manager before running the installer. Test wheel availability for the target Python/CPU/libc platform. Dedicated collector storage avoids competing with GPU workloads; do not place the SQLite WAL on NFS. Shared run-artifact directories can be network mounted while collector state is local persistent storage.

Copy `examples/cluster.example.json` outside the checkout. Every cluster needs its own identity and epoch, narrow local/remote roots, real controller/completion paths, Slurm binary directory and service unit. `root` must be `/var/lib/slurm-evidence/<cluster>/<epoch>`. Identity placeholders cause `deploy.py` to fail. No GPU count, vendor-specific node name, scheduler installation path or fixed customer inventory is assumed.

Create approved run directories before deployment. Grant the collection identity read/search ACLs on controller/completion logs and durable run roots. Grant authorized runners write access only to their run directories and trusted `state/runner-manifests`; keep service code and secrets root-owned. Prefer default ACLs so new files retain the right reader permissions. Decide source retention before commissioning: worst allowed outage + fleet revisit time + export/verification margin. ACL policy is platform-specific and cannot safely be inferred from job owners.

The example defaults to local/shared artifact capture (`remote_capture_enabled=false`) and performs no compute-node SSH reads. For remote node-local capture, set `remote_capture_enabled=true` and provision a dedicated read-only SSH identity, known-host entries and allowlisted run roots on every scoped node. The collector never disables host-key checking. For a shared-artifact deployment, remote access can remain unused, but native completion and shared logs must still be retained. A remote path alone is not proof it is readable or persistent across reboot.

## Installation commands

```sh
python3 tools/deploy.py plan --config /etc/ova-collection/cluster.json --output /var/tmp/ova-plan
# Inspect rendered source, units and deployment-plan.json.
sudo python3 tools/deploy.py apply --config /etc/ova-collection/cluster.json --output /var/tmp/ova-install
```

The two output directories are distinct and empty. `plan` writes review files only. `apply` installs fresh source/dependencies, creates a non-root collection account, generates a token without printing its value, tests access as that account and enables browser/timers/watchdog. Filesystem checks reject tmpfs/ramfs/overlay; the operator must verify persistent mount configuration and backup. The installer leaves failed/partial installation intact; fix the failure and follow manual installation or rollback rather than deleting evidence.

Existing durable completion and accounting are reused. For a fresh cluster using a standalone Slurm config with no existing completion plugin, the same installation command can configure the native completion plugin:

```sh
sudo python3 tools/deploy.py apply --config /etc/ova-collection/cluster.json --output /var/tmp/ova-install \
  --configure-jobcomp /etc/slurm/slurm.conf --slurm-user slurm
```

This explicit option creates a durable completion file, backs up the config, appends `JobCompType=jobcomp/filetxt` and `JobCompLoc`, then invokes `scontrol reconfigure`. It never reboots nodes. Existing different plugins, included configurations and mismatched filetxt paths are rejected for site adaptation. Check Slurm's effective config, all HA controllers and permissions before choosing this option. A failed reconfigure restores the config file but requires inspection of running scheduler state. Existing slurmdbd/accounting is not installed or replaced. A scheduled maintenance window may be necessary under local scheduler policy.

## Offline dependencies

On an approved connected host with the same Python/OS/architecture as the collector:

```sh
python3 -m pip download --only-binary=:all: -r app/requirements.lock -d /var/tmp/ova-wheelhouse
# Independently inventory/hash and scan that wheelhouse under the delivery policy.
sudo python3 tools/deploy.py apply --config /etc/ova-collection/cluster.json --output /var/tmp/ova-install \
  --wheelhouse /path/to/approved-wheelhouse
```

Pins ensure selected versions; the supplied requirements file does not include wheel hashes. The offline artifact must have its own approved hash manifest. No wheelhouse, environments or downloaded dependencies are added to Git.

## Browser and service access

The receipt names the loopback URL, token-file path and enabled units. Use an SSH tunnel and `/login`; retrieve the token through the approved secure channel. It is shared cluster-level access. Rotate it by replacing the root-owned credential and restarting the browser; signed sessions from the old token become invalid. Team deployments should use the provided SSO proxy fragment, TLS and reader-group authorization; set `browser_secure_cookie=true` when accessed through HTTPS.

Use the exact unit names in `deployment-plan.json`, such as `slurm-evidence-<cluster>-<epoch>-metadata.timer`. Confirm enabled, active and increasing health timestamps. Run the [job-1 acceptance gate](acceptance.md). A successful installer receipt remains `INSTALLED_REQUIRES_COMMISSIONING` until source and recovery checks pass.

## Upgrade, maintenance and rollback

Fresh deployment refuses to overwrite `app/` or `state/index.sqlite`. For an upgrade, verify a new source bundle in an isolated checkout, run fixtures, back up the checkpoint online and preserve payloads and configuration. Stop the watchdog timer first, then the other collection timers/services and browser. Install reviewed code/dependencies without changing cluster/epoch/root, validate a checkpoint copy and units, then re-enable collection. Reconcile retained sources and verify exports. Do not delete a lake to “reset” a failed service.

Rollback code/dependencies from the previous reviewed release while preserving state. Schema changes need an explicit migration/rollback plan. Restoring a checkpoint alone without its referenced raw and Parquet payloads is not disaster recovery. Record every installed revision and dependency-lock/configuration hash in the deployment receipt.
