/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */
/**
 * Knowledge entries for the Analytics & Benchmarks domain (Analytics, Reports).
 */
import type { HelpContent } from "../types";

export const analyticsContent: HelpContent[] = [
  {
    id: "analytics",
    kind: "view",
    title: "Analytics",
    domain: "Analytics & Benchmarks",
    routePath: "/analytics/overview",
    summary: "Rack-level and node-level analytics, plus the cluster and customer-schema reports.",
    description:
      "The Analytics page has two tabs. Rack Level aggregates rack and benchmark data into cluster-wide charts and tables — validation pass rates, NCCL/NEMO benchmark trends, and comparisons across racks. Node Level shows a heatmap with one square per node, coloured by a selectable data view (node up/down, test completion, or any bring-up benchmark that produces a metric such as NCCL busbw), with each node's up/down state always drawn as the square's border. The Compact layout tiles racks eight across as blocks of trays so a whole floor fits on one screen; Linear gives each rack its own row and shows a load gauge per node. The heatmap can be downloaded as a PNG or JPEG image. The Rack Level tab carries a report generator offering two reports: the rack status standard report (cluster details plus a row per node, as CSV, JSON, or a PDF with rack-level charts) and the test-result JSON schema report (the customer's Consolidated Test Plan contract, schema-validated before download).",
    features: [
      "Rack Level: cluster-wide aggregate charts, benchmark trends, cross-rack comparisons.",
      "Node Level: per-node heatmap grouped by rack, with a data-view selector.",
      "Compact layout tiles racks as blocks with a per-rack tally; Linear shows a gauge per node.",
      "Test completion view: all tests done, partial, or none run — independent of pass/fail.",
      "Up/down state shown as each cell's border on every view.",
      "Metric views scale against the fleet's observed range, stated in the legend.",
      "Download image: the heatmap as a report-ready PNG or JPEG with title, legend and timestamp.",
      "Report generator (Rack Level tab): the rack status report as CSV/JSON/PDF, or the test-result schema report as validated JSON. Both sweep every node for hardware and firmware identity, with a progress bar.",
    ],
    howTo: [
      { task: "Compare benchmark results across racks", steps: ["Open Analytics & Benchmarks > Analytics.", "Stay on the Rack Level tab.", "Select the metric/benchmark.", "Read the aggregate chart and rack comparison."] },
      { task: "Find slow or failed nodes across the cluster", steps: ["Open Analytics & Benchmarks > Analytics.", "Switch to the Node Level tab.", "Pick a benchmark in the data-view selector.", "Hover a square for that node's value and verdict; pale cells are failures or tests that never ran."] },
      { task: "See how far bring-up has got", steps: ["Open Analytics & Benchmarks > Analytics.", "Switch to the Node Level tab.", "Choose the Test completion view.", "Green racks are fully tested, red have not started, yellow are part-way; the per-rack tally counts each."] },
      { task: "Put the heatmap in a status email", steps: ["Open Analytics & Benchmarks > Analytics.", "Switch to the Node Level tab.", "Pick the view and layout you want to show.", "Choose PNG or JPEG and click Download image — the file carries the cluster name, legend and timestamp."] },
      { task: "Produce a report", steps: ["Open Analytics & Benchmarks > Analytics.", "Stay on the Rack Level tab and find Generate a report.", "Pick the report, then the format (CSV, JSON or PDF; the test-result schema report is JSON only).", "Click Generate & download and watch the per-node sweep progress."] },
    ],
    related: ["reports", "nodes", "parserResultsDialog", "dashboard"],
    keywords: ["analytics", "aggregate", "benchmark", "trends", "comparison", "charts", "heatmap", "node level", "report", "csv report", "pdf report", "json report", "test-result schema", "test completion", "download image", "png", "jpeg", "compact layout"],
    aria: { label: "Analytics page", description: "Rack-level and node-level analytics with downloadable cluster reports." },
    aiContext:
      "The Analytics page has a Rack Level tab (cluster-wide aggregate charts: validation pass rates, NCCL/NEMO trends, cross-rack comparisons) and a Node Level tab (per-node heatmap grouped by rack; the fill is a selectable view — node up/down, test completion, or a bring-up metric like NCCL busbw — and the border always shows up/down). Test completion counts a test as done once it has a verdict, pass or fail, so it answers 'has this node been tested' rather than 'did it pass'. Two layouts: Compact tiles racks eight across as tray blocks with a per-rack good/warn/bad tally (the whole floor on one screen), Linear gives each rack a row and each node a load gauge. Metric views auto-scale to the fleet's observed range. Download image renders the heatmap to a light-background PNG/JPEG with title, legend, cluster and timestamp baked in, drawn on a canvas so it does not depend on the UI theme. The Rack Level tab carries a report generator with two reports. The rack status standard report renders one dataset as CSV, JSON, or a PDF with an executive summary and rack-level charts. The test-result JSON schema report answers the customer's Consolidated Test Plan contract and is validated against the vendored schema before download, so it is JSON only; fields bring-up cannot measure are marked TBD for the operator to edit. Both reports share one fleet sweep of per-node hardware and firmware identity — asking twice while a sweep runs joins the running job rather than starting a second one — and report progress per node. PDF is only offered when the image can render it.",
  },
  {
    id: "postRunNodeReport",
    kind: "view",
    title: "Post Run Node Report",
    domain: "Analytics & Benchmarks",
    routePath: "/analytics/post-run-nodes",
    summary: "Floor-style node validation participation, failure trends, deep audits, and Slurm status.",
    description:
      "The Post Run Node Report is built from Greenlight validation activities joined to exact Slurm allocations. It counts every validation a node participated in, attributes failures only when evidence names that node, flags repeat failures across distinct runs, and preserves the snapshot after Slurm accounting ages out. Hardware and NVLink/network reports are available as persistent sections. Selecting a node shows Job IDs, categories, findings, current Slurm reason, and controls for immediate deep audits or an explicit operator mark/drain.",
    features: [
      "Punchcard-style floor view grouped by rack, with run and attributed-failure counts per node.",
      "Increasing, decreasing, flat, and new failure trends; a repeat flag requires at least three findings across three distinct runs.",
      "Node drill-down with every validation participation, Job ID, scheduler state, evidence category, and finding.",
      "Current Slurm state and reason shown beside validation history.",
      "Persistent Node hardware status and Node network status report sections.",
      "One-node hardware or NVLink/network deep audits can be launched from the investigation dialog.",
      "Operator findings can be recorded locally or explicitly attached to a Slurm drain after confirmation.",
    ],
    howTo: [
      { task: "Investigate a repeat offender", steps: ["Open Analytics & Benchmarks > Post Run Node Report.", "Look for a red flag or increasing trend arrow.", "Select the node.", "Review the Job IDs, attributed failures, and current Slurm comment.", "Launch the relevant hardware or NVLink/network audit and watch its report section refresh."] },
      { task: "Record and drain a confirmed node issue", steps: ["Open the node from the floor view.", "Choose an evidence category and enter the exact reason.", "Enable the Slurm drain option.", "Confirm the exact node; Greenlight records the finding and applies the generated Slurm reason."] },
    ],
    tips: ["A failed multi-node job is visible as participation but does not count against every tray. A node failure requires explicit evidence, a single-node job, or a structured audit/operator finding."],
    related: ["analytics", "reports", "nodes", "singleRack"],
    keywords: ["post run", "node history", "punchcard", "trend", "repeat failure", "slurm reason", "hardware audit", "network audit", "nvlink", "nccl", "job id"],
    aria: { label: "Post Run Node Report page", description: "Floor-style validation participation and evidence-attributed node failure history with deep audit reports." },
    aiContext:
      "This page is the first-class post-run node history, not a Google punchcard import. It joins durable validation activities to exact Slurm allocations, snapshots node membership, counts attributed failures only with node-specific evidence, flags repeat offenders across distinct runs, and shows current Slurm state/reason. It has persistent hardware and NVLink/network report sections. A selected node can launch either deep audit or receive an operator mark; draining requires an explicit confirmation.",
  },
  {
    id: "deploymentTracker",
    kind: "view",
    title: "Deployment Tracker",
    domain: "Analytics & Benchmarks",
    routePath: "/analytics/deployment-tracker",
    summary: "Bring-up progress per node, rolled up by rack, row and scalable unit, ready to publish as a static page.",
    description:
      "The Deployment Tracker folds everything Rack Status knows about the bring-up into one state per compute node — completed, in progress, in remediation, not started, or handed over — and lays it out on the floor: scalable unit, then row, then rack. A node is completed when its Stage 1 (single-node NCCL) and Stage 2 (single-node LLM training) have both passed; it is in remediation when a stage failed or Slurm holds it down or drained, so a node drained after passing is back on the list. A scalable unit with a handover date on the cluster record counts as handed over and leaves every validation step's denominator. The full-rack stages are shown as their own progress steps. Download static page exports the same view with today's data embedded, as one self-contained HTML file that opens from disk and that any static host (such as Linkify) can serve without reaching the cluster.",
    features: [
      "Headline tiles: total nodes, each state, and the share complete.",
      "Validation steps: node Stage 1 and Stage 2, then rack Stage 1 and Stage 2, with passed, running, failed and not-run counts.",
      "A card per scalable unit and per row with a stacked progress bar.",
      "A node heatmap, one tile per node grouped by rack, filterable by state, scalable unit and free-text search.",
      "An expandable table from scalable unit to row to rack.",
      "A self-contained static export of the same page for publishing.",
    ],
    howTo: [
      { task: "Publish the tracker", steps: ["Open Analytics & Benchmarks > Deployment Tracker.", "Choose Download static page.", "Upload deployment-tracker.html to the static host as a new deploy."] },
      { task: "Mark a scalable unit handed over", steps: ["Open Platform > Projects & Clusters and edit the cluster.", "In Scalable Unit translation, set the SU's Handed over date.", "Save; the tracker counts its nodes as handed over on the next refresh."] },
      { task: "Find the nodes that need attention", steps: ["In the node heatmap, choose In remediation.", "Hover a red tile to see the failed stage or the Slurm state."] },
    ],
    tips: ["The state definitions at the bottom of the page come from the backend classifier, so the published page always explains exactly what it counted."],
    related: ["postRunNodeReport", "analytics", "nodes", "singleRack", "projects"],
    keywords: ["deployment tracker", "bring-up", "progress", "rollout", "scalable unit", "su", "row", "heatmap", "handover", "linkify", "static export"],
    aria: { label: "Deployment Tracker page", description: "Bring-up progress per compute node, by scalable unit, row and rack." },
    aiContext:
      "This page shows bring-up progress. Each node's state comes from backend/deployment_tracker.py: handed over (its SU has handed_over_at on the cluster record) > in progress (a stage running) > remediation (a stage failed, or Slurm down/drained, or BCM down) > completed (node Stage 1 and Stage 2 both done) > in progress (one stage done) > not started. Rack stages are reported separately as steps. The data is GET /api/deployment-tracker; GET /api/deployment-tracker/site.html is the static page with the data embedded.",
  },
  {
    id: "clusterForecast",
    kind: "view",
    title: "Cluster Forecast",
    domain: "Analytics & Benchmarks",
    routePath: "/analytics/cluster-forecast",
    summary: "When validation finishes, per node, rack and scalable unit, from the measured repair pace.",
    description:
      "The Cluster Forecast projects when the validating scalable units finish. A node has passed when both node stages (single-node NCCL and single-node LLM training) passed, a rack when rack Stage 2 (full-rack NeMo) passed, and a scalable unit when all of its racks have. Rack Status records each unit's progress every hour, and the forecast compares today's open work with a sample from about a week earlier that covered the same nodes, which gives a measured repair pace. Two scenarios project from it: current pace keeps returning nodes at that daily rate, and slowing tail lets the backlog shrink by the same fraction each day, so the hardest nodes come back last. Milestones, a projection chart, a table per scalable unit with each unit's date under both scenarios, the open racks grouped by how many nodes they wait on, and the history of nodes and racks passed are shown. Units placed but not yet started have no date until their first node runs a stage; handed-over units are left out. Download static page exports the same view with today's data, as one self-contained HTML file for Linkify or mail.",
    features: [
      "Headline tiles: nodes, racks and SUs passed, nodes still open, repairs per day, and the finish date under each scenario.",
      "Milestones: first SU, half and 90% of racks, 95% and 99% of nodes, every node, and everything complete.",
      "A projection of nodes still to pass under both scenarios.",
      "A table per scalable unit with its completion date under each scenario, expandable to the open racks and how many nodes each is missing.",
      "History of nodes and racks passed since sampling began, with imported history drawn dashed.",
      "A self-contained static export of the same page for publishing.",
    ],
    howTo: [
      { task: "Publish the forecast", steps: ["Open Analytics & Benchmarks > Cluster Forecast.", "Choose Download static page.", "Upload cluster-forecast.html to the static host as a new deploy."] },
      { task: "Bring in history recorded before sampling began", steps: ["Write a CSV with sampled_at, nodes, nodes_passed, racks and racks_passed, one fleet-level row per sample.", "Run `python backend/cli.py import-progress <file>` on the Rack Status host (inside the container on a container deployment).", "Refresh the page; imported history is drawn dashed."] },
      { task: "Leave a handed-over unit out", steps: ["Open Platform > Projects & Clusters and edit the cluster.", "Set the unit's Handed over date in Scalable Unit translation.", "The forecast drops it from scope on the next refresh."] },
    ],
    tips: [
      "With less than a day of history, or none covering today's nodes, the page shows where things stand without dates rather than projecting from too little.",
      "Doubling the repair rate roughly halves every remaining interval; the dates move with the repairs, not with validation capacity.",
      "A cluster with no Bring-up home on its record has no Stage 2, so a node passes on Stage 1 alone; one with no SU map is forecast as one group of racks; a pool with no racks by its nodes alone.",
      "Only the active cluster is sampled. The bottom of the page shows the sampler's last check and why it skipped, if it did.",
    ],
    related: ["deploymentTracker", "postRunNodeReport", "analytics", "projects"],
    keywords: ["forecast", "cluster forecast", "projection", "eta", "completion date", "pace", "repair rate", "scalable unit", "su", "milestones", "linkify", "static export"],
    aria: { label: "Cluster Forecast page", description: "Projected completion of validation per node, rack and scalable unit." },
    aiContext:
      "This page is the cluster forecast from backend/cluster_forecast.py over the deployment tracker dataset. Node passed = node Stage 1 and Stage 2 done; rack passed = rack Stage 2 done; SU complete = every rack passed. A rack's missing nodes are those not passed or not up in the cluster manager. Progress samples are stored hourly per SU in results_history (table progress_samples) by a sampler in backend/api/cluster_forecast.py; imported fleet-level history uses unit '*' and source 'import'. Pace = the drop in nodes still open since the oldest sample 1-7 days old (RACK_FORECAST_WINDOW_DAYS) whose node scope is within 3% of today's. Current pace: rack with k missing closes at T*k/(k+1) + 1 day where T = open nodes / nodes per day. Slowing tail: each missing node returns with an exponential time whose mean comes from the measured shrinkage; a rack closes at the median of its last return + 1 day. Group kinds: su; racks (the tracker's racks-in-no-SU bucket, 'All racks' with no SU map, never counted as an SU); pool (no racks: node-only forecast, no rack milestones, no rack-run day). With no evidence.bringup_home on the cluster record there is no Stage 2 source and a node passes on Stage 1. Samples are filed under the snapshot's cluster identity; only the active cluster is observed; meta.sampling.last_check says why the sampler last skipped. Data: GET /api/cluster-forecast; GET /api/cluster-forecast/site.html is the static page with data embedded.",
  },
  {
    id: "handoverReports",
    kind: "view",
    title: "Handover Reports",
    domain: "Analytics & Benchmarks",
    routePath: "/analytics/handover-reports",
    summary: "Multi-rack NCCL and LLM runs with what each measured, and the handover report for the runs you choose.",
    description:
      "Handover Reports lists every multi-rack run NVIS Rack Status launched or adopted, newest first: when it ran, its scheduler job, whether it measured NCCL, LLM training or both, the racks and scalable units it covered, its GPU count, the all-reduce, all-to-all and all-gather bus bandwidth at a 2 GB message, the LLM model with its TFLOP/s per GPU and step time, and its outcome. A finished run's numbers are read once from its logs and kept with the run, so the first visit after an upgrade summarizes older runs in the background while the table fills in. View opens one run in full: headline tiles (including all-to-all as a share of its ceiling), the NCCL results per collective with one chart each for all-reduce, all-to-all and all-gather of bus bandwidth from 2 GB to 16 GB, a floor plan of every scalable unit the run touched, drawn whole as on the Racks floor view (racks in floor order, nodes in tray order, green for the nodes the run held and gray for the rest), a table of every node the run held with its rack, IP address and its own bring-up NCCL results, the LLM training figures with a chart of steps per second, the configuration, the per-collective NCCL settings, the environment the launch handed the job (secrets withheld) and the one the job stated, the NCCL test command each collective ran (the mpirun and nccl-tests line with its exported variables, so a customer can run the same test), and the launcher command. A node's bring-up results are read once, after the run finishes, and kept with the run; Collect node facts again reads them anew, for example after nodes were re-tested before the handover. Download report draws the handover report as a PDF on the NVIDIA letterhead with the project and cluster names; selecting several runs in the table gives one report over all of them. Every report downloaded is also kept on the Reports page.",
    features: [
      "Run table with NCCL bus bandwidth at 2 GB for all-reduce, all-to-all and all-gather, and LLM model, TFLOP/s per GPU and step time.",
      "Filter by scalable unit and search racks, jobs and models.",
      "Run detail with one bus bandwidth chart per collective from 2 GB to 16 GB, and a steps per second chart.",
      "Nodes table: hostname, rack, IP and each node's bring-up all-reduce and all-to-all bus bandwidth over NVLink and RoCE.",
      "Floor plan of the run's scalable units, whole: which racks and trays the run used (green) and which it did not (gray).",
      "All-to-all against its ceiling: the most all-to-all can reach on the run's racks, from the nodes' own measured NIC rate, and the share of it achieved.",
      "The NCCL test command itself (mpirun + nccl-tests with its exported variables), not only the launcher that ran it.",
      "The settings each run used: the launch environment and the settings the job printed, per collective.",
      "PDF handover report on the NVIDIA letterhead, for one run or several selected runs.",
    ],
    howTo: [
      { task: "Hand over a scalable unit", steps: ["Open Analytics & Benchmarks > Handover Reports.", "Choose the scalable unit in the filter.", "Tick the NCCL and LLM runs that validate it.", "Choose Report for N selected and send the PDF."] },
      { task: "Check what settings a run used", steps: ["Open Analytics & Benchmarks > Handover Reports.", "Choose View on the run.", "Read Configuration, Per-collective NCCL settings and the two Environment tables."] },
      { task: "Refresh the nodes table before a handover", steps: ["Open the run with View.", "Choose Collect node facts again above the Nodes table.", "Wait for the table to fill in; download the report after it does."] },
      { task: "Give a customer the command to rerun a test", steps: ["Open the run with View.", "Copy the collective's block under NCCL test commands.", "Write a hosts file with one '<node> slots=<GPUs per node>' line per node from the Nodes table, and run the block from one of them."] },
    ],
    tips: [
      "Bus bandwidth is quoted at a 2 GB message, the size acceptance criteria are stated at; hover a value for the peak.",
      "A cross-rack NeMo run sweeps NCCL as a preflight before it trains, inside its container and with the training job's NCCL settings: it shows as LLM + NCCL preflight, its NCCL figures are labelled as the preflight, and it is left out of NCCL comparisons and the all-to-all ceiling.",
      "Runs launched before NVIS Rack Status kept launch environments show only the settings the job printed in its log.",
      "Runs whose job did not yet print its exact NCCL command show it rebuilt from the job's settings and marked reconstructed; values the log did not keep read <not recorded>.",
      "Bring-up runs no per-node all-gather test, so the nodes table shows all-gather as a dash.",
      "All-to-all bus bandwidth falls as a run grows because more of every GPU's traffic leaves its rack; compare runs by their share of the ceiling, not their raw GB/s.",
    ],
    related: ["multirack", "reports", "analytics", "clusterForecast"],
    keywords: ["handover", "hand over", "acceptance", "multi-rack", "multirack", "nccl", "all-to-all", "alltoall", "busbw", "llm", "nemo", "tflops", "step time", "report", "pdf"],
    aria: { label: "Handover Reports page", description: "Multi-rack runs and their handover reports." },
    aiContext:
      "This page is backend/handover_report.py over the durable run registry (validation_activities, scope multirack) and the nvis_logscan record of each run's task logs. A finished run's summary (results_summary on its registry record, versioned by SUMMARY_VERSION) holds per-collective busbw_peak_gbps (the scanner's peak: largest size of the last completed test) and busbw_2g_gbps (best sweep at the row within 1% of 2 GiB), the LLM model/size/dtype/gbs from 'INFO: LLM params', step_time_s, tflops_per_gpu and mfu, and nodes/GPUs from the launcher header. A background backfill (one nvis_logscan batch) folds runs without a summary; running runs are never folded. Detail adds nccl_curves (series_by_collective), llm_steps (thinned to 500 points), settings.launch_env (the environment the launch resolved, recorded by validation_activities.record_activity with secrets redacted) and settings.stated (the launchers' own 'nccl_allreduce:' / 'nvis_fabric:' statements), nccl_commands (per collective: the 'nccl_allreduce: <coll>: command:' / 'env:' / 'LD_LIBRARY_PATH=' lines nccl_allreduce.sbatch prints, source stated; older logs are rebuilt from the stated settings, source reconstructed, unknown values empty), and the launcher command. floor_plan lists each scalable unit (cluster record) holding one of the run's racks, all of its racks naturally sorted, each with native_status.placed_rack_members in tray order and used = in the run; node_rows lists the run's nodes (registry nodes, else the launcher's --nodelist) with rack and IP from cluster-manager placement and, from node_facts on the registry record (collected once after the run finishes, in the background, with no probe of the nodes), the per-node bring-up results for allreduce, alltoall, allreduce-nonvlink and alltoall-nonvlink from report_benchmarks.sh; node_facts.state is ready, collecting, not_collected or none. alltoall_ceiling = B x (N-1)/(N-R): B = median bring-up alltoall-nonvlink busbw of the run's nodes, N = GPUs, R = GPUs in the run's smallest rack (gpus/nodes x nodes in that rack); pct_2g/pct_peak = achieved/ceiling; su_racks counts racks per SU; null without B or when R >= N. The PDF summary tables it across runs with the derivation; POST /api/handover-reports/runs/<activity_id>/node-facts (report.handover:generate) collects them again (409 while the run is still going). Data: GET /api/handover-reports/runs[?su=], GET /api/handover-reports/runs/<activity_id>, GET /api/handover-reports/report?ids=a,b[&format=json]; the PDF is handover_report_pdf.py and is also saved in report_store (kind handover). Actions: report.handover:list/read/generate.",
  },
  {
    id: "reports",
    kind: "view",
    title: "Reports",
    domain: "Analytics & Benchmarks",
    routePath: "/analytics/reports",
    summary: "Download saved cluster reports, plus bug report and NVLMapper archives.",
    description:
      "The Reports page holds two separate things. Generated reports are the cluster and customer-schema documents produced from Analytics > Rack Level; each is saved when it finishes, so you can start a report, leave the page, and download it here later — a fleet sweep takes minutes and is no longer lost by navigating away. Rows show the report type, format, when it was generated, the node count it covers, and any schema errors, and can be downloaded or deleted. Below that, the bug report section lists NVIDIA bug report archives, NVLMapper outputs and Excel exports already present in the reports directory on this dashboard host.",
    features: [
      "Generated rack status (CSV/JSON/PDF) and test-result schema (JSON) reports, saved automatically when they finish.",
      "Reports survive leaving the page and a container restart; the most recent are kept and older ones pruned.",
      "Schema errors are shown on the row, so a report that failed validation is visible without regenerating it.",
      "Separate listing of nvidia-bug-report archives, NVLMapper CSV/XLS and parser Excel exports from the reports directory.",
    ],
    howTo: [
      {
        task: "Get a report you generated earlier",
        steps: [
          "Open Analytics & Benchmarks > Reports.",
          "Find the row under Generated reports — newest first.",
          "Click Download.",
        ],
      },
      {
        task: "Generate a new report",
        steps: [
          "Go to Analytics & Benchmarks > Analytics, Rack Level tab.",
          "Use Generate a report, pick the report and format, and start it.",
          "You can leave the page; it appears here when the sweep finishes.",
        ],
      },
    ],
    related: ["analytics", "dashboard"],
    keywords: ["reports", "report", "export", "summary", "handoff", "validation", "benchmark", "saved reports", "pdf", "csv", "bug report", "nvlmapper", "download"],
    aria: { label: "Reports page", description: "Download saved cluster reports and node bug report archives." },
    aiContext:
      "Analytics > Reports lists (1) generated reports from report_store.py, served by GET /api/reports/generated with download and DELETE at /api/reports/generated/<id>, kept under var/reports on the rack-data volume so they survive restarts, and (2) bug report / NVLMapper files from the reports directory via /api/bug-report-inventory. Reports are archived by the node-report worker when it completes, not when downloaded, so closing the tab mid-sweep no longer loses the run. Generation itself happens on Analytics > Analytics, Rack Level tab.",
  },
];
