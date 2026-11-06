# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Handover reports: what a multi-rack run measured, in the form a rack handover is signed off on.

One dataset, several renderers (core-designs.mdc citizen 10): the Handover Reports page reads it as
JSON and ``handover_report_pdf`` draws it on the NVIDIA letterhead. Nothing here measures anything.
The run is the durable registry's record (``validation_activities``: racks, the command, the
environment the launch handed its job) and the numbers are the single-pass scanner's record of each
of its logs (``nvis_logscan`` via ``logscan_cache``): busbw per message size for every NCCL
collective, step time and TFLOP/s per training step, and the launchers' own statements of the
settings they ran with.

Two depths, because they cost different amounts:

* The **summary** of a run -- peak and 2 GB busbw per collective, the LLM's model, TFLOP/s/GPU and
  step time, nodes and GPUs -- is what the run table shows for every run. Scanning ~170 logs of up
  to hundreds of MB on every page load is not an option, so a finished run's summary is folded once
  and kept on its registry record (``results_summary``), by a background backfill that the list
  request starts. A run still going is never folded: its logs are still growing.
* The **detail** -- the per-size curves, the per-step series, the stated settings -- is read when a
  run is opened or a report is drawn, from the scanner's cache (path + mtime + size), so a second
  look costs nothing.
"""
from __future__ import annotations

import logging
import re
import shlex
import statistics
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import native_status
import validation_activities
from activity_hydration import record_job_times, refresh_activities_lazy
from logscan_cache import _logscan_batch, _logscan_record

_logger = logging.getLogger(__name__)

#: Bump when the summary's shape or derivation changes: every stored summary is then refolded.
SUMMARY_VERSION = 1

#: The message size the acceptance criteria are stated at (Meta's CSP table, "all at 2G").
CRITERION_BYTES = 2 * 1024**3

#: The collectives a handover reports, in the order they are shown. The scanner's peak map is keyed
#: by its short codes; its series by the full name.
COLLECTIVES = ("all_reduce", "alltoall", "all_gather", "reduce_scatter")
_SHORT = {"all_reduce": "ar", "alltoall": "aa", "all_gather": "ag", "reduce_scatter": "rs"}

#: Work phases after which a run's logs no longer change (validation_activities.WORK_PHASES).
_FINISHED_WORK = frozenset({"done", "failed"})
_FINISHED_PHASE = frozenset({"error", "timeout"})

#: Steps per series point the API hands the page: a 2010-step soak is drawn from 500 points.
MAX_SERIES_POINTS = 500

#: Bump when the node-facts snapshot's shape changes: a stored one is then collected again.
NODE_FACTS_VERSION = 1

#: The bring-up jobs whose metric is a node's own NCCL result, in the order a handover lists them:
#: the NVLink runs inside the node, then the same collectives forced onto the RoCE rails. Bring-up
#: runs no all-gather, which the page and the report say rather than leave blank.
BRINGUP_NCCL_JOBS = ("allreduce", "alltoall", "allreduce-nonvlink", "alltoall-nonvlink")

_NODELIST_ARG = re.compile(r"--nodelist\s+(\S+)")


def natural_key(text: str) -> list:
    """SU2 before SU10: names are compared number by number, not character by character."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(text))]


_ENV_ASSIGN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})=(\S+)")
_PER_COLLECTIVE = re.compile(r"\b([a-z_]+): its own NCCL settings:\s*(.*)$")
_NCCL_VERSION = re.compile(r"\bNCCL version=(\S+)")
_NCCL_HEADER = re.compile(r"\bnodes=(\d+)\s+np=(\d+)\s+gpus/node=(\d+)(?:\s+sizes=(\S+))?(?:\s+rounds=(\d+))?"
                          r"(?:\s+collectives=(.*))?$")
_FORWARDED = re.compile(r"forwarding extra env to all ranks:\s*(.*)$")
#: The job's own statement of each collective's program (nccl_allreduce.sbatch, since the handover
#: reports): the command, the values it forwards by name, and the library path it runs with.
_COLL_COMMAND = re.compile(r"\b([a-z_]+): command:\s*(mpirun\b.*)$")
_COLL_ENV = re.compile(r"\b([a-z_]+): env:\s*(.*)$")
_COLL_LD = re.compile(r"\b([a-z_]+): LD_LIBRARY_PATH=(.*)$")
_BIN = re.compile(r"\bbin=(\S+)\s+per-collective timeout=(\d+)s")
_RSH_AGENT = re.compile(r"orted launch agent:\s*(.*)$")
_GPN = re.compile(r"\bgpus/node=(\d+)")
_NP = re.compile(r"\bnp=(\d+)")
_MODEL_ARGS = re.compile(r"INFO: model_args=\[(.*?)\]\s*extra_args=\[(.*?)\]")


# --- the run's logs ------------------------------------------------------------------------------


def task_logs(rec: dict[str, Any]) -> list[str]:
    """Every log a run's tasks resolved, most specific first per task, deduplicated.

    A task can name three: the aggregated results log, the training log and the job's stdout.
    The first one present is that task's evidence -- the others are the same run seen coarser.
    """
    out: list[str] = []
    for task in rec.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        for key in ("results_log_path", "training_log_path", "stdout_path"):
            path = str(task.get(key) or "").strip()
            if path:
                if path not in out:
                    out.append(path)
                break
    return out


def is_finished(rec: dict[str, Any]) -> bool:
    """Has the run stopped writing its logs? Only then is its summary worth keeping."""
    if rec.get("dry_run"):
        return False
    work = str(rec.get("work_phase") or "").strip().lower()
    if work in _FINISHED_WORK:
        return True
    return str(rec.get("phase") or "").strip().lower() in _FINISHED_PHASE


# --- one log ---------------------------------------------------------------------------------------


def _size_at(series: list[dict[str, Any]], size: int) -> float | None:
    """busbw at the row nearest *size*, if one is within 1%.

    Not an exact match: nccl-tests rounds a collective's message down to a multiple of what each
    rank sends, so on 144 ranks the all-to-all "2 GB" row is 2,147,483,520 bytes, not 2^31.
    """
    best: tuple[float, float] | None = None
    for point in series:
        n = int(point.get("size_bytes") or 0)
        if n <= 0:
            continue
        off = abs(n - size) / size
        if off <= 0.01 and (best is None or off < best[0]):
            best = (off, float(point.get("bus_bw_gbps") or 0.0))
    return best[1] if best else None


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def summarize_scan(scan: dict[str, Any]) -> dict[str, Any]:
    """The compact summary of one log's scanner record: what the run table shows.

    ``busbw_peak_gbps`` is the scanner's own peak (the largest message size of the last completed
    test, the definition every other Rack Status view uses); ``busbw_2g_gbps`` reads the best sweep
    at 2 GB, the size the acceptance criteria are stated at.
    """
    nccl = scan.get("nccl") or {}
    peaks = nccl.get("peak_busbw_gbps") or {}
    series = nccl.get("series_by_collective") or {}
    collectives: dict[str, dict[str, Any]] = {}
    for name in COLLECTIVES:
        rows = series.get(name) or []
        peak = peaks.get(_SHORT[name])
        if peak is None and not rows:
            continue
        collectives[name] = {
            "busbw_peak_gbps": peak,
            "busbw_2g_gbps": _size_at(rows, CRITERION_BYTES),
            "max_size_bytes": max((int(p.get("size_bytes") or 0) for p in rows), default=None),
        }
    nemo = scan.get("nemo") or {}
    geom = scan.get("geometry") or {}
    params = scan.get("llm_params") or {}
    llm: dict[str, Any] | None = None
    if nemo.get("samples"):
        llm = {
            "model": params.get("model") or "",
            "model_size": params.get("size") or "",
            "dtype": params.get("dtype") or "",
            "global_batch": _int(params.get("gbs") or geom.get("global_batch")),
            "step_time_s": nemo.get("step_time_s"),
            "tflops_per_gpu": nemo.get("tflops_per_gpu"),
            "mfu_percent": nemo.get("mfu_percent"),
            "steps": nemo.get("samples"),
            "declared_steps": nemo.get("declared_max_steps"),
            "finished": bool(nemo.get("finished")),
        }
    nodes = _int(geom.get("nccl_nodes")) or _int(geom.get("slurm_nnodes"))
    gpus = _int(geom.get("nccl_np")) or _int(geom.get("num_gpus"))
    gpn = _int(geom.get("gpus_per_node"))
    if nodes is None and gpus and gpn:
        nodes = gpus // gpn
    return {"collectives": collectives, "llm": llm, "nodes": nodes, "gpus": gpus}


def _merge(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """One run's summary from its logs': the first log to report a value supplies it."""
    out: dict[str, Any] = {"collectives": {}, "llm": None, "nodes": None, "gpus": None}
    for s in summaries:
        for name, vals in (s.get("collectives") or {}).items():
            out["collectives"].setdefault(name, vals)
        if out["llm"] is None and s.get("llm"):
            out["llm"] = s["llm"]
        for key in ("nodes", "gpus"):
            if out[key] is None and s.get(key):
                out[key] = s[key]
    return out


def run_type(summary: dict[str, Any] | None) -> str:
    """``nccl``, ``llm``, ``both`` or ``none``, from what the logs contain -- not from the tool.

    A cross-rack NeMo job sweeps NCCL before it trains, so its tool name alone would understate it.
    """
    if not summary:
        return "none"
    has_nccl = bool(summary.get("collectives"))
    has_llm = bool(summary.get("llm"))
    if has_nccl and has_llm:
        return "both"
    return "nccl" if has_nccl else ("llm" if has_llm else "none")


# --- the stated configuration ---------------------------------------------------------------------


def stated_settings(statements: list[str]) -> dict[str, Any]:
    """What the launchers SAID they ran with, structured: the run's settings as the log has them.

    The launch environment on the registry record is the request's side; these are the job's.
    For a run launched before the registry kept environments, they are the only record there is.
    """
    out: dict[str, Any] = {
        "env": {},
        "per_collective": {},
        "forwarded": [],
        "nccl_version": "",
        "sizes": "",
        "rounds": None,
        "collectives": [],
        "model_args": "",
        "extra_args": "",
        "commands": {},
        "collective_env": {},
        "ld_library_path": "",
        "bin": "",
        "test_timeout": None,
        "rsh_agent": "",
        "np": None,
        "gpus_per_node": None,
    }
    for line in statements or []:
        m = _COLL_COMMAND.search(line)
        if m:
            out["commands"][m.group(1)] = m.group(2).strip()
            continue
        m = _COLL_ENV.search(line)
        if m:
            out["collective_env"][m.group(1)] = dict(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=(\S*)", m.group(2)))
            continue
        m = _COLL_LD.search(line)
        if m:
            out["ld_library_path"] = m.group(2).strip()
            continue
        m = _BIN.search(line)
        if m:
            out["bin"], out["test_timeout"] = m.group(1), _int(m.group(2))
            continue
        m = _RSH_AGENT.search(line)
        if m:
            out["rsh_agent"] = m.group(1).strip()
            continue
        m = _PER_COLLECTIVE.search(line)
        if m:
            out["per_collective"][m.group(1)] = dict(_ENV_ASSIGN.findall(m.group(2)))
            continue
        m = _FORWARDED.search(line)
        if m:
            out["forwarded"] = m.group(1).split()
            continue
        m = _MODEL_ARGS.search(line)
        if m:
            out["model_args"], out["extra_args"] = m.group(1).strip(), m.group(2).strip()
            continue
        m = _NCCL_VERSION.search(line)
        if m:
            out["nccl_version"] = m.group(1)
        m = _NCCL_HEADER.search(line)
        if m:
            out["np"], out["gpus_per_node"] = _int(m.group(2)), _int(m.group(3))
            out["sizes"] = m.group(4) or ""
            out["rounds"] = _int(m.group(5))
            out["collectives"] = (m.group(6) or "").split()
            continue
        if "LLM params" in line:
            continue
        for key, value in _ENV_ASSIGN.findall(line):
            out["env"].setdefault(key, value)
    return out


def _quote(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]*", value) and value else shlex.quote(value)


def nccl_commands(stated: dict[str, Any], launch_env: dict[str, str]) -> list[dict[str, Any]]:
    """Each collective's NCCL program as someone outside NVIS Rack Status would run it.

    ``source`` says how much to trust it. ``stated``: the job printed its exact ``mpirun`` line and
    the values it forwarded (runs since the handover reports). ``reconstructed``: an earlier job
    printed only its parts -- scale, binary, sizes, timeout, interfaces, forwarded names and each
    collective's own settings -- and the command is rebuilt from them the way
    ``nccl_allreduce.sbatch`` assembles it; a forwarded value the record does not hold is left as
    the variable's name for the reader to set.
    """
    collectives = list(dict.fromkeys([*stated.get("collectives", []), *stated.get("commands", {})]))
    out: list[dict[str, Any]] = []
    for coll in collectives:
        per = dict((stated.get("per_collective") or {}).get(coll) or {})
        exact = (stated.get("commands") or {}).get(coll)
        if exact:
            env = dict((stated.get("collective_env") or {}).get(coll) or {})
            out.append({"collective": coll, "source": "stated", "env": env,
                        "ld_library_path": stated.get("ld_library_path") or "", "command": exact})
            continue
        if not (stated.get("bin") and stated.get("np") and stated.get("gpus_per_node")):
            continue
        env_known = {**(stated.get("env") or {}), **{k: v for k, v in launch_env.items() if not k.startswith("NVIS_")}}
        size_min, _, size_max = str(stated.get("sizes") or "8..16G").partition("..")
        ns_if = env_known.get("NCCL_SOCKET_IFNAME", "")
        forwarded = [k for k in stated.get("forwarded") or [] if k not in ("NCCL_SOCKET_IFNAME", "NCCL_IB_HCA", "NCCL_DEBUG")]
        binary = stated["bin"] if coll == "all_reduce" else f"{stated['bin'].rsplit('/', 1)[0]}/{coll}_perf"
        parts = [
            "mpirun", "-np", str(stated["np"]), "--hostfile", "hosts",
            "--map-by", f"ppr:{stated['gpus_per_node']}:node", "--bind-to", "none",
            "--mca", "plm", "rsh", "--mca", "plm_rsh_agent", _quote(stated.get("rsh_agent") or "ssh"),
            "--mca", "pml", "ob1", "--mca", "btl", "tcp,self", "--mca", "btl_tcp_if_include", ns_if,
            "--mca", "oob_tcp_if_include", ns_if,
            "-x", "LD_LIBRARY_PATH", "-x", "PATH", "-x", f"NCCL_SOCKET_IFNAME={ns_if}",
        ]
        if env_known.get("NCCL_IB_HCA"):
            parts += ["-x", f"NCCL_IB_HCA={env_known['NCCL_IB_HCA']}"]
        parts += ["-x", "NCCL_DEBUG=WARN"]
        for k in [*forwarded, *(k for k in per if k not in forwarded)]:
            parts += ["-x", k]
        parts += [binary, "-b", size_min or "8", "-e", size_max or "16G", "-f", "2", "-g", "1",
                  "-T", str(stated.get("test_timeout") or 120)]
        env = {k: env_known.get(k, "") for k in forwarded}
        env.update(per)
        out.append({"collective": coll, "source": "reconstructed", "env": env,
                    "ld_library_path": "", "command": " ".join(parts)})
    return out


def _launch_command(rec: dict[str, Any]) -> dict[str, Any]:
    """The command an operator would rerun, and the scheduler submission it became."""
    submitted = [
        line.split("exec:", 1)[1].strip()
        for line in str(rec.get("stdout_tail") or "").splitlines()
        if "exec:" in line and ("sbatch" in line or "srun" in line or "mpirun" in line)
    ]
    return {"launcher": str(rec.get("command_display") or ""), "submitted": submitted[:4]}


# --- context ---------------------------------------------------------------------------------------


def site_context() -> dict[str, Any]:
    """Project, cluster and platform names, and each rack's scalable unit where the site states it."""
    try:
        from catalog import context as catalog_context

        project, cluster, platform = catalog_context.resolve()
    except Exception:  # a label; the dataset is complete without it
        _logger.warning("handover report: active cluster unavailable", exc_info=True)
        return {"project": "", "cluster": "", "platform": "", "gpu_model": "", "rack_su": {}, "units": []}
    rack_su: dict[str, str] = {}
    units: list[dict[str, Any]] = []
    for su in (cluster.scalable_units if cluster is not None else []) or []:
        units.append({"id": su.id, "label": su.label or su.id, "racks": [str(r) for r in su.racks]})
        for rack in su.racks:
            rack_su[str(rack)] = su.label or su.id
    return {
        "project": project.name if project is not None else "",
        "cluster": cluster.name if cluster is not None else "",
        "platform": platform.name if platform is not None else "",
        "gpu_model": platform.gpu_model if platform is not None else "",
        "rack_su": rack_su,
        "units": units,
    }


#: Context keys that are lookups for building the dataset, not facts about the site to print.
_CONTEXT_ONLY = ("rack_su", "units")


# --- the run table ---------------------------------------------------------------------------------


def _row(rec: dict[str, Any], rack_su: dict[str, str]) -> dict[str, Any]:
    stored = rec.get("results_summary")
    summary = stored if isinstance(stored, dict) and stored.get("version") == SUMMARY_VERSION else None
    racks = [str(r) for r in rec.get("racks") or []]
    tasks = [t for t in rec.get("tasks") or [] if isinstance(t, dict)]
    if summary is not None:
        state = "ready" if summary.get("logs") else "no_logs"
    elif not is_finished(rec):
        state = "running"
    else:
        state = "pending"
    return {
        "activity_id": str(rec.get("activity_id") or ""),
        "created_at": rec.get("created_at"),
        "finished_at": rec.get("finished_at"),
        # The scheduler job's own start and end; finished_at is when the launcher returned.
        "job_started_at": min((t["started_at"] for t in tasks if t.get("started_at")), default=None),
        "job_ended_at": max((t["ended_at"] for t in tasks if t.get("ended_at")), default=None),
        "tool": rec.get("tool"),
        "stage": rec.get("stage"),
        "operator": rec.get("operator") or "",
        "racks": racks,
        "scalable_units": sorted({rack_su[r] for r in racks if r in rack_su}, key=natural_key),
        "scheduler_job_ids": validation_activities.scheduler_refs(rec),
        "outcome": validation_activities.ledger_outcome(rec),
        "summary_state": state,
        "run_type": run_type(summary),
        "nodes": (summary or {}).get("nodes"),
        "gpus": (summary or {}).get("gpus"),
        "collectives": (summary or {}).get("collectives") or {},
        "llm": (summary or {}).get("llm"),
    }


def list_runs(*, rack: str | None = None, scalable_unit: str | None = None, limit: int = 500) -> dict[str, Any]:
    """The multi-rack runs a handover can be drawn from, newest first, with their summaries.

    Starts the backfill for finished runs that have none yet and says how far it has got, so the
    page can show the rows at once and fill the numbers in as they arrive.
    """
    ctx = site_context()
    records = validation_activities.list_activities(scope="multirack", rack=rack or None, limit=limit)
    # A run that just ended has no log path or final phase until the registry is hydrated, which it
    # is on read: without this its numbers waited for someone to open the multi-rack page.
    if refresh_activities_lazy([r for r in records if not is_finished(r) or not task_logs(r)]):
        records = validation_activities.list_activities(scope="multirack", rack=rack or None, limit=limit)
    rows = [_row(rec, ctx["rack_su"]) for rec in records]
    if scalable_unit:
        rows = [r for r in rows if scalable_unit in r["scalable_units"]]
    if any(r["summary_state"] == "pending" for r in rows):
        ensure_backfill()
    return {
        "site": {k: v for k, v in ctx.items() if k not in _CONTEXT_ONLY},
        "scalable_units": sorted(set(ctx["rack_su"].values()), key=natural_key),
        "runs": rows,
        "backfill": backfill_status(),
    }


# --- the backfill ----------------------------------------------------------------------------------

_backfill_lock = threading.Lock()
_backfill_state: dict[str, Any] = {"running": False, "done": 0, "total": 0, "error": ""}


def backfill_status() -> dict[str, Any]:
    with _backfill_lock:
        return dict(_backfill_state)


def summarize(rec: dict[str, Any], scans: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fold one finished run's scanner records into the summary its registry record keeps."""
    logs = [p for p in task_logs(rec) if isinstance(scans.get(p), dict) and scans[p].get("ok")]
    merged = _merge([summarize_scan(scans[p]) for p in logs])
    return {
        "version": SUMMARY_VERSION,
        "summarized_at": datetime.now(timezone.utc).isoformat(),
        "logs": logs,
        **merged,
    }


def _needs_summary(rec: dict[str, Any]) -> bool:
    stored = rec.get("results_summary")
    if isinstance(stored, dict) and stored.get("version") == SUMMARY_VERSION:
        return False
    return is_finished(rec)


def run_backfill() -> int:
    """Summarize every finished multi-rack run that has no current summary. Returns runs folded.

    One scanner process for all of their logs (``_logscan_batch``): the analytics aggregate
    measured a whole 1020-log directory at 40 s that way, against a process per file.
    """
    records = [
        rec
        for rec in validation_activities.list_activities(scope="multirack", limit=0)
        if _needs_summary(rec)
    ]
    paths = sorted({p for rec in records for p in task_logs(rec)})

    def _progress(done: int, total: int, _path: str) -> None:
        with _backfill_lock:
            _backfill_state.update(done=done, total=total)

    scans = _logscan_batch(paths, on_progress=_progress) if paths else {}
    folded = 0
    for rec in records:
        logs = task_logs(rec)
        if logs and not all(p in scans for p in logs):
            continue  # the scanner never answered for this run: leave it pending, try again later
        validation_activities.update_activity(
            str(rec.get("activity_id") or ""), results_summary=summarize(rec, scans)
        )
        folded += 1
    return folded


def _backfill_worker() -> None:
    try:
        n = run_backfill()
        _logger.info("handover report: summarized %d multi-rack run(s)", n)
        error = ""
    except Exception as exc:  # a failed pass leaves the runs pending; the next list retries
        _logger.exception("handover report backfill failed")
        error = str(exc)
    with _backfill_lock:
        _backfill_state.update(running=False, error=error)


def ensure_backfill() -> bool:
    """Start the backfill unless one is running. Returns whether this call started it."""
    with _backfill_lock:
        if _backfill_state["running"]:
            return False
        _backfill_state.update(running=True, done=0, total=0, error="")
    threading.Thread(target=_backfill_worker, name="handover-backfill", daemon=True).start()
    return True


# --- one run, in full ------------------------------------------------------------------------------


def _thin(values: list[float], limit: int = MAX_SERIES_POINTS) -> list[dict[str, float]]:
    """``[{step, step_time_s, steps_per_s}]``, evenly thinned to at most *limit* points."""
    stride = max(1, -(-len(values) // limit))
    return [
        {
            "step": i + 1,
            "step_time_s": v,
            "steps_per_s": round(1.0 / v, 5) if v else 0.0,
        }
        for i, v in enumerate(values)
        if i % stride == 0 or i == len(values) - 1
    ]


# --- the nodes a run covered ------------------------------------------------------------------------


def run_nodes(rec: dict[str, Any]) -> list[str]:
    """The exact hosts a run covered: its registry roster, else the ``--nodelist`` it launched with.

    Launches record their roster since the handover reports; older runs still carry it in the
    command they were started with (every multi-rack launcher passes an explicit node list).
    """
    nodes = [str(n) for n in rec.get("nodes") or [] if str(n).strip()]
    if nodes:
        return nodes
    m = _NODELIST_ARG.search(str(rec.get("command_display") or ""))
    if not m:
        return []
    return [h for h in m.group(1).strip("'\"").split(",") if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", h)]


def _bringup_metrics(hosts: list[str]) -> tuple[dict[str, dict[str, str]], str]:
    """Each host's bring-up NCCL results from the framework's own report, and an error if it failed.

    The report's cell is the metric (busbw GB/s) when the job produced one, else its status word
    (NOT_RUN, FAIL, ...), kept as it is so a missing number says why it is missing.
    """
    try:
        import bringup

        if not bringup.is_enabled():
            return {}, "this cluster runs no bring-up framework"
        columns, rows = bringup.parse_daily_report_csv(bringup.run_daily_report())
    except Exception as exc:  # a bring-up outage costs these columns, not the report
        _logger.warning("handover report: bring-up results unavailable", exc_info=True)
        return {}, str(exc)
    by_base: dict[str, str] = {}
    for col in columns:
        by_base.setdefault(bringup._base_job(col), col)
    lowered = {k.casefold(): v for k, v in rows.items()}
    out: dict[str, dict[str, str]] = {}
    for host in hosts:
        row = rows.get(host) or lowered.get(host.casefold()) or {}
        cells = row.get("cells") if isinstance(row.get("cells"), dict) else {}
        # A host bring-up has no row for was never tested: no cells, rather than a row of blanks.
        out[host] = {job: str(cells.get(by_base[job], "")) for job in BRINGUP_NCCL_JOBS if job in by_base} if row else {}
    return out, ""


def collect_node_facts(activity_id: str) -> dict[str, Any] | None:
    """Gather each node's bring-up NCCL results for a run, and keep them with it.

    A snapshot taken when the handover is drawn up: bring-up keeps testing, and the document should
    go on saying what the nodes measured when they were handed over. Read from the bring-up
    framework's own report -- data already on the cluster, no probe of the nodes.
    """
    rec = validation_activities.get_activity(activity_id)
    if rec is None:
        return None
    hosts = run_nodes(rec)
    bringup, bringup_error = _bringup_metrics(hosts)
    facts = {
        "version": NODE_FACTS_VERSION,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "nodes": {h: {"bringup": bringup.get(h, {})} for h in hosts},
        "bringup_error": bringup_error,
    }
    validation_activities.update_activity(activity_id, node_facts=facts)
    return facts


_facts_lock = threading.Lock()
_facts_running: set[str] = set()


def _facts_worker(activity_id: str) -> None:
    try:
        collect_node_facts(activity_id)
    except Exception:  # the page shows the nodes without the facts and offers the collection again
        _logger.exception("handover report: node facts collection failed for %s", activity_id)
    finally:
        with _facts_lock:
            _facts_running.discard(activity_id)


def ensure_node_facts(activity_id: str) -> bool:
    """Start collecting a run's node facts unless that is already under way. Returns whether it started."""
    with _facts_lock:
        if activity_id in _facts_running:
            return False
        _facts_running.add(activity_id)
    threading.Thread(target=_facts_worker, args=(activity_id,), name="handover-node-facts", daemon=True).start()
    return True


def recollect_node_facts(activity_id: str) -> str | None:
    """Gather a finished run's node facts again, replacing what it kept; the state that leaves.

    Facts are a snapshot by design, but a handover can be drawn up days after the run: a node is
    re-tested in bring-up, or the bring-up report was unavailable the first time. ``None`` when there is no such multi-rack run; ``"running"`` while the run is still
    going, when there is nothing final to snapshot yet.
    """
    rec = validation_activities.get_activity(activity_id)
    if rec is None or str(rec.get("scope") or "") != "multirack":
        return None
    if not is_finished(rec):
        return "running"
    if not run_nodes(rec):
        return "none"
    ensure_node_facts(activity_id)
    return "collecting"


def _node_rows(rec: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """The run's nodes with what is known of each, and the state of the per-node facts."""
    hosts = run_nodes(rec)
    placed = native_status.placed_node_facts(hosts) or {}
    stored = rec.get("node_facts")
    facts = stored if isinstance(stored, dict) and stored.get("version") == NODE_FACTS_VERSION else None
    with _facts_lock:
        running = str(rec.get("activity_id") or "") in _facts_running
    state = "collecting" if running else ("ready" if facts else ("none" if not hosts else "not_collected"))
    rows = []
    for host in sorted(hosts, key=lambda h: (natural_key((placed.get(h) or {}).get("rack") or "~"), natural_key(h))):
        node = ((facts or {}).get("nodes") or {}).get(host) or {}
        rows.append({
            "host": host,
            "rack": (placed.get(host) or {}).get("rack") or "",
            "ip": (placed.get(host) or {}).get("ip") or "",
            "bringup": node.get("bringup") or {},
        })
    return rows, state


#: The bring-up job that measures one node's all-to-all with NVLink off: every byte over its NICs.
#: Its bus bandwidth is the rate one GPU can push through the fabric, the input to the ceiling.
NIC_A2A_JOB = "alltoall-nonvlink"


def _gbps_value(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def alltoall_ceiling(run: dict[str, Any], node_rows: list[dict[str, Any]],
                     rack_su: dict[str, str]) -> dict[str, Any] | None:
    """The bus bandwidth all-to-all could reach on this run's racks, and how close it came.

    In all-to-all every GPU sends ``1/N`` of its buffer to every rank. The share bound for its
    own rack travels over NVLink, an order of magnitude faster; the rest -- ``(N - R) / N`` for
    ``R`` GPUs in the rack -- leaves through the GPU's NIC, and that sets the time. With ``B``
    the bus bandwidth one GPU drives through its NIC::

        ceiling = B * (N - 1) / (N - R)

    ``B`` is measured, not a datasheet figure: the median of the nodes' own bring-up all-to-all
    with NVLink off (every byte over the NICs). The smallest rack bounds ``R``, since its GPUs send
    the largest share off-rack and finish last. ``None`` without that measurement, or when the run
    never leaves a rack.
    """
    a2a = (run.get("collectives") or {}).get("alltoall") or {}
    n_gpus, n_nodes = int(run.get("gpus") or 0), int(run.get("nodes") or 0)
    # Only a dedicated NCCL test is held to the ceiling. An LLM job's sweep is its preflight, run
    # inside the training container with the training job's NCCL settings, not the tuned test's.
    if run.get("run_type") != "nccl" or not a2a or not n_gpus or not n_nodes:
        return None
    rates = sorted((v, r["host"]) for r in node_rows
                   if (v := _gbps_value((r.get("bringup") or {}).get(NIC_A2A_JOB))) is not None)
    per_rack = Counter(r["rack"] for r in node_rows if r.get("rack"))
    if not rates or not per_rack:
        return None
    rack_gpus = n_gpus // n_nodes * min(per_rack.values())
    if not 0 < rack_gpus < n_gpus:
        return None
    nic = statistics.median(v for v, _ in rates)
    ceiling = nic * (n_gpus - 1) / (n_gpus - rack_gpus)

    def pct(value: Any) -> float | None:
        v = _gbps_value(value)
        return round(100 * v / ceiling, 1) if v is not None else None

    su_racks = Counter(rack_su.get(r) or "" for r in per_rack)
    return {
        "nic_gbps": round(nic, 2),
        "nic_min_gbps": round(rates[0][0], 2),
        "nic_min_host": rates[0][1],
        "nic_nodes": len(rates),
        "gpus_per_rack": rack_gpus,
        "ceiling_gbps": round(ceiling, 1),
        "busbw_2g_gbps": a2a.get("busbw_2g_gbps"),
        "pct_2g": pct(a2a.get("busbw_2g_gbps")),
        "busbw_peak_gbps": a2a.get("busbw_peak_gbps"),
        "pct_peak": pct(a2a.get("busbw_peak_gbps")),
        "max_size_bytes": a2a.get("max_size_bytes"),
        "su_racks": {su: n for su, n in sorted(su_racks.items(), key=lambda kv: natural_key(kv[0])) if su},
    }


def floor_plan(run_racks: list[str], run_hosts: list[str], units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every scalable unit the run touched, drawn whole: its racks in order, each rack's nodes in tray order.

    A node is ``used`` when the run held it. The whole unit is drawn, not only the run's racks, so the
    figure shows what the run left out as plainly as what it took -- the spare trays of a rack, the racks
    of the unit another run covered. Nodes are the inventory's placement (tray = place in the rack by
    install order, as on the Racks floor view); a rack the inventory has not placed draws empty.
    """
    used = {h.casefold() for h in run_hosts}
    wanted = {r.casefold() for r in run_racks}
    plan: list[dict[str, Any]] = []
    for unit in units:
        racks = [str(r) for r in unit.get("racks") or []]
        if not any(r.casefold() in wanted for r in racks):
            continue
        drawn = []
        for rack in sorted(racks, key=natural_key):
            members = native_status.placed_rack_members(rack) or []
            drawn.append({
                "rack": rack,
                "in_run": rack.casefold() in wanted,
                "nodes": [{"host": h, "used": h.casefold() in used} for h in members],
            })
        plan.append({"su": str(unit.get("label") or unit.get("id") or ""), "racks": drawn})
    return plan


def run_detail(activity_id: str) -> dict[str, Any] | None:
    """One run in full: its summary, the curves the charts draw, and what it ran with.

    ``None`` when the registry has no such multi-rack run.
    """
    rec = validation_activities.get_activity(activity_id)
    if rec is None or str(rec.get("scope") or "") != "multirack":
        return None
    if refresh_activities_lazy([rec]):
        rec = validation_activities.get_activity(activity_id) or rec
    # A run that finished before job times were recorded has them filled in on its first read.
    if is_finished(rec) and not any(isinstance(t, dict) and t.get("ended_at") for t in rec.get("tasks") or []):
        try:
            if record_job_times(activity_id):
                rec = validation_activities.get_activity(activity_id) or rec
        except Exception:  # the launcher's times still stand in
            _logger.debug("handover report: job times unavailable for %s", activity_id, exc_info=True)
    ctx = site_context()
    logs = task_logs(rec)
    scans = {p: _logscan_record(p) for p in logs}
    good = [p for p in logs if isinstance(scans.get(p), dict) and scans[p].get("ok")]
    summary = _merge([summarize_scan(scans[p]) for p in good])

    curves: dict[str, list[dict[str, Any]]] = {}
    steps: list[float] = []
    statements: list[str] = []
    for path in good:
        scan = scans[path]
        for name, rows in ((scan.get("nccl") or {}).get("series_by_collective") or {}).items():
            if rows and name not in curves:
                curves[name] = [
                    {"size_bytes": int(p["size_bytes"]), "busbw_gbps": float(p["bus_bw_gbps"])} for p in rows
                ]
        if not steps:
            steps = [float(v) for v in ((scan.get("nemo") or {}).get("step_series") or [])]
        for line in scan.get("statements") or []:
            if line not in statements:
                statements.append(line)

    row = _row({**rec, "results_summary": {"version": SUMMARY_VERSION, "logs": good, **summary}}, ctx["rack_su"])
    nodes, facts_state = _node_rows(rec)
    if facts_state == "not_collected" and is_finished(rec) and ensure_node_facts(activity_id):
        facts_state = "collecting"
    stored_facts = rec.get("node_facts") if isinstance(rec.get("node_facts"), dict) else {}
    return {
        **row,
        "site": {k: v for k, v in ctx.items() if k not in _CONTEXT_ONLY},
        "rack_su": {r: ctx["rack_su"][r] for r in row["racks"] if r in ctx["rack_su"]},
        "logs": [
            {"path": p, "scanned": p in good, "bytes": (scans.get(p) or {}).get("bytes")} for p in logs
        ],
        "nccl_curves": curves,
        "llm_steps": _thin(steps),
        "settings": {
            "launch_env": dict(rec.get("launch_env") or {}),
            "stated": stated_settings(statements),
        },
        "statements": statements,
        "command": _launch_command(rec),
        "nccl_commands": nccl_commands(stated_settings(statements), dict(rec.get("launch_env") or {})),
        "error_summary": str(rec.get("issue_summary") or rec.get("error") or ""),
        "node_rows": nodes,
        "floor_plan": floor_plan(row["racks"], [n["host"] for n in nodes], ctx.get("units") or []),
        "alltoall_ceiling": alltoall_ceiling(row, nodes, ctx["rack_su"]),
        "node_facts": {
            "state": facts_state,
            "collected_at": stored_facts.get("collected_at") or "",
            "bringup_jobs": list(BRINGUP_NCCL_JOBS),
            "bringup_error": stored_facts.get("bringup_error") or "",
        },
    }


def report_dataset(activity_ids: list[str]) -> dict[str, Any]:
    """The handover report over one or more runs: the site, then each run in full.

    Runs the registry does not have are named in ``missing`` rather than dropped silently.
    """
    runs: list[dict[str, Any]] = []
    missing: list[str] = []
    for aid in activity_ids:
        detail = run_detail(aid)
        (runs if detail is not None else missing).append(detail if detail is not None else aid)
    runs.sort(key=lambda r: str(r.get("created_at") or ""))
    racks = sorted({r for run in runs for r in run["racks"]}, key=natural_key)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site": runs[0]["site"] if runs else {k: v for k, v in site_context().items() if k not in _CONTEXT_ONLY},
        "racks": racks,
        "scalable_units": sorted({su for run in runs for su in run["scalable_units"]}, key=natural_key),
        "runs": runs,
        "missing": missing,
    }
