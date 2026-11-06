# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The cluster forecast: when validation finishes, from how fast it has been going.

One dataset, two renderers (citizen 10), the same shape as the deployment tracker it is built
on. ``build_dataset`` takes the tracker dataset -- every node already classified and grouped
SU -> row -> rack -- and the validation progress samples ``results_history`` has recorded, and
answers three questions: how much work is left, how fast it has been closing, and when each
node, rack and SU will be done at that pace.

**Done is validation, not readiness.** A node has *passed* when both node stages passed -- or
Stage 1 alone on a cluster with no Stage 2 source (no bring-up framework on its record); a rack
when rack Stage 2 passed; an SU when every one of its racks has. A cluster with no SU map is
forecast as one group of racks, and a pool with no racks by its nodes alone (``unit_progress``). A node that passed and was
drained since is still passed here -- the tracker's remediation state is where drains are
chased. A rack, though, can only run when all of its nodes are passed *and* up, so the work a
rack is waiting on is its nodes that are not both.

**Pace is measured, never typed in.** The remaining node count is compared with a sample from
about a week earlier that covered the same scope. Scope changes -- an SU starting to validate,
one handed over -- move the count without anyone repairing anything, so a baseline whose scope
differs from today's is skipped rather than read as progress or regression.

**Two scenarios over the same open work**, both from that one measurement:

``current_pace``
    Nodes keep coming back at the measured daily rate, in no particular order, until none are
    left. A rack missing *k* nodes closes, on average, ``k/(k+1)`` of the way through.
``slowing_tail``
    Each missing node has the same chance of coming back each day, matched to the measured
    shrinkage, so the backlog halves every half-life and the hardest nodes come back last. A
    rack closes at the median time its last missing node does. Pessimistic where one fabric fix
    clears a whole held rack, since that is one repair rather than eighteen.

Each rack date adds ``RACK_RUN_DAYS`` for its Stage 1 and Stage 2 runs.

``record_sample`` is the write path: the sampler calls it hourly with a fresh tracker dataset,
filed under the cluster its snapshot was collected for (``cluster_key_of``). Rack Status
observes only the active cluster, so only the active cluster is ever sampled. Reads never write -- a read path that writes defeats its own cache
(``storage-engines.mdc``).
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

import results_history
import static_page
from deployment_tracker import UNASSIGNED_UNIT, UNPLACED_RACK, UNPLACED_UNIT

#: Days from a rack's last node passing to its rack Stage 2 verdict: one Stage 1 and one Stage 2.
RACK_RUN_DAYS = 1.0

#: How far back the pace looks for a baseline. A week holds a few repair cycles without letting
#: the fast first pass of a fresh fleet stand in for its tail.
DEFAULT_WINDOW_DAYS = 7

#: The shortest span a pace is measured over; anything shorter is noise from one repair batch.
MIN_SPAN_DAYS = 1.0

#: A baseline is like-for-like when its node scope is within this share of today's.
SCOPE_TOLERANCE = 0.03

#: How far ahead the projection is drawn.
PROJECTION_DAYS = 120

#: Open racks grouped by how many of their nodes are still missing.
RACK_BUCKETS = ((0, 0, "0"), (1, 1, "1"), (2, 3, "2–3"), (4, 9, "4–9"), (10, 10_000, "10+"))

SCENARIOS = {
    "current_pace": (
        "Repairs keep returning nodes at the measured daily rate, in no particular order, until "
        "none are left."
    ),
    "slowing_tail": (
        "The backlog keeps shrinking by the same fraction each day, as measured, so the hardest "
        "nodes come back last. Pessimistic where one fabric fix clears a whole held rack."
    ),
}


def definitions(*, stage2_available: bool, stage2_source: str, has_racks: bool, has_units: bool) -> dict[str, str]:
    """What each term on the page means *on this cluster*, written beside the code that applies it.

    Built per dataset rather than fixed, because the answer differs by cluster: one with no Stage 2
    source passes a node on Stage 1 alone, and a pool with no racks has no rack terms at all.
    """
    if stage2_available:
        node = (
            "Both node stages passed: Stage 1, single-node NCCL, and Stage 2, "
            f"{stage2_source or 'single-node LLM training'}."
        )
    else:
        node = (
            "Stage 1, single-node NCCL, passed. This cluster names no Stage 2 source (no bring-up "
            "framework on its record), so Stage 1 is the whole node ladder."
        )
    out = {"node_passed": node}
    if has_racks:
        out["rack_passed"] = "Rack Stage 2 passed: full-rack NeMo over all of the rack's nodes."
        out["missing"] = "A node a rack is waiting on: not passed, or not up in the cluster manager."
    if has_units:
        out["unit_complete"] = "Every rack in the scalable unit has passed."
    out["validating"] = "At least one of the group's nodes has run a node stage."
    out["onboarding"] = "Placed in the cluster, but none of its nodes has run a stage yet. No date until it starts."
    return out


# ---------------------------------------------------------------------------------- per unit
#
# The tracker groups nodes by scalable unit, and puts what no SU holds into one of two buckets
# of its own: racks in no SU (``UNASSIGNED_UNIT``; on a cluster with no SU map at all, that is
# every rack, labelled "All racks"), and, on a pool cluster with no racks, the pool itself
# (``UNPLACED_UNIT``, whose nodes sit in the ``UNPLACED_RACK`` placeholder). Each is forecast for
# what it is: an SU counts as an SU; the racks-in-no-SU bucket is real work but never an SU; and a
# pool is nodes only, with no rack to pass and no rack runs to wait for.


def _stage2_on(tracker: Mapping[str, Any]) -> bool:
    return bool((tracker.get("meta") or {}).get("stage2_available", True))


def unit_progress(tracker: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every group's progress from a tracker dataset, its open racks included."""
    stage2 = _stage2_on(tracker)

    def passed(node: Mapping[str, Any]) -> bool:
        return node.get("stage1") == "done" and (not stage2 or node.get("stage2") == "done")

    def ready(node: Mapping[str, Any]) -> bool:
        # An empty status means no cluster manager reports one (a pool, a demo); passing is enough.
        return passed(node) and str(node.get("status") or "up").lower() == "up"

    def ran(node: Mapping[str, Any]) -> bool:
        return node.get("stage1") not in (None, "pending") or node.get("stage2") not in (None, "pending")

    out = []
    for unit in tracker.get("units") or []:
        uid = str(unit.get("id"))
        kind = "pool" if uid == UNPLACED_UNIT else "racks" if uid == UNASSIGNED_UNIT else "su"
        held = [rack for row in unit.get("rows") or [] for rack in row.get("racks") or []]
        racks = [r for r in held if r.get("rack") != UNPLACED_RACK]
        loose = [n for r in held if r.get("rack") == UNPLACED_RACK for n in r.get("nodes") or []]
        nodes = [n for r in held for n in r.get("nodes") or []]
        if unit.get("handed_over_at"):
            phase = "handed_over"
        elif any(ran(n) for n in nodes):
            phase = "validating"
        else:
            phase = "onboarding"
        open_racks = [
            {"rack": rack["rack"], "missing": sum(1 for n in rack.get("nodes") or [] if not ready(n))}
            for rack in racks
            if rack.get("stage2") != "done"
        ]
        loose_missing = sum(1 for n in loose if not ready(n))
        out.append({
            "unit": uid,
            "label": str(unit.get("label") or uid),
            "kind": kind,
            "phase": phase,
            "handed_over_at": str(unit.get("handed_over_at") or ""),
            "nodes": len(nodes),
            "nodes_passed": sum(1 for n in nodes if passed(n)),
            "nodes_failing": sum(1 for n in nodes if "fail" in (n.get("stage1"), n.get("stage2"))),
            "racks": len(racks),
            "racks_passed": len(racks) - len(open_racks),
            "open_racks": open_racks,
            # The nodes still to come back, which is what a group's date waits on.
            "nodes_missing": sum(r["missing"] for r in open_racks) + loose_missing,
        })
    return out


def _scope(units: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    validating = [u for u in units if u["phase"] == "validating"]
    return {
        "units": sum(1 for u in validating if u["kind"] == "su"),
        "nodes": sum(u["nodes"] for u in validating),
        "nodes_passed": sum(u["nodes_passed"] for u in validating),
        "racks": sum(u["racks"] for u in validating),
        "racks_passed": sum(u["racks_passed"] for u in validating),
    }


# ---------------------------------------------------------------------------------- sampling


def cluster_key_of(identity: str) -> str:
    """The history key for a snapshot identity: ``catalog:<project>/<cluster>`` -> ``<project>/<cluster>``.

    A deployment without a catalog cluster identifies its snapshot by host or name instead, and
    that identity is the key as it stands, so such a deployment keeps a history too.
    """
    return identity.strip().removeprefix("catalog:")


def sample_rows(tracker: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The rows one progress sample stores: a unit each, open racks left out."""
    return [
        {k: u[k] for k in ("unit", "phase", "nodes", "nodes_passed", "racks", "racks_passed")}
        for u in unit_progress(tracker)
    ]


def sample_due(cluster_key: str, interval_sec: int, now: datetime | None = None) -> bool:
    """Whether the sampler should record now: never sampled, or the last one is an interval old."""
    if interval_sec <= 0 or not cluster_key:
        return False
    last = results_history.last_progress_at(cluster_key, source="sampler")
    if not last:
        return True
    now = now or datetime.now(timezone.utc)
    then = datetime.fromisoformat(last.replace("Z", "+00:00"))
    return (now - then).total_seconds() >= interval_sec


def record_sample(cluster_key: str, tracker: Mapping[str, Any], now: datetime | None = None) -> int:
    """Store one sample of this tracker dataset. The write path; nothing that reads calls it."""
    rows = sample_rows(tracker)
    if not rows:
        return 0
    return results_history.record_progress(
        cluster_key, now or datetime.now(timezone.utc), rows, source="sampler"
    )


# ---------------------------------------------------------------------------------- pace


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def measure_pace(
    series: Sequence[Mapping[str, Any]],
    now_point: Mapping[str, Any],
    now: datetime,
    *,
    window_days: float = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """How fast the remaining nodes and racks have been closing, against a like-for-like baseline.

    The baseline is the oldest sample inside the window whose node scope matches today's within
    ``SCOPE_TOLERANCE`` and that is at least ``MIN_SPAN_DAYS`` old.
    """
    scope = int(now_point["nodes"])
    remaining_now = scope - int(now_point["nodes_passed"])
    out: dict[str, Any] = {
        "enough_history": False,
        "reason": "",
        "window_days": window_days,
        "from": None,
        "to": now.isoformat(timespec="minutes"),
        "days": None,
        "remaining_from": None,
        "remaining_to": remaining_now,
        "nodes_per_day": None,
        "mean_days": None,
        "half_life_days": None,
        "racks_from": None,
        "racks_to": int(now_point["racks_passed"]),
        "racks_per_day": None,
        "baseline_source": None,
    }
    oldest = now - timedelta(days=window_days)
    newest = now - timedelta(days=MIN_SPAN_DAYS)
    like = [
        p for p in series
        if oldest <= _at(p["sampled_at"]) <= newest
        and scope and abs(int(p["nodes"]) - scope) <= SCOPE_TOLERANCE * scope
    ]
    if not like:
        out["reason"] = (
            f"No sample from {MIN_SPAN_DAYS:g} to {window_days:g} days ago covers today's "
            f"{scope:,} nodes; the pace needs one to compare with."
        )
        return out
    base = like[0]
    days = (now - _at(base["sampled_at"])).total_seconds() / 86400.0
    remaining_then = int(base["nodes"]) - int(base["nodes_passed"])
    per_day = (remaining_then - remaining_now) / days
    out.update({
        "from": _at(base["sampled_at"]).isoformat(timespec="minutes"),
        "days": round(days, 2),
        "remaining_from": remaining_then,
        "nodes_per_day": round(per_day, 2),
        "racks_from": int(base["racks_passed"]),
        "racks_per_day": round((int(now_point["racks_passed"]) - int(base["racks_passed"])) / days, 2),
        "baseline_source": base.get("source"),
    })
    if remaining_now == 0:
        out.update({"enough_history": True, "reason": "Every node in scope has passed."})
    elif per_day <= 0 or remaining_then <= remaining_now:
        out["reason"] = "The remaining work did not shrink over the window, so there is no pace to project."
    else:
        mean = days / math.log(remaining_then / remaining_now)
        out.update({
            "enough_history": True,
            "mean_days": round(mean, 2),
            "half_life_days": round(mean * math.log(2), 2),
        })
    return out


# ---------------------------------------------------------------------------------- scenarios


def _pace_days(missing: int, remaining: int, per_day: float, run_days: float = RACK_RUN_DAYS) -> float:
    """Current pace: days until a set of ``missing`` nodes is back, then the rack runs."""
    if missing <= 0:
        return run_days
    total = remaining / per_day
    return total * missing / (missing + 1) + run_days


def _tail_days(missing: int, mean_days: float, run_days: float = RACK_RUN_DAYS) -> float:
    """Slowing tail: the median time the last of ``missing`` independent repairs comes back."""
    if missing <= 0:
        return run_days
    return -mean_days * math.log(1 - 0.5 ** (1 / missing)) + run_days


def _date(now: datetime, days: float | None) -> str | None:
    if days is None or not math.isfinite(days):
        return None
    return (now + timedelta(days=days)).date().isoformat()


def _finish(has_racks: bool, has_units: bool) -> dict[str, str]:
    """How the last milestone is named, and the phrase the page's takeaway uses for it."""
    if has_racks and has_units:
        return {"label": "Every rack and SU complete", "phrase": "every rack and SU is done"}
    if has_racks:
        return {"label": "Every rack passed", "phrase": "every rack has passed"}
    return {"label": "Every node passed", "phrase": "every node has passed"}


def build_dataset(
    tracker: Mapping[str, Any],
    series: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    window_days: float = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """The forecast dataset from a tracker dataset and the recorded progress series. Pure."""
    now = now or datetime.now(timezone.utc)
    meta = dict(tracker.get("meta") or {})
    units = unit_progress(tracker)
    scope = _scope(units)
    pace = measure_pace(series, scope, now, window_days=window_days)
    remaining = scope["nodes"] - scope["nodes_passed"]
    per_day = pace["nodes_per_day"] if pace["enough_history"] and remaining else None
    mean = pace["mean_days"]
    has_racks = any(u["racks"] for u in units)
    has_units = any(u["kind"] == "su" for u in units)

    def run_days(u: Mapping[str, Any]) -> float:
        # A group's last step is its rack runs only when it has an open rack; a pool has none.
        return RACK_RUN_DAYS if u["open_racks"] else 0.0

    def pace_d(missing: int, runs: float = RACK_RUN_DAYS) -> float | None:
        return _pace_days(missing, remaining, per_day, runs) if per_day else None

    def tail_d(missing: int, runs: float = RACK_RUN_DAYS) -> float | None:
        return _tail_days(missing, mean, runs) if mean else None

    validating = [u for u in units if u["phase"] == "validating"]
    open_racks = [r for u in validating for r in u["open_racks"]]

    # ---------------------------------------------------------------- per group
    units_out = []
    for u in units:
        complete = u["phase"] == "validating" and not u["open_racks"] and not u["nodes_missing"]
        row = {**u, "complete": complete}
        if u["phase"] == "validating" and not complete:
            row["current_pace"] = _date(now, pace_d(u["nodes_missing"], run_days(u)))
            row["slowing_tail"] = _date(now, tail_d(u["nodes_missing"], run_days(u)))
        else:
            row["current_pace"] = row["slowing_tail"] = None
        units_out.append(row)

    # ---------------------------------------------------------------- milestones
    def scenario(fn) -> dict[str, float | None]:
        rack_days = sorted(fn(r["missing"]) for r in open_racks)
        group_days = [
            (u["kind"], 0.0 if not (u["open_racks"] or u["nodes_missing"]) else fn(u["nodes_missing"], run_days(u)))
            for u in validating
        ]
        su_days = sorted(d for kind, d in group_days if kind == "su")

        def racks_at(share: float) -> float | None:
            need = math.ceil(share * scope["racks"]) - scope["racks_passed"]
            return 0.0 if need <= 0 else (rack_days[need - 1] if need <= len(rack_days) else None)

        return {
            "unit_first": su_days[0] if su_days else None,
            "units_half": su_days[math.ceil(len(su_days) / 2) - 1] if su_days else None,
            "racks_half": racks_at(0.5),
            "racks_90": racks_at(0.9),
            "all": max([0.0, *rack_days, *(d for _kind, d in group_days)]),
        }

    p = scenario(pace_d) if per_day else {}
    q = scenario(tail_d) if mean else {}

    def node_share_days(share: float) -> tuple[float | None, float | None]:
        target = (1 - share) * scope["nodes"]
        if remaining <= target:
            return 0.0, 0.0
        a = (remaining - target) / per_day if per_day else None
        b = mean * math.log(remaining / target) if mean and target > 0 else None
        return a, b

    finish = _finish(has_racks, has_units)
    if not has_racks:
        # A pool finishes when its last node does: the whole backlog at the measured pace, and
        # the median return of the last of them on the tail.
        p["all"] = remaining / per_day if per_day else None
        q["all"] = _tail_days(remaining, mean, 0.0) if mean else None
    n95, n99 = node_share_days(0.95), node_share_days(0.99)
    complete_units = sum(1 for u in units_out if u["complete"] and u["kind"] == "su")
    su_validating = [u for u in validating if u["kind"] == "su"]
    plan = [
        ("unit_first", "First SU complete", has_units, complete_units > 0),
        ("racks_half", "Half of racks passed", has_racks,
         bool(scope["racks"]) and scope["racks_passed"] >= math.ceil(0.5 * scope["racks"])),
        ("nodes_95", "95% of nodes passed", True, remaining <= 0.05 * scope["nodes"]),
        ("units_half", "Half of SUs complete", has_units,
         bool(su_validating) and complete_units >= math.ceil(len(su_validating) / 2)),
        ("nodes_99", "99% of nodes passed", True, remaining <= 0.01 * scope["nodes"]),
        ("racks_90", "90% of racks passed", has_racks,
         bool(scope["racks"]) and scope["racks_passed"] >= math.ceil(0.9 * scope["racks"])),
        ("nodes_all", "Every node passed", has_racks, remaining == 0),
        ("all", finish["label"], True, bool(validating) and all(u["complete"] for u in units_out if u["phase"] == "validating")),
    ]
    dates = {
        "nodes_95": n95,
        "nodes_99": n99,
        "nodes_all": ((remaining / per_day) if per_day else None, None),
    }
    milestones_out = []
    for mid, label, applies, reached in plan:
        if not applies:
            continue
        a, b = dates.get(mid, (p.get(mid), q.get(mid)))
        milestones_out.append({
            "id": mid,
            "label": label,
            "reached": reached,
            "current_pace": None if reached else _date(now, a),
            "slowing_tail": None if reached else _date(now, b),
        })

    # ---------------------------------------------------------------- projection
    projection = []
    if remaining and (per_day or mean):
        for day in range(PROJECTION_DAYS + 1):
            projection.append({
                "date": _date(now, day),
                "current_pace": max(0.0, round(remaining - per_day * day, 1)) if per_day else None,
                "slowing_tail": round(remaining * math.exp(-day / mean), 1) if mean else None,
            })

    # ---------------------------------------------------------------- history and scope changes
    history = [
        {"at": _at(p_["sampled_at"]).isoformat(timespec="minutes"), "source": p_["source"],
         **{k: int(p_[k]) for k in ("nodes", "nodes_passed", "racks", "racks_passed")}}
        for p_ in series
    ]
    history.append({"at": now.isoformat(timespec="minutes"), "source": "now",
                    **{k: scope[k] for k in ("nodes", "nodes_passed", "racks", "racks_passed")}})
    scope_changes = []
    for prev, cur in pairwise(history):
        if prev["nodes"] and abs(cur["nodes"] - prev["nodes"]) > SCOPE_TOLERANCE * prev["nodes"]:
            scope_changes.append({"at": cur["at"], "from": prev["nodes"], "to": cur["nodes"]})

    buckets = [
        {
            "label": label,
            "min": lo,
            "max": hi,
            "racks": sum(1 for r in open_racks if lo <= r["missing"] <= hi),
            "nodes_missing": sum(r["missing"] for r in open_racks if lo <= r["missing"] <= hi),
        }
        for lo, hi, label in RACK_BUCKETS
    ] if has_racks else []

    def _phase(name: str) -> dict[str, int]:
        group = [u for u in units if u["phase"] == name]
        return {"units": len(group), "nodes": sum(u["nodes"] for u in group), "racks": sum(u["racks"] for u in group)}

    stage2_available = _stage2_on(tracker)
    return {
        "meta": {
            "cluster": meta.get("cluster", ""),
            "project": meta.get("project", ""),
            "cluster_key": meta.get("cluster_key", ""),
            "generated_at": now.isoformat(timespec="seconds"),
            "snapshot_at": meta.get("snapshot_at", ""),
            "stage2_loading": bool(meta.get("stage2_loading")),
            "stage2_available": stage2_available,
            "stage2_source": meta.get("stage2_source", ""),
            "rack_run_days": RACK_RUN_DAYS if has_racks else 0,
            "definitions": definitions(
                stage2_available=stage2_available,
                stage2_source=str(meta.get("stage2_source") or ""),
                has_racks=has_racks,
                has_units=has_units,
            ),
            "scenarios": dict(SCENARIOS),
        },
        "shape": {
            "has_racks": has_racks,
            "has_units": has_units,
            "group_label": "Scalable unit" if has_units else "Group",
            "finish": finish,
        },
        "summary": {
            **scope,
            "nodes_remaining": remaining,
            "nodes_failing": sum(u["nodes_failing"] for u in validating),
            "units_complete": complete_units,
            "onboarding": _phase("onboarding"),
            "handed_over": _phase("handed_over"),
        },
        "pace": pace,
        "milestones": milestones_out,
        "units": units_out,
        "rack_buckets": buckets,
        "projection": projection,
        "history": history,
        "scope_changes": scope_changes,
    }


# ---------------------------------------------------------------------------------- static site

#: Where ``npm run build`` writes the forecast's single-file page (``frontend/vite.forecast.config.ts``).
SITE_DIR = Path(__file__).resolve().parent.parent / "static" / "forecast"

#: The id of the element the static page reads its dataset from.
DATA_ELEMENT_ID = "forecast-data"


def render_site(dataset: Mapping[str, Any], site_dir: Path | None = None) -> str:
    """The static forecast as one HTML file, with this dataset embedded in it."""
    return static_page.render(site_dir or SITE_DIR, dataset, DATA_ELEMENT_ID, name="forecast")
