---
diataxis: explanation
description: Why a cluster's on-host paths should derive from one root, the sprawl that happens when they don't, and the single-source-of-truth the app should expose.
---

# The cluster home directory

Rack Status runs commands, reads logs and stages build artefacts on a cluster's own hosts, so it
has to know *where* on those hosts things live. Today it learns each of those locations from a
**separate** setting, with its own default, and nothing ties them together or shows them in one
place. On a deployment where the defaults happen to be wrong, the result is a cluster whose files
are scattered across three different `/home` users — and a tool that silently looks in a fourth.

This page is the argument for a single **cluster home**: one configured root from which every other
on-host path derives, surfaced by the app as the one place an operator looks to answer "where does
this cluster keep its things?"

## The sprawl, concretely

These are the on-host paths the app resolves, each from an independent knob:

| What | Setting | Default | On NscaleTX-NC today |
|---|---|---|---|
| App scripts (launchers, sbatch) | `RACK_REMOTE_BASE_PATH` (+ the layered `scripts` role; see [how-a-script-path-is-chosen](how-a-script-path-is-chosen.md)) | `/home/cmsupport/nvis-rack-status` | `/home/rkoike/nvis-rack-status` |
| Job logs | cluster `connection.log_dir` → `NVIS_LOG_DIR` (legacy `RACK_STATUS_LOG_DIR`) | `$PWD` of the launch | `/home/cmods/nvis/logs` |
| Readable roots | `RACK_STATUS_ALLOWED_PREFIXES` | — | `/home/cmods/nvis/logs,/home/cmods/bringup-data` |
| Bug-report drop | `RACK_BUG_REPORT_REMOTE_DIR` | — | `/home/cmods/bringup-data/reports` |
| Build workspace (HPC-X, CUDA, host NCCL + nccl-tests) | `NVIS_WORKSPACE_DIR` / `RACK_WORKSPACE_DIR` | `/home/cmsupport/workspace` | **unset → `/home/cmsupport/workspace`** |
| Single-node bring-up scripts (external, owned by the bring-up team) | — (consumed, not owned) | — | `/home/cmods/bringup` |

Three different users — `rkoike`, `cmods`, `cmsupport` — and the one that matters most for the
host-NCCL validation, the workspace, is the one nobody ever set. It falls through to a hard-coded
`/home/cmsupport/workspace` that does not exist on this cluster. An operator installing the "CUDA
toolkit & NCCL" tool and then running the NCCL sweep has no way to see that the two are pointed at
different places until the sweep fails with `libnccl.so.2 not found`.

## Why this is the disease, not a typo

The scattered defaults are not individually wrong so much as *un-anchored*. Two symptoms give it
away:

- **The sweep wildcards the user.** `nccl_allreduce.sbatch` resolves its library with a glob —
  `/home/`**`*`**`/workspace/nccl-<ver>/...` — precisely because no setting ever told it which home
  the workspace lives in. A wildcard that stands in for a missing configuration is a path that was
  never made a first-class citizen. It happens to match any `/home/<user>/workspace`, which hides
  the problem right up until two tools disagree on the version, and then the error names a literal
  `*` and the reader cannot tell configuration from a bug.
- **A ghost default silently breaks a tool.** `NVIS_WORKSPACE_DIR` unset is not an error; it is a
  confident pointer at an empty directory. The install tool writes real artefacts to the *configured*
  workspace and the sweep reads from the *wildcard* one, and nothing reconciles the two.

Both are the same root cause: a cluster's on-host geography is spread across N independent knobs
with N independent defaults, and the app treats each as if it were unrelated to the others.

## The design: one root, derived paths, shown in the UI

A cluster declares **one** folder on its record — its **root**, `/home/cmods` on Nscale NC — and every
other on-host path is that root plus a fixed suffix (`backend/cluster_paths.py`, `LAYOUT`):

```
<root>/                             e.g. /home/cmods
├── nvis-rack-status/               Rack Status scripts       (RACK_REMOTE_BASE_PATH)
├── nvis/logs/                      job logs                  (NVIS_LOG_DIR)
├── workspace/                      toolchains + LLMB         (NVIS_WORKSPACE_DIR; LLMB = workspace/llmb)
├── bringup/                        bring-up framework        (RACK_BRINGUP_HOME; only if it runs here)
└── bringup-data/
    ├── logs/                       health-check markers      (only with bring-up on)
    └── reports/                    bug reports, NVLMapper, parser Excel (RACK_BUG_REPORT_REMOTE_DIR)
```

Three properties make this a consolidation rather than a rename:

1. **One source of truth.** The root is set once per cluster. Each derived path keeps its own field
   as an *override* for the rare cluster that needs one, but a correctly shaped cluster needs exactly
   one value, not six.
2. **No ghost defaults, no instance-wide values.** Nothing falls through to a stranger's directory:
   the literal defaults are gone, and an unset path refuses with the setting it needs. The resolved
   paths are published in the catalog's *high* overlay, which beats the environment, so once a
   cluster has a root no instance-wide environment variable can move its paths. That is what makes
   one instance safe to serve several clusters.
3. **Findable.** Projects & Clusters → edit the active cluster shows "Where this cluster keeps its
   things": the root, every path with where it came from (root, override, or — the thing to fix —
   the environment), and whether each folder exists and is writable on the execution host.

**Images are the stated exception.** The node image cache is each node's local disk, and on a P2P
cluster it is the only copy a job runs; the image origin is P2P's own store on the app server, which
no node reads. Both are P2P's settings, shown on the same screen beside the root.

**Whether bring-up runs is a fact apart from where it lives.** A root derives `<root>/bringup` for
every cluster, so the record carries a switch, *Runs the bring-up framework*: without it a cluster
has no Stage 2 source and a node passes on Stage 1, instead of waiting on verdicts nobody writes.

## Where this stands

Built on 2026-10-23. The cluster record has a root, every path in the layout derives from it, the
first-run wizard asks for the root and nothing else, and the scripts' and backend's last literal
defaults are gone (`test_cluster_workspace.py` scans every script, operator tool and backend value
for a `/home` path). A deployment not yet given a root keeps working from its environment, labelled
on the paths screen as the thing to move onto the record. Nscale NC moved onto `/home/cmods` the
same day: its scripts from `/home/rkoike/nvis-rack-status` to `/home/cmods/nvis-rack-status`.

## What this is not

It is not a demand that every cluster use `/home/cmods`, nor that the three existing users collapse
into one overnight. It is that the app should *model* a cluster home and derive from it, so a new
deployment is one decision instead of six, and an existing one — like NscaleTX-NC, which already
keeps logs and bring-up data under `/home/cmods` — can be pulled onto a single root deliberately
rather than discovering the sprawl one failed launch at a time. See
[how-a-script-path-is-chosen](how-a-script-path-is-chosen.md) for the script layer that already does
the derived-from-a-root thing well, and that this generalises.
