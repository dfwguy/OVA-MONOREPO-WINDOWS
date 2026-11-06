---
diataxis: how-to
description: Read when racks or a scalable unit are handed over, to pick the multi-rack runs that validated them and download their report.
---

# How to write a rack handover report

Produce the document a handover is signed off on: the multi-rack NCCL and LLM runs that validated a
set of racks, what each measured, the settings each ran with, and the command that launched it, on
the NVIDIA letterhead with the project and cluster named.

## 1. Run the validation through NVIS Rack Status

The report can only state what NVIS Rack Status recorded, so launch the handover runs from it: from
**Compute › Multirack operations**, or with `nvrs run` against the same launchers. Every launch
registers in the run registry with the environment it handed its job (secrets withheld), and each
job's log states the NCCL and LLM settings it actually used. A run started by hand on the cluster
has neither.

Use the settings you intend to hand over with: set the cluster's NCCL variables (per span and per
collective) on the cluster record in **Platform › Projects & Clusters**, so the report shows them as
the cluster's standing tuning rather than a one-off.

## 2. Find the runs

1. Open **Analytics & Benchmarks › Handover Reports**.
2. Choose the scalable unit in the filter, or search for racks, a job id or a model.

Each row is one multi-rack run: when it ran, its scheduler job, whether it measured NCCL, LLM
training or both, the racks and scalable units it covered, the GPUs, the all-reduce, all-to-all and
all-gather bus bandwidth at a 2 GB message (hover for the peak), the LLM model with its TFLOP/s per
GPU and step time, and the outcome.

On the first visit after an upgrade, older finished runs are summarized from their logs in the
background; the banner counts the logs, and the rows fill in as it goes. A run still writing its
logs shows **running** and is summarized once it finishes.

## 3. Check a run

1. Choose **View** on the run.
2. Read the headline tiles, then the NCCL results with one chart each for all-reduce, all-to-all and
   all-gather (bus bandwidth from 2 GB to 16 GB), and the LLM training figures with the
   steps-per-second chart.
3. Check **Nodes**. Its floor plan draws every scalable unit the run touched in full, as the Racks
   floor view does: racks in floor order and nodes in tray order, green for the nodes the run held and
   gray for the rest, so the spare trays and the racks another run covered are plain. Below it is
   every node the run held, with its rack, IP address and its
   own bring-up all-reduce and all-to-all results over NVLink and RoCE. These are read once, after
   the run finishes; the table says so while they are being collected. Bring-up has no per-node
   all-gather test, so that column is a dash. If nodes were re-tested in bring-up since,
   choose **Collect node facts again** before downloading the report.
4. Check **All-to-all against its ceiling**. All-to-all slows as a run grows, because more of every
   GPU's traffic leaves its rack through the NIC, so compare runs by their share of the ceiling, not
   by raw GB/s. The ceiling is `B × (N − 1) / (N − R)`: N GPUs in the run, R in each rack, and B the
   bus bandwidth one GPU drives through its NIC, measured as the median of the nodes' own bring-up
   all-to-all with NVLink off. The racks-per-SU line shows how the run was spread across scalable
   units, which can change the share it reaches.
5. Check **Configuration**, **Per-collective NCCL settings** and the two **Environment** tables: what
   the launch handed the job, and what the job printed it ran with. They should agree.
6. **NCCL test commands** gives each collective's program itself: its exported variables and the
   `mpirun` line that runs the nccl-tests binary. A customer can rerun the test from it on any node
   of the run, with a hosts file of one `<node> slots=<GPUs per node>` line per node in the table.
   A run whose job predates printing its command shows it rebuilt from the job's settings, marked
   *reconstructed*, with `<not recorded>` where the log did not keep a value.

## 4. Download the report

- For one run, choose **Download report** on its page.
- For a handover over several runs (for example the 512-GPU and 1024-GPU NCCL runs and the LLM run
  on the same racks), tick them in the table and choose **Report for N selected**.

The PDF opens with the project, cluster, racks and scalable units and every run's headline numbers
side by side and a table of all-to-all against its ceiling with how the ceiling is derived, then
gives each run a section with its results, the three charts, its nodes, settings
and the NCCL test commands. A copy of
every report downloaded is kept on **Analytics & Benchmarks › Reports**.

## Related

- Data: `GET /api/handover-reports/runs`, `GET /api/handover-reports/runs/<activity_id>`,
  `GET /api/handover-reports/report?ids=<id>,<id>` (`&format=json` for the dataset),
  `POST /api/handover-reports/runs/<activity_id>/node-facts` to collect a run's node facts again.
- Permissions: `report.handover:list`, `report.handover:read` and `report.handover:generate`.
  A deployment installed before this page existed needs `python backend/cli.py reconcile-admin-policy`
  so administrators hold the new actions.
