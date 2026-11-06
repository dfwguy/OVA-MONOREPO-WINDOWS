# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""PDF rendering of the handover dataset (:mod:`handover_report`), on the NVIDIA letterhead.

The page is the one the NVIDIA report kit produces through Word -- logo on page 1, NVIDIA Sans,
black headings over a green rule, black-headed tables -- drawn directly so the server needs no
Word and no template: 1" margins on US Letter, the template's type sizes and its 1.2x body leading.
The same dataset feeds the page's JSON, so the document cannot say something the page does not.

Order, for a reader who signs off on page 1: the site and racks, every run's headline numbers
against each other, then each run in full -- its results, the busbw-per-message-size and
steps-per-second charts, the settings it ran with and the command that launched it.

reportlab is imported lazily, as in ``cluster_report_pdf``, and the charts use its own primitives.
"""
from __future__ import annotations

import io
import logging
import math
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent / "assets" / "report"

GREEN, GREEN_SOFT, GRAY_SOFT, RULE = "#76B900", "#E9F4D3", "#F2F2F2", "#BFBFBF"
INK, MUTED = "#1A1A1A", "#595959"
#: One hue per collective, fixed order (Okabe-Ito hues with NVIDIA green for the headline,
#: all-to-all); every line also carries a legend entry, so identity is never color alone.
SERIES_COLORS = {
    "alltoall": GREEN,
    "all_reduce": "#0072B2",
    "all_gather": "#CC79A7",
    "reduce_scatter": "#E69F00",
}
LABELS = {"all_reduce": "All-reduce", "alltoall": "All-to-all", "all_gather": "All-gather",
          "reduce_scatter": "Reduce-scatter"}
RUN_TYPES = {"nccl": "NCCL", "llm": "LLM", "both": "LLM", "none": "No results"}
#: An LLM job sweeps NCCL before it trains -- inside its container, with the training job's NCCL
#: settings. Real numbers, but not the acceptance test's, so they are never set beside it.
PREFLIGHT_NOTE = ("This LLM job swept NCCL as a preflight before training, inside its container and with the "
                  "training job's NCCL settings rather than the tuned settings of the NCCL acceptance test, so these "
                  "figures are lower by design and are not compared with the NCCL test runs.")
PRODUCT = "NVIS Rack Status"
#: The collectives drawn one chart each, over the message sizes acceptance is judged at.
BAND_COLLECTIVES = ("all_reduce", "alltoall", "all_gather")
BAND_MIN_BYTES, BAND_MAX_BYTES = 2 * 1024**3, 16 * 1024**3
#: Bring-up's own per-node NCCL jobs, as the node table heads them.
BRINGUP_HEADS = {"allreduce": "AR", "alltoall": "A2A", "allreduce-nonvlink": "AR RoCE",
                 "alltoall-nonvlink": "A2A RoCE"}

#: Word's single line for NVIDIA Sans is 1.26 x the size; the template's NVIDIA styles use 1.2x that.
_SINGLE = 1.26
FONT, BOLD = "NVSans", "NVSans-Bold"


def available() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


def _fonts() -> tuple[str, str]:
    """NVIDIA Sans when its files are present, Helvetica otherwise (the document still renders)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFError, TTFont

    if FONT in pdfmetrics.getRegisteredFontNames():
        return FONT, BOLD
    try:
        pdfmetrics.registerFont(TTFont(FONT, str(ASSETS / "NVIDIASans-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(BOLD, str(ASSETS / "NVIDIASans-Bold.ttf")))
        pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=BOLD, italic=FONT, boldItalic=BOLD)
        return FONT, BOLD
    except (OSError, TTFError):  # missing or unreadable asset: degrade, do not fail the report
        _log.warning("NVIDIA Sans unavailable for the handover PDF; using Helvetica", exc_info=True)
        return "Helvetica", "Helvetica-Bold"


# --- small formatting helpers ---------------------------------------------------------------------


def _esc(value: Any) -> str:
    return str(value if value is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _gbps(value: Any) -> str:
    return f"{float(value):.1f}" if isinstance(value, (int, float)) else "—"


def _size(size: Any) -> str:
    try:
        n = int(size)
    except (TypeError, ValueError):
        return "—"
    # nccl-tests rounds sizes to what divides across the ranks: 17,179,869,180 bytes is "16 GB".
    for unit, div in (("G", 1024**3), ("M", 1024**2), ("K", 1024)):
        if n >= div * 0.99:
            value = n / div
            return f"{round(value)} {unit}B" if abs(value - round(value)) <= 0.01 * value else f"{value:.1f} {unit}B"
    return f"{n} B"


def _when(iso: Any) -> str:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return str(iso or "—")


def _day(iso: Any) -> str:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%B %-d, %Y")
    except (TypeError, ValueError):
        return ""


def _jobs(run: dict[str, Any]) -> str:
    return ", ".join(run.get("scheduler_job_ids") or []) or run.get("activity_id", "")[:8]


def _racks(run: dict[str, Any]) -> str:
    su = run.get("rack_su") or {}
    return ", ".join(f"{r} ({su[r]})" if r in su else r for r in run.get("racks") or [])


# --- the document ----------------------------------------------------------------------------------


def to_pdf(dataset: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        BaseDocTemplate,
        CondPageBreak,
        Frame,
        HRFlowable,
        KeepTogether,
        NextPageTemplate,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        XPreformatted,
    )

    font, bold = _fonts()
    width, height = letter
    margin = 1 * inch
    text_w = width - 2 * margin

    def lead(size: float, multiple: float = 1.0) -> float:
        return size * _SINGLE * multiple

    st = {
        "headline": ParagraphStyle("headline", fontName=bold, fontSize=24, leading=lead(24, 1.2),
                                   textColor=INK, spaceAfter=9),
        "sub": ParagraphStyle("sub", fontName=font, fontSize=18, leading=lead(18, 1.2), textColor=INK,
                              spaceBefore=6, spaceAfter=14),
        "meta": ParagraphStyle("meta", fontName=font, fontSize=9, leading=lead(9, 1.2), textColor=MUTED,
                               spaceAfter=6),
        "body": ParagraphStyle("body", fontName=font, fontSize=10, leading=lead(10, 1.2), textColor=INK,
                               spaceAfter=6),
        "note": ParagraphStyle("note", fontName=font, fontSize=8.5, leading=lead(8.5, 1.2), textColor=MUTED,
                               spaceAfter=8),
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=16, leading=lead(16), textColor=INK, spaceBefore=20),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=12.5, leading=lead(12.5), textColor=INK,
                             spaceBefore=16, spaceAfter=4),
        "cell": ParagraphStyle("cell", fontName=font, fontSize=8, leading=lead(8), textColor=INK),
        "cellr": ParagraphStyle("cellr", fontName=font, fontSize=8, leading=lead(8), textColor=INK,
                                alignment=TA_RIGHT),
        "head": ParagraphStyle("head", fontName=bold, fontSize=8, leading=lead(8), textColor=colors.white),
        "headr": ParagraphStyle("headr", fontName=bold, fontSize=8, leading=lead(8), textColor=colors.white,
                                alignment=TA_RIGHT),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=7.2, leading=8.2, textColor=INK,
                               backColor=GRAY_SOFT, leftIndent=6, rightIndent=6, borderPadding=4,
                               spaceBefore=4, spaceAfter=10),
    }

    def h1(text: str, *, new_page: bool = False) -> list:
        return ([PageBreak()] if new_page else []) + [
            CondPageBreak(1.6 * inch),
            Paragraph(_esc(text), st["h1"]),
            HRFlowable(width="100%", thickness=1.5, color=colors.HexColor(GREEN), spaceBefore=1.5, spaceAfter=6),
        ]

    def h2(text: str) -> list:
        return [CondPageBreak(1.2 * inch), Paragraph(_esc(text), st["h2"])]

    def table(headers: list[str], rows: list[list[Any]], widths: list[float], *, numeric=(), hi=(),
              mono=()) -> Table:
        """Black header row, light rules; *mono* columns hold literal arguments and are set in Courier."""
        data = [[Paragraph(_esc(h), st["headr" if i in numeric else "head"]) for i, h in enumerate(headers)]]
        for row in rows:
            data.append([
                Paragraph(f'<font face="Courier" size="7.5">{_esc(v)}</font>' if i in mono else _esc(v),
                          st["cellr" if i in numeric else "cell"])
                for i, v in enumerate(row)
            ])
        t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1, hAlign="LEFT")
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor(RULE)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for r in hi:
            style.append(("BACKGROUND", (0, r + 1), (-1, r + 1), colors.HexColor(GREEN_SOFT)))
        t.setStyle(TableStyle(style))
        return t

    def kv(pairs: list[tuple[str, Any]]) -> Table:
        return table(["Item", "Value"], [[k, v] for k, v in pairs], [1.6, text_w / inch - 1.6])

    site = dataset.get("site") or {}
    runs = [r for r in dataset.get("runs") or [] if isinstance(r, dict)]
    title = "Rack Handover Report"
    site_line = " / ".join(x for x in (site.get("project"), site.get("cluster")) if x) or PRODUCT
    generated = _day(dataset.get("generated_at"))

    story: list = [
        Paragraph(title, st["headline"]),
        Paragraph(_esc(site_line), st["sub"]),
        Paragraph(_esc(" | ".join(x for x in (f"Generated by {PRODUCT}", generated) if x)), st["meta"]),
        NextPageTemplate("later"),
    ]

    # --- summary ------------------------------------------------------------------------------
    story += h1("Summary")
    gpus = max((r.get("gpus") or 0 for r in runs), default=0)
    nodes = max((r.get("nodes") or 0 for r in runs), default=0)
    first = min((str(r.get("job_started_at") or r.get("created_at") or "") for r in runs), default="")
    last = max((str(r.get("job_ended_at") or r.get("finished_at") or r.get("created_at") or "") for r in runs),
               default="")
    story.append(kv([
        ("Project", site.get("project") or "—"),
        ("Cluster", site.get("cluster") or "—"),
        ("Platform", " ".join(x for x in (site.get("platform"), site.get("gpu_model")) if x) or "—"),
        ("Racks", ", ".join(dataset.get("racks") or []) or "—"),
        ("Scalable units", ", ".join(dataset.get("scalable_units") or []) or "—"),
        ("Runs", str(len(runs))),
        ("Largest run", f"{nodes} nodes, {gpus} GPUs" if gpus else "—"),
        ("Tested", f"{_when(first)} to {_when(last)}" if first else "—"),
    ]))
    story.append(Spacer(1, 10))
    if runs:
        rows = []
        for r in runs:
            # An LLM job's NCCL figures are its preflight: shown in its own section, not compared here.
            c = (r.get("collectives") or {}) if r.get("run_type") != "both" else {}
            llm = r.get("llm") or {}
            rows.append([
                _when(r.get("created_at"))[:16],
                _jobs(r),
                RUN_TYPES.get(r.get("run_type") or "none", r.get("run_type")),
                r.get("gpus") or "—",
                _gbps((c.get("all_reduce") or {}).get("busbw_2g_gbps")),
                _gbps((c.get("alltoall") or {}).get("busbw_2g_gbps")),
                _gbps((c.get("all_gather") or {}).get("busbw_2g_gbps")),
                " ".join(x for x in (llm.get("model"), llm.get("model_size")) if x) or "—",
                _gbps(llm.get("tflops_per_gpu")),
                f"{llm['step_time_s']:.2f}" if isinstance(llm.get("step_time_s"), (int, float)) else "—",
            ])
        story.append(table(
            ["Date", "Job", "Type", "GPUs", "AR @2G", "A2A @2G", "AG @2G", "LLM model", "TFLOP/s /GPU", "Step (s)"],
            rows, [0.95, 0.55, 0.65, 0.4, 0.55, 0.55, 0.55, 0.85, 0.6, 0.45], numeric=(3, 4, 5, 6, 8, 9),
        ))
        story.append(Paragraph(
            "NCCL bus bandwidth in GB/s at a 2 GB message, the size acceptance criteria are stated at, from the "
            "NCCL test runs. LLM figures are the mean over the measured window of the training run; an LLM run's own "
            "NCCL preflight is in its section.", st["note"]))
    ceilings = [r for r in runs if r.get("alltoall_ceiling")]
    if ceilings:
        # One block: the explanation is only useful beside the table it explains.
        story.append(KeepTogether([Paragraph("All-to-all against its ceiling", st["h2"]),
                                   Paragraph(_esc(CEILING_TEXT), st["body"]), table(
            ["Job", "GPUs", "Racks by SU", "NIC (GB/s)", "Ceiling", "A2A @2G", "% @2G", "A2A peak", "% peak"],
            [[_jobs(r), r.get("gpus") or "—", _su_mix(c["su_racks"]), _gbps(c["nic_gbps"]), _gbps(c["ceiling_gbps"]),
              _gbps(c["busbw_2g_gbps"]), _pct(c["pct_2g"]), _gbps(c["busbw_peak_gbps"]), _pct(c["pct_peak"])]
             for r in ceilings for c in [r["alltoall_ceiling"]]],
            [0.55, 0.45, 1.8, 0.7, 0.6, 0.65, 0.55, 0.65, 0.55], numeric=(1, 3, 4, 5, 6, 7, 8),
        ), Paragraph(_esc(CEILING_NOTE), st["note"])]))
    if dataset.get("missing"):
        story.append(Paragraph(_esc("Not found in the run registry: " + ", ".join(dataset["missing"])), st["note"]))

    # --- each run -----------------------------------------------------------------------------
    for i, run in enumerate(runs):
        story += h1(f"Run {_jobs(run)}: {RUN_TYPES.get(run.get('run_type') or 'none', '')}", new_page=True)
        story.append(kv([
            ("Activity", run.get("activity_id") or "—"),
            ("Tool", run.get("tool") or "—"),
            ("Started", _when(run.get("job_started_at") or run.get("created_at"))),
            ("Finished", _when(run.get("job_ended_at") or run.get("finished_at"))
             if (run.get("job_ended_at") or run.get("finished_at")) else "—"),
            ("Racks", _racks(run) or "—"),
            ("Nodes / GPUs", f"{run.get('nodes') or '—'} / {run.get('gpus') or '—'}"),
            ("Outcome", run.get("outcome") or "—"),
            ("Operator", run.get("operator") or "—"),
        ]))
        if run.get("error_summary"):
            story.append(Paragraph(_esc("Issue: " + run["error_summary"]), st["note"]))

        coll = run.get("collectives") or {}
        if coll:
            preflight = run.get("run_type") == "both"
            story += h2("NCCL preflight (inside the LLM job)" if preflight else "NCCL results")
            if preflight:
                story.append(Paragraph(_esc(PREFLIGHT_NOTE), st["note"]))
            names = [n for n in LABELS if n in coll]
            story.append(table(
                ["Collective", "Bus bandwidth @2 GB (GB/s)", "Peak bus bandwidth (GB/s)", "Largest message"],
                [[LABELS[n], _gbps(coll[n].get("busbw_2g_gbps")), _gbps(coll[n].get("busbw_peak_gbps")),
                  _size(coll[n].get("max_size_bytes"))] for n in names],
                [1.6, 1.7, 1.7, 1.5], numeric=(1, 2, 3), hi=tuple(j for j, n in enumerate(names) if n == "alltoall"),
            ))
            charts = [c for c in (_band_chart(run.get("nccl_curves") or {}, n, text_w / 3 - 6, colors)
                                  for n in BAND_COLLECTIVES) if c is not None]
            if charts:
                story.append(Spacer(1, 8))
                story.append(KeepTogether([
                    Table([charts], colWidths=[text_w / 3] * len(charts), hAlign="LEFT",
                          style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]),
                    Paragraph("Figure: out-of-place bus bandwidth from 2 GB to 16 GB messages, best sweep of "
                              "each collective; the number at each point is its busbw in GB/s.", st["note"]),
                ]))
            ceiling = run.get("alltoall_ceiling")
            if ceiling:
                story.append(KeepTogether([
                    Paragraph("All-to-all against its ceiling", st["h2"]),
                    kv(_ceiling_pairs(ceiling, run.get("gpus"))),
                    Paragraph("The summary explains how the ceiling is derived.", st["note"]),
                ]))

        llm = run.get("llm") or {}
        if llm:
            story += h2("LLM training")
            story.append(kv([
                ("Model", " ".join(x for x in (llm.get("model"), llm.get("model_size")) if x) or "—"),
                ("Precision", llm.get("dtype") or "—"),
                ("Global batch", llm.get("global_batch") or "—"),
                ("Steps", f"{llm.get('steps') or '—'} of {llm.get('declared_steps') or '—'}"
                          + (" (finished)" if llm.get("finished") else "")),
                ("Step time (s)", f"{llm['step_time_s']:.2f}" if isinstance(llm.get("step_time_s"), (int, float)) else "—"),
                ("Throughput (steps/s)", f"{1 / llm['step_time_s']:.3f}" if llm.get("step_time_s") else "—"),
                ("Model TFLOP/s per GPU", _gbps(llm.get("tflops_per_gpu"))),
                ("MFU", f"{llm['mfu_percent']:.1f}%" if isinstance(llm.get("mfu_percent"), (int, float)) else "—"),
            ]))
            chart = _steps_chart(run.get("llm_steps") or [], text_w, colors)
            if chart is not None:
                story.append(Spacer(1, 8))
                story.append(KeepTogether([chart, Paragraph(
                    "Figure: training throughput per step (steps per second); the first steps include warm-up.",
                    st["note"])]))

        story += _settings(run, st, table, h2, Paragraph, XPreformatted)
        story += _nodes(run, st, table, h2, Paragraph, text_w, colors, KeepTogether)
        if i == len(runs) - 1:
            story.append(Spacer(1, 4))

    # --- page furniture -----------------------------------------------------------------------
    footer = " | ".join(x for x in ("NVIDIA Confidential", title, site.get("cluster"), generated) if x)

    def _foot(canvas, doc, numbered: bool) -> None:
        canvas.saveState()
        canvas.setFont(font, 7.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(margin, 31, footer)
        if numbered:
            canvas.drawRightString(width - margin, 31, f"Page {doc.page}")
        canvas.restoreState()

    def _first(canvas, doc) -> None:
        logo = ASSETS / "nvidia_logo.png"
        if logo.is_file():
            canvas.drawImage(str(logo), 58.0, height - 137.7, width=98.3, height=79.7, mask="auto")
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#70AD47"))  # the letterhead's own rule above the footer
        canvas.rect(71.3, height - 753.8, 473.3, 1.4, stroke=0, fill=1)
        canvas.restoreState()
        _foot(canvas, doc, numbered=False)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=letter, title=f"{title} - {site_line}", author=PRODUCT,
                          leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin)
    pad = {"leftPadding": 0, "rightPadding": 0, "topPadding": 0, "bottomPadding": 0}
    doc.addPageTemplates([
        PageTemplate("first", [Frame(margin, margin, text_w, height - margin - 2.06 * inch, id="first", **pad)],
                     onPage=_first),
        PageTemplate("later", [Frame(margin, margin, text_w, height - 2 * margin, id="later", **pad)],
                     onPage=lambda c, d: _foot(c, d, numbered=True)),
    ])
    doc.build(story)
    return buf.getvalue()


def _settings(run: dict[str, Any], st, table, h2, Paragraph, XPreformatted) -> list:
    """Configuration and command: what the run was given and what it says it ran with."""
    out: list = []
    settings = run.get("settings") or {}
    stated = settings.get("stated") or {}
    launch_env = settings.get("launch_env") or {}

    facts = [
        ("NCCL version", stated.get("nccl_version")),
        ("Collectives", " ".join(stated.get("collectives") or [])),
        ("Message sizes", stated.get("sizes")),
        ("Rounds", stated.get("rounds")),
        ("Model arguments", stated.get("model_args")),
        ("Training arguments", stated.get("extra_args")),
    ]
    facts = [(k, v) for k, v in facts if v not in (None, "", [])]
    if facts:
        out += h2("Configuration")
        out.append(table(["Setting", "Value"], [[k, v] for k, v in facts], [1.6, 4.9], mono=(1,)))

    per = stated.get("per_collective") or {}
    if per:
        out += h2("Per-collective NCCL settings")
        rows = [[LABELS.get(c, c), k, v] for c, env in per.items() for k, v in sorted(env.items())]
        out.append(table(["Collective", "Variable", "Value"], rows, [1.3, 2.8, 2.4], mono=(2,)))

    env = dict(stated.get("env") or {})
    if launch_env:
        out += h2("Environment (as launched)")
        rows = [[k, v] for k, v in sorted(launch_env.items()) if not k.startswith("NVIS_NCCL_ENV_")]
        out.append(table(["Variable", "Value"], rows, [2.6, 3.9], mono=(1,)))
        if any(k.startswith("NVIS_NCCL_ENV_") for k in launch_env):
            out.append(Paragraph("Per-collective blocks (NVIS_NCCL_ENV_*) are listed under per-collective settings.",
                                 st["note"]))
    if env:
        out += h2("Environment (as stated by the job)")
        out.append(table(["Variable", "Value"], [[k, v] for k, v in sorted(env.items())], [2.6, 3.9], mono=(1,)))
        out.append(Paragraph("Variables the launchers printed in the job log, for every rank.", st["note"]))

    commands = run.get("nccl_commands") or []
    if commands:
        out += h2("NCCL test commands")
        stated = all(c.get("source") == "stated" for c in commands)
        nodes = len(run.get("node_rows") or []) or run.get("nodes") or "the run's"
        out.append(Paragraph(_esc(
            f"Each collective as nccl-tests ran it, to reproduce outside {PRODUCT}. 'hosts' is a file with one "
            f"'<node> slots={_slots(run)}' line per node ({nodes} nodes, listed under Nodes). "
            + ("The job printed these commands and values itself." if stated else
               "Reconstructed from the job's log, which predates printing the command; a value the log did "
               "not record is shown as <not recorded> and is the site's own setting.")), st["note"]))
        for cmd in commands:
            out.append(XPreformatted(_esc(_command_block(cmd)), st["code"]))
    command = run.get("command") or {}
    if command.get("launcher"):
        out += h2(f"Launched through {PRODUCT}")
        out.append(XPreformatted(_esc(_wrap(_short_nodelist(command["launcher"]))), st["code"]))
    return out


CEILING_TEXT = (
    "In all-to-all every GPU sends an equal share of its buffer to every other GPU. The share bound for its "
    "own rack travels over NVLink; the rest leaves through the GPU's network interface, and that sets the "
    "pace. With N GPUs in the run, R of them in each rack, and B the bus bandwidth one GPU drives through its "
    "network interface, the most all-to-all can reach is  ceiling = B x (N - 1) / (N - R).  B is measured on "
    "these nodes, not taken from a datasheet: the median of each node's own bring-up all-to-all with NVLink "
    "off, which sends every byte over its interfaces. The ceiling falls as a run grows, because a larger share "
    "of every GPU's traffic leaves its rack: the same nodes have a lower ceiling at 1024 GPUs than at 128."
)
CEILING_NOTE = (
    "Bus bandwidth in GB/s. Peak is at the largest message of the run's sweep. Racks by SU shows how the run "
    "was spread across scalable units: racks in one unit share its leaf switches, so a run concentrated in "
    "one unit and a run spread across several can reach a different share of the same ceiling."
)


def _pct(value: Any) -> str:
    return f"{value:.1f}%" if isinstance(value, (int, float)) else "—"


def _su_mix(su_racks: dict[str, int]) -> str:
    return ", ".join(f"{su} x{n}" for su, n in su_racks.items()) or "—"


def _ceiling_pairs(c: dict[str, Any], gpus: Any) -> list[tuple[str, Any]]:
    return [
        ("All-to-all ceiling", (f"{_gbps(c['ceiling_gbps'])} GB/s = {_gbps(c['nic_gbps'])} x ({gpus} - 1) / "
                                f"({gpus} - {c['gpus_per_rack']})")),
        ("Achieved @2 GB", f"{_gbps(c['busbw_2g_gbps'])} GB/s, {_pct(c['pct_2g'])} of ceiling"),
        ("Achieved at peak", f"{_gbps(c['busbw_peak_gbps'])} GB/s, {_pct(c['pct_peak'])} of ceiling"),
        ("NIC rate (B)", (f"{_gbps(c['nic_gbps'])} GB/s, median of {c['nic_nodes']} nodes' bring-up all-to-all "
                          f"with NVLink off; slowest {_gbps(c['nic_min_gbps'])} ({c['nic_min_host']})")),
        ("Racks by SU", _su_mix(c.get("su_racks") or {})),
    ]


def _slots(run: dict[str, Any]) -> int:
    gpus, nodes = run.get("gpus") or 0, run.get("nodes") or len(run.get("node_rows") or [])
    return gpus // nodes if gpus and nodes else 4


def _short_nodelist(command: str) -> str:
    """The launcher line with its node list summarized: the nodes are tabled under Nodes."""
    return re.sub(r"--nodelist\s+(\S+)",
                  lambda m: f"--nodelist <{len(m.group(1).split(','))} nodes, see Nodes>", command)


def _command_block(cmd: dict[str, Any]) -> str:
    """One collective's program as shell lines: its exports, then the mpirun command, wrapped."""
    lines = [f"# {LABELS.get(cmd.get('collective'), cmd.get('collective'))} ({cmd.get('source')})"]
    if cmd.get("ld_library_path"):
        lines.append(_wrap_word(f"export LD_LIBRARY_PATH={cmd['ld_library_path']}"))
    for k, v in (cmd.get("env") or {}).items():
        lines.append(_wrap_word(f"export {k}={v if v != '' else '<not recorded>'}"))
    lines.append(_wrap_args(str(cmd.get("command") or "")))
    return "\n".join(lines)


def _wrap_word(line: str, width: int = 96) -> str:
    """Break one long unquoted word (a library path list, a plugin path) after a '/' or ':'.

    The continuation line starts at column 0: the shell removes a backslash-newline, so the halves
    rejoin into exactly the original word -- an indent would put a space inside the value. A line
    with quotes is left whole, since a backslash-newline inside single quotes stays literal.
    """
    if len(line) <= width or "'" in line or '"' in line:
        return line
    out = []
    while len(line) > width:
        # Between whole paths of a list first; inside one path only when no list separator is near.
        cut = line.rfind(":", 0, width)
        if cut < width // 3:
            cut = line.rfind("/", 0, width)
        if cut < width // 3:
            break
        out.append(line[: cut + 1] + "\\")
        line = line[cut + 1 :]
    out.append(line)
    return "\n".join(out)


# How many values each option of an mpirun / nccl-tests line takes, so an option and its values
# stay on one line.
_ARITY = {"--mca": 2, "-x": 1, "-np": 1, "--hostfile": 1, "--map-by": 1, "--bind-to": 1,
          "-b": 1, "-e": 1, "-f": 1, "-g": 1, "-T": 1, "-n": 1, "-w": 1, "-c": 1}


def _wrap_args(command: str, width: int = 92) -> str:
    """Break a long command between its options, with shell continuations.

    Split as the shell would (``shlex``) and re-quoted, so a quoted argument -- the ssh agent, with
    its own spaces -- is never broken across lines, where the continuation would land inside it;
    and an option is kept with its values (``--mca plm_rsh_agent '<agent>'`` reads as one setting).
    """
    try:
        tokens = [shlex.quote(t) for t in shlex.split(command)]
    except ValueError:  # unbalanced quotes: show it as it was rather than guess
        return command
    groups: list[str] = []
    i = 0
    while i < len(tokens):
        n = _ARITY.get(tokens[i], 0) + 1
        groups.append(" ".join(tokens[i:i + n]))
        i += n
    out, line = [], ""
    for group in groups:
        if line and len(line) + 1 + len(group) > width:
            out.append(line + " \\")
            line = "    " + group
        else:
            line = f"{line} {group}" if line else group
    out.append(line)
    return "\n".join(out)


def _nodes(run: dict[str, Any], st, table, h2, Paragraph, width: float, colors, KeepTogether) -> list:
    """Every node the run covered, with its own bring-up NCCL results."""
    nodes = run.get("node_rows") or []
    if not nodes:
        return []
    facts = run.get("node_facts") or {}
    jobs = [j for j in facts.get("bringup_jobs") or BRINGUP_HEADS if j in BRINGUP_HEADS]
    rows = []
    for n in nodes:
        b = n.get("bringup") or {}
        rows.append([n.get("host"), n.get("rack") or "—", n.get("ip") or "—",
                     *[b.get(j) or "—" for j in jobs[:2]], "—", *[b.get(j) or "—" for j in jobs[2:]]])
    heads = ["Node", "Rack", "IP", *[BRINGUP_HEADS[j] for j in jobs[:2]], "AG",
             *[BRINGUP_HEADS[j] for j in jobs[2:]]]
    widths = [1.95, 0.45, 1.05, 0.6, 0.6, 0.35, 0.7, 0.8][: len(heads)]  # 6.5 in, the text width
    out = h2(f"Nodes ({len(nodes)})")
    plan = run.get("floor_plan") or []
    if plan:
        used = sum(1 for su in plan for r in su["racks"] for n in r["nodes"] if n["used"])
        total = sum(len(r["nodes"]) for su in plan for r in su["racks"])
        figure = [d for su in plan for d in _floor_plan(su, width, colors)]
        figure.append(_floor_legend(width, colors, used, total))
        figure.append(Paragraph(_esc(
            f"Figure: the {'scalable unit' if len(plan) == 1 else 'scalable units'} this run used, drawn whole -- "
            "every rack in floor order, every node in tray order as on the Racks floor view. Green nodes ran "
            "in this run; gray nodes are in the same units but were not part of it."), st["note"]))
        out.append(KeepTogether(figure))
    if facts.get("state") == "ready":
        note = (f"Bring-up's own per-node NCCL tests, bus bandwidth in GB/s: AR and A2A over NVLink inside the "
                f"node, RoCE the same collectives forced onto the rails. Bring-up runs no all-gather test, so AG "
                f"is not measured per node. Collected "
                f"{_when(facts.get('collected_at'))}.")
        if facts.get("bringup_error"):
            note += f" Bring-up results unavailable: {facts['bringup_error']}."
    else:
        note = "Bring-up results were not collected for this run yet."
    out.append(Paragraph(_esc(note), st["note"]))
    out.append(table(heads, rows, widths, numeric=tuple(range(3, len(heads)))))
    return out


FLOOR_USED, FLOOR_IDLE = GREEN, "#D0D0D0"
FLOOR_RACKS_PER_LINE = 8


def _floor_plan(su: dict[str, Any], width: float, colors) -> list:
    """One scalable unit as rack tiles, each a grid of its nodes in tray order (two rows of nine
    for an 18-tray rack); one drawing per line of racks, so a large unit wraps instead of shrinking."""
    from reportlab.graphics.shapes import Drawing, Rect, String

    racks = su.get("racks") or []
    lines = [racks[i:i + FLOOR_RACKS_PER_LINE] for i in range(0, len(racks), FLOOR_RACKS_PER_LINE)] or [[]]
    per_line = min(max(len(racks), 1), FLOOR_RACKS_PER_LINE)
    tile_w = width / per_line
    out = []
    for li, line in enumerate(lines):
        most = max((len(r["nodes"]) for r in line), default=0)
        cols = min(9, max(1, -(-most // 2)))
        gap = 1.2
        cell = min(9.0, (tile_w - 10 - gap * (cols - 1)) / cols)
        rows = max(1, -(-most // cols)) if most else 1
        head = 13 if li == 0 else 0
        grid_h = rows * cell + (rows - 1) * gap
        height = head + 11 + grid_h + 10
        d = Drawing(width, height)
        if li == 0:
            d.add(String(0, height - 9, str(su.get("su") or ""), fontName="Helvetica-Bold", fontSize=8.5,
                         fillColor=colors.HexColor(INK)))
        for ri, rack in enumerate(line):
            x0 = ri * tile_w + 4
            top = height - head - 2
            d.add(String(x0 + (tile_w - 8) / 2, top - 8, rack["rack"],
                         fontName="Helvetica-Bold" if rack.get("in_run") else "Helvetica", fontSize=7,
                         fillColor=colors.HexColor(INK if rack.get("in_run") else MUTED), textAnchor="middle"))
            gx = x0 + (tile_w - 8 - (cols * cell + (cols - 1) * gap)) / 2
            gy_top = top - 12
            d.add(Rect(x0, gy_top - grid_h - 3, tile_w - 8, grid_h + 6, strokeColor=colors.HexColor(RULE),
                       strokeWidth=0.4, fillColor=None))
            for ni, node in enumerate(rack["nodes"]):
                r_, c_ = divmod(ni, cols)
                d.add(Rect(gx + c_ * (cell + gap), gy_top - (r_ + 1) * cell - r_ * gap, cell, cell, strokeWidth=0,
                           fillColor=colors.HexColor(FLOOR_USED if node.get("used") else FLOOR_IDLE)))
            if not rack["nodes"]:
                d.add(String(x0 + (tile_w - 8) / 2, gy_top - grid_h / 2 - 3, "not placed", fontName="Helvetica",
                             fontSize=6, fillColor=colors.HexColor(MUTED), textAnchor="middle"))
        out.append(d)
    return out


def _floor_legend(width: float, colors, used: int, total: int):
    from reportlab.graphics.shapes import Drawing, Rect, String

    d = Drawing(width, 14)
    x = 0.0
    for color, label in ((FLOOR_USED, f"In this run ({used} nodes)"),
                         (FLOOR_IDLE, f"Not in this run ({total - used} nodes)")):
        d.add(Rect(x, 3, 8, 8, strokeWidth=0, fillColor=colors.HexColor(color)))
        d.add(String(x + 12, 4, label, fontName="Helvetica", fontSize=7.5, fillColor=colors.HexColor(INK)))
        x += 150
    return d


def _wrap(text: str, width: int = 100) -> str:
    """Hard-wrap long command lines with a shell continuation so nothing runs off the page."""
    out: list[str] = []
    for line in text.splitlines():
        while len(line) > width:
            cut = line.rfind(",", 0, width)
            cut = cut if cut > width // 2 else width
            out.append(line[: cut + 1] + " \\")
            line = "    " + line[cut + 1 :]
        out.append(line)
    return "\n".join(out)


# --- charts ---------------------------------------------------------------------------------------


def _axis_style(chart, colors, font_size: float = 7) -> None:
    for axis in (chart.xValueAxis, chart.yValueAxis):
        axis.labels.fontName = "Helvetica"
        axis.labels.fontSize = font_size
        axis.labels.fillColor = colors.HexColor(MUTED)
        axis.strokeColor = colors.HexColor(RULE)
        axis.strokeWidth = 0.5
    chart.yValueAxis.visibleGrid = True
    chart.yValueAxis.gridStrokeColor = colors.HexColor("#E6E6E6")
    chart.yValueAxis.gridStrokeWidth = 0.4


def _band_chart(curves: dict[str, list[dict[str, Any]]], name: str, width: float, colors):
    """One collective's bus bandwidth from 2 GB to 16 GB: the sizes acceptance is judged at."""
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.widgets.markers import makeMarker

    points = [p for p in curves.get(name) or []
              if BAND_MIN_BYTES * 0.99 <= int(p.get("size_bytes") or 0) <= BAND_MAX_BYTES * 1.01]
    if not points:
        return None
    data = [(math.log2(p["size_bytes"]), p["busbw_gbps"]) for p in points]
    height = 165
    d = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 30, 28, width - 38, height - 52
    lp.data = [data]
    lp.joinedLines = 1
    lp.lines[0].strokeColor = colors.HexColor(SERIES_COLORS[name])
    lp.lines[0].strokeWidth = 2
    lp.lines[0].symbol = makeMarker("FilledCircle", size=4, fillColor=colors.HexColor(SERIES_COLORS[name]))
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 30.8, 34.2
    lp.xValueAxis.valueSteps = [31, 32, 33, 34]
    lp.xValueAxis.labelTextFormat = lambda v: _size(2 ** round(v)).replace(" ", "")
    lp.yValueAxis.valueMin = 0
    lp.yValueAxis.valueMax = _nice(max(y for _, y in data) * 1.18)
    lp.yValueAxis.labelTextFormat = "%d"
    _axis_style(lp, colors, font_size=6.5)
    d.add(lp)
    ymax = lp.yValueAxis.valueMax
    for x, y in data:
        px = lp.x + (x - 30.8) / (34.2 - 30.8) * lp.width
        py = lp.y + y / ymax * lp.height + 5
        d.add(String(px, py, f"{y:.0f}", fontName="Helvetica", fontSize=6.5, textAnchor="middle",
                     fillColor=colors.HexColor(INK)))
    d.add(String(2, height - 11, LABELS[name], fontName="Helvetica-Bold", fontSize=8, fillColor=colors.HexColor(INK)))
    d.add(String(lp.x + lp.width / 2, 6, "Message size", fontName="Helvetica", fontSize=6.5,
                 fillColor=colors.HexColor(MUTED), textAnchor="middle"))
    return d


def _steps_chart(points: list[dict[str, Any]], width: float, colors):
    """Training throughput (steps/s) per step."""
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String

    data = [(float(p["step"]), float(p["steps_per_s"])) for p in points if p.get("steps_per_s")]
    if len(data) < 2:
        return None
    height = 180
    d = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 40, 36, width - 50, height - 56
    lp.data = [data]
    lp.joinedLines = 1
    lp.lines[0].strokeColor = colors.HexColor(GREEN)
    lp.lines[0].strokeWidth = 1.6
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 1, max(x for x, _ in data)
    lp.xValueAxis.labelTextFormat = "%d"
    lp.yValueAxis.valueMin = 0
    # Warm-up steps are slow outliers on the low side only; the axis is scaled to the steady state.
    steady = sorted(y for _, y in data)
    lp.yValueAxis.valueMax = _nice(steady[int(len(steady) * 0.95)] * 1.15)
    lp.yValueAxis.labelTextFormat = "%.2f"
    _axis_style(lp, colors)
    d.add(lp)
    d.add(String(4, height - 12, "Steps per second", fontName="Helvetica", fontSize=7.5,
                 fillColor=colors.HexColor(MUTED)))
    d.add(String(lp.x + lp.width / 2, 8, "Training step", fontName="Helvetica", fontSize=7.5,
                 fillColor=colors.HexColor(MUTED), textAnchor="middle"))
    return d


def _nice(value: float) -> float:
    """A round axis maximum at or above *value*."""
    if value <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(value))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * exp >= value:
            return m * exp
    return 10 * exp
