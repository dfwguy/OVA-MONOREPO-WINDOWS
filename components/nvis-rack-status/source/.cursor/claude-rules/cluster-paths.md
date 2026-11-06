---
description: Every fix and new feature — one root per cluster (connection.root); scripts, logs, workspace, bring-up and reports derive from it via cluster_paths and one resolver each, never a literal, a default or an instance env var; images are P2P exceptions; how to add a path and fix the next path bug
alwaysApply: true
---

# Cluster paths reach scripts from the project record — never from the script

Full reasoning, incident history and host-visibility map: `docs/explanation/how-cluster-paths-reach-scripts.md`.
Read it before touching any path, prefix, `*_DIR`, `LLMB_*`, workspace, log or container-image
location in `bin/scripts/` or the backend.

**This applies to every fix and every new feature, not only to path bugs.** A new script, tool,
installer, launcher, preset or setting that reads or writes anything on a cluster host takes its
location from the cluster record from day one. A "quick" literal to unblock a run is the bug this
rule exists to stop: it is how six incidents happened (2026-10, Nscale NC) and how four different
`/home` users came to coexist in one tree. If you are unsure which root a path belongs to, ask —
and check earlier sessions' transcripts for a decision already made — rather than guessing a path.

**The rule: one root per cluster.** A cluster declares ONE folder on its record, `connection.root`
(`/home/cmods` on Nscale NC), and every on-host path is that root plus a fixed suffix
(`backend/cluster_paths.py`, `LAYOUT`). Each path keeps its own record field as an **override** for a
site that genuinely keeps it elsewhere; a correctly shaped cluster needs only the root.
`catalog.context.high_overlay()` publishes the resolved paths as the `NVIS_*`/`RACK_*` variables the
backend and scripts read (they forward over SSH), and the high overlay beats the environment — so
once a cluster names a path, **no instance-wide environment variable can move it**. An environment
variable is one value for the whole instance; the record is per cluster, which is what multi-tenant
means. Each root is then turned into concrete paths by exactly ONE shell resolver.

| Path | Under the root | Override field | Env | Resolver |
|---|---|---|---|---|
| scripts | `nvis-rack-status` | `remote_base_path` | `RACK_REMOTE_BASE_PATH` | `script_tree.py`; scripts self-locate, batch scripts use `NVIS_SCRIPTS_DIR` |
| logs | `nvis/logs` | `log_dir` | `NVIS_LOG_DIR` / launch cwd / `RACK_JOB_LOG_DIR` | `${RACK_JOB_LOG_DIR:-${RACK_STATUS_LOG_DIR:-$PWD}}` |
| workspace | `workspace` | `workspace_dir` | `NVIS_WORKSPACE_DIR` | `bin/scripts/workspace-dir-common.sh`; `lib/llmb_paths.inc.sh` → `LLMB_INSTALL`=`<ws>/llmb` |
| bring-up tree | `bringup` | `evidence.bringup_home` | `RACK_BRINGUP_HOME` | `bringup.bringup_home()`; runs only where `evidence.bringup_enabled` says so |
| health-check markers | `bringup-data/logs` | `evidence.healthcheck_root` | — | `healthcheck_evidence.log_root()` (only with bring-up on) |
| reports | `bringup-data/reports` | `bug_report_dir` | `RACK_BUG_REPORT_REMOTE_DIR` | `paths._bug_report_remote_dir()`; NVLMapper and parser Excel derive from it |
| readable folders | the root | — | `RACK_STATUS_ALLOWED_PREFIXES` | `cluster_paths.allowed_prefixes()` |
| published settings | (follows scripts) | — | — | `bin/scripts/lib/node_config.inc.sh` → `<scripts>/config/` |

**Two exceptions, by nature.** Images are not under the root. The **node image cache**
(`node_container_dir` → `NVIS_NODE_CONTAINER_DIR`, `lib/node_images.inc.sh`) is each node's local
disk, and on a P2P cluster it is the **only** copy a job runs: launchers refuse `--storage nfs` and
`--rsync` there. The **image origin** (`shared_container_dir` → `RACK_VALIDATION_CONTAINER_ROOT`) is
P2P's own store on the app server, which no node reads; it has no default, and only a non-P2P
cluster's launch ever reads it.

**Where a cluster's paths stand is one screen:** Projects & Clusters → edit the active cluster →
"Where this cluster keeps its things" (`GET /api/cluster-paths`), with whether each folder exists and
is writable. A path that only the environment gives is labelled there as the thing to move onto the
record. Design and history: `docs/explanation/the-cluster-home-directory.md`.

## Not only paths: every setting an action uses

The same rule holds for every value a launch or action depends on, not just locations: if it can
differ between sites or change over time, it comes from the Project/Cluster record or the tool's
settings — and if no setting holds it yet, add one there, never a literal. Container images are the
worked example: which image a launch stages, its byte size and its SHA256 are the cluster's **image
catalog** entry whose `required_by` names the launch (`validation_presets.launch_image`, served to
scripts as `NVIS_LAUNCH_IMAGE*`, read by `lib/node_images.inc.sh:nvis_launch_image`). The presets once
hard-coded a digest that NC's catalog had already corrected, and every multi-rack preset launch failed
its stage gate on a healthy image (2026-10-14). CI guard:
`backend/tests/test_preset_image_from_catalog.py::test_no_launch_source_carries_an_image_digest`.

## Never

- a `/home/<user>/...` literal or a `/home/*/` glob in script code (CI guard:
  `backend/tests/test_cluster_workspace.py::test_no_script_carries_a_user_home`);
- `${X:-/some/site/path}` defaults repeated per script — derive in the root's resolver, once;
- a backend/script fallback to another site's directory (the old `/home/cmsupport/workspace`) —
  unset must be an error that names the setting ("Projects → cluster → Workspace");
- stat-ing a shared store from the launch host (NC's BCM head mounts only `/home`; `/cluster` is
  app-server-only; `/opt/containers` is node-local) — check node data on the nodes via `pdsh`;
- writing into a shipped layer (`multi-platform/`) except published `config/` files, or creating a
  script layer as a side effect;
- "fixing" it on the host (editing a deployed script, exporting in a shell) — fix the setting.

## Fixing a path bug — in order

1. Name the root. 2. If it exists, add the suffix to that root's resolver and source the resolver.
3. If none fits, add a path to the layout, not a root beside it: a `PathSpec` in
`cluster_paths.LAYOUT` (its suffix under the root, its override field on the record, the variables
it is published as) → the override field on `ClusterConnection`/`ClusterEvidence` (validated with
`valid_data_dir`) → its editor field in `ProjectsView.tsx` + `types/catalog.ts` (the placeholder
derives from `GET /api/cluster-paths/layout`, never a suffix retyped in TypeScript) → resolver lib →
the table above. A genuinely node-local or P2P-owned location is an exception, stated as one. 4. Fail loudly when unset. 5. Check every hop: overlay, SSH forwarding (prefix or
`env_extra`), Slurm `--export`, `NVIS_SCRIPTS_DIR` in batch scripts. 6. Check which host resolves
it. 7. Test the way it runs (`test_cluster_workspace.py`, `test_node_config.py`,
`test_cluster_container_dirs.py`) in the CI images via `bin/ci-local.sh`.
