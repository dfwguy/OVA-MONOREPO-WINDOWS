# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The cluster forecast: progress samples, the pace, both scenarios, the routes and the sampler."""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

import cluster_forecast as cf
import deployment_tracker as dt
import pytest
import results_history as rh
import static_page

NOW = datetime(2026, 10, 23, 14, 37, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _history_db(tmp_path, monkeypatch):
    monkeypatch.setenv("RACK_RESULTS_DB", str(tmp_path / "results.db"))


# ---------------------------------------------------------------- a small floor


def _n(name, s1="done", s2="done", status="up"):
    return {"node": name, "stage1": s1, "stage2": s2, "status": status}


def _rack(rack, nodes, stage2="pending"):
    return {"rack": rack, "stage2": stage2, "nodes": nodes}


def _unit(uid, racks, handed=""):
    return {"id": uid, "label": uid.upper(), "handed_over_at": handed, "rows": [{"key": "r", "racks": racks}]}


@pytest.fixture
def tracker():
    """SU20 complete; SU21 one rack done, one ready, one held; SU1 never run; SU19 handed over."""
    return {
        "meta": {"cluster": "NC", "snapshot_at": "2026-10-23T14:36:00Z"},
        "units": [
            _unit("su20", [_rack("V1", [_n("a"), _n("b")], "done")]),
            _unit("su21", [
                _rack("Q1", [_n("c"), _n("d")], "done"),
                _rack("Q2", [_n("e"), _n("f")]),  # every node passed and up: ready to run
                _rack("Q3", [_n("g", "fail", "done"), _n("h", status="down"), _n("i", "pending", "pending")]),
            ]),
            _unit("su1", [_rack("A2", [_n("j", "pending", "pending", "down"), _n("k", "pending", "pending", "down")])]),
            _unit("su19", [_rack("U19", [_n("l")], "done")], handed="2026-10-17"),
        ],
    }


# ---------------------------------------------------------------- the samples table


def test_progress_rows_are_stored_per_unit_and_a_resample_replaces_them():
    rows = [
        {"unit": "su20", "phase": "validating", "nodes": 126, "nodes_passed": 120, "racks": 7, "racks_passed": 5},
        {"unit": "su1", "phase": "onboarding", "nodes": 126, "nodes_passed": 0, "racks": 7, "racks_passed": 0},
    ]
    assert rh.record_progress("p/c", "2026-10-23T14:37:12Z", rows, source="sampler") == 2
    rows[0]["nodes_passed"] = 121
    rh.record_progress("p/c", "2026-10-23T14:37:50Z", rows, source="sampler")  # same minute
    series = rh.progress_series("p/c")
    # Only validating units count, and the second write replaced the first.
    assert series == [{
        "sampled_at": "2026-10-23T14:37:00Z", "source": "sampler", "units": 1,
        "nodes": 126, "nodes_passed": 121, "racks": 7, "racks_passed": 5,
    }]
    assert rh.last_progress_at("p/c", source="sampler") == "2026-10-23T14:37:00Z"
    assert rh.last_progress_at("p/c", source="import") is None
    assert {r["unit"] for r in rh.progress_units("p/c", "2026-10-23T14:37:00Z")} == {"su1", "su20"}
    # Another cluster's history is its own.
    assert rh.progress_series("other/c") == []


def test_progress_rows_refuse_what_they_cannot_mean():
    ok = {"unit": "su20", "phase": "validating", "nodes": 1, "nodes_passed": 1, "racks": 1, "racks_passed": 1}
    with pytest.raises(rh.ResultsHistoryError):
        rh.record_progress("p/c", "last tuesday", [ok], source="sampler")
    with pytest.raises(rh.ResultsHistoryError):
        rh.record_progress("p/c", NOW, [{**ok, "phase": "done"}], source="sampler")
    with pytest.raises(rh.ResultsHistoryError):
        rh.record_progress("p/c", NOW, [ok], source="guess")
    with pytest.raises(rh.ResultsHistoryError):
        rh.record_progress("", NOW, [ok], source="sampler")


# ---------------------------------------------------------------- per unit


def test_units_are_phased_and_racks_wait_on_nodes_not_passed_or_not_up(tracker):
    units = {u["unit"]: u for u in cf.unit_progress(tracker)}
    assert set(units) == {"su20", "su21", "su1", "su19"}
    assert {u["kind"] for u in units.values()} == {"su"}
    assert units["su20"]["phase"] == "validating" and units["su20"]["open_racks"] == []
    assert units["su1"]["phase"] == "onboarding"
    assert units["su19"]["phase"] == "handed_over"
    su21 = units["su21"]
    assert su21["nodes"] == 7 and su21["nodes_passed"] == 5 and su21["nodes_failing"] == 1
    assert su21["racks_passed"] == 1
    # h passed but is down, g failed a stage, i never ran: all three hold Q3.
    assert su21["open_racks"] == [{"rack": "Q2", "missing": 0}, {"rack": "Q3", "missing": 3}]
    assert su21["nodes_missing"] == 3


def test_a_node_with_no_manager_status_is_ready_once_passed():
    units = cf.unit_progress({"units": [_unit("pool", [_rack("P1", [_n("a", status="")])])]})
    assert units[0]["open_racks"] == [{"rack": "P1", "missing": 0}]


def test_a_sample_is_one_row_per_unit_without_the_racks(tracker):
    rows = cf.sample_rows(tracker)
    assert [r["unit"] for r in rows] == ["su20", "su21", "su1", "su19"]
    assert all(set(r) == {"unit", "phase", "nodes", "nodes_passed", "racks", "racks_passed"} for r in rows)
    assert cf.record_sample("p/c", tracker, now=NOW) == 4
    assert rh.progress_series("p/c")[0]["nodes"] == 9  # su20 + su21, the validating units


def test_a_sample_is_due_when_none_exists_or_the_last_is_an_interval_old(tracker):
    assert cf.sample_due("p/c", 3600, now=NOW)
    cf.record_sample("p/c", tracker, now=NOW)
    assert not cf.sample_due("p/c", 3600, now=NOW + timedelta(minutes=59))
    assert cf.sample_due("p/c", 3600, now=NOW + timedelta(minutes=61))
    assert not cf.sample_due("p/c", 0, now=NOW + timedelta(days=1))  # 0 switches sampling off
    # An import is history, not a sample: it never stops the sampler taking one.
    rh.record_progress("q/c", NOW, [{"unit": "*", "phase": "validating", "nodes": 1, "nodes_passed": 0,
                                     "racks": 1, "racks_passed": 0}], source="import")
    assert cf.sample_due("q/c", 3600, now=NOW)


# ---------------------------------------------------------------- the pace


def _point(days_ago, nodes, passed, racks=121, racks_passed=31, source="import"):
    at = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:00Z")
    return {"sampled_at": at, "source": source, "nodes": nodes, "nodes_passed": passed,
            "racks": racks, "racks_passed": racks_passed}


NOW_POINT = {"nodes": 2178, "nodes_passed": 1853, "racks": 121, "racks_passed": 47}


def test_the_pace_compares_with_the_oldest_like_for_like_sample_in_the_window():
    series = [
        _point(9, 2178, 1600),        # outside the window
        _point(6.94, 2286, 1700),     # SU19 still in scope: a different fleet
        _point(6.94 - 0.01, 2178, 1694),
        _point(3, 2178, 1800),
        _point(0.5, 2178, 1850),      # too recent to measure against
    ]
    pace = cf.measure_pace(series, NOW_POINT, NOW)
    assert pace["enough_history"] and pace["remaining_from"] == 484 and pace["remaining_to"] == 325
    assert pace["nodes_per_day"] == pytest.approx(22.9, abs=0.1)
    assert pace["half_life_days"] == pytest.approx(12.1, abs=0.1)
    assert pace["racks_per_day"] == pytest.approx(16 / 6.93, abs=0.01)
    assert pace["baseline_source"] == "import"


def test_no_pace_without_a_comparable_sample_or_without_progress():
    assert not cf.measure_pace([], NOW_POINT, NOW)["enough_history"]
    other = cf.measure_pace([_point(3, 2682, 1700)], NOW_POINT, NOW)
    assert not other["enough_history"] and "2,178 nodes" in other["reason"]
    stuck = cf.measure_pace([_point(3, 2178, 1900)], NOW_POINT, NOW)
    assert not stuck["enough_history"] and "did not shrink" in stuck["reason"]


def test_both_scenarios_follow_their_formulas():
    # Current pace: a rack missing k of R open nodes closes k/(k+1) of the way, plus its runs.
    assert cf._pace_days(1, 100, 10) == pytest.approx(10 * 1 / 2 + cf.RACK_RUN_DAYS)
    assert cf._pace_days(0, 100, 10) == cf.RACK_RUN_DAYS
    # Slowing tail: one missing node returns at its median, mean * ln 2.
    assert cf._tail_days(1, 17.4) == pytest.approx(17.4 * math.log(2) + cf.RACK_RUN_DAYS)
    # More missing nodes take longer: the last of eighteen is well past the first.
    assert cf._tail_days(18, 17.4) > cf._tail_days(3, 17.4) > cf._tail_days(1, 17.4)


# ---------------------------------------------------------------- the dataset


def test_the_dataset_dates_units_racks_and_milestones(tracker):
    series = [_point(5, 9, 3, racks=4, racks_passed=1, source="sampler")]
    d = cf.build_dataset(tracker, series, now=NOW)
    s = d["summary"]
    assert (s["nodes"], s["nodes_passed"], s["nodes_remaining"]) == (9, 7, 2)
    assert (s["racks"], s["racks_passed"], s["units"], s["units_complete"]) == (4, 2, 2, 1)
    assert s["onboarding"] == {"units": 1, "nodes": 2, "racks": 1}
    assert s["handed_over"] == {"units": 1, "nodes": 1, "racks": 1}

    units = {u["unit"]: u for u in d["units"]}
    assert units["su20"]["complete"] and units["su20"]["current_pace"] is None
    assert units["su21"]["current_pace"] and units["su21"]["slowing_tail"]
    assert units["su1"]["current_pace"] is None and units["su19"]["current_pace"] is None

    by_id = {m["id"]: m for m in d["milestones"]}
    assert by_id["unit_first"]["reached"] and by_id["unit_first"]["current_pace"] is None
    assert by_id["racks_half"]["reached"]  # 2 of 4
    assert not by_id["all"]["reached"] and by_id["all"]["current_pace"] == units["su21"]["current_pace"]
    assert by_id["nodes_all"]["slowing_tail"] is None  # the tail never reaches zero
    assert d["projection"][0] == {"date": "2026-10-23", "current_pace": 2.0, "slowing_tail": 2.0}
    assert d["history"][-1]["source"] == "now"
    assert d["rack_buckets"][0] == {"label": "0", "min": 0, "max": 0, "racks": 1, "nodes_missing": 0}
    assert set(d["meta"]["definitions"]) >= {"node_passed", "rack_passed", "unit_complete"}
    assert d["shape"] == {
        "has_racks": True, "has_units": True, "group_label": "Scalable unit",
        "finish": {"label": "Every rack and SU complete", "phrase": "every rack and SU is done"},
    }


def test_without_a_pace_nothing_is_dated(tracker):
    d = cf.build_dataset(tracker, [], now=NOW)
    assert not d["pace"]["enough_history"]
    assert all(m["current_pace"] is None and m["slowing_tail"] is None for m in d["milestones"])
    assert d["projection"] == []
    assert {u["unit"]: u["current_pace"] for u in d["units"]}["su21"] is None


def test_a_jump_in_scope_is_published_as_one():
    tracker = {"units": [_unit("su20", [_rack("V1", [_n("a"), _n("b", "fail")])])]}
    d = cf.build_dataset(tracker, [_point(2, 1000, 900, source="sampler")], now=NOW)
    assert d["scope_changes"] == [{"at": NOW.isoformat(timespec="minutes"), "from": 1000, "to": 2}]


def test_the_tracker_now_says_whether_a_node_is_up():
    payload = {
        "nodes": [{"id": "gpu1", "rack": "V20", "status": "down", "scheduler_status": "idle"}],
        "rows": [{"rack": "V20"}],
    }
    data = dt.build_dataset(payload, {"nodes": []})
    assert data["units"][0]["rows"][0]["racks"][0]["nodes"][0]["status"] == "down"


# ---------------------------------------------------------------- the static page


def test_the_dataset_is_embedded_as_data_never_markup(tmp_path):
    (tmp_path / "index.html").write_text(f"<html>{static_page.data_element(cf.DATA_ELEMENT_ID)}</html>")
    html = cf.render_site({"meta": {"cluster": "</script><b>x"}}, site_dir=tmp_path)
    assert "</script><b>" not in html and "<\\/script>" in html
    with pytest.raises(static_page.SiteBundleMissing):
        cf.render_site({}, site_dir=tmp_path / "missing")
    (tmp_path / "index.html").write_text("<html></html>")
    with pytest.raises(static_page.SiteBundleMissing):
        cf.render_site({}, site_dir=tmp_path)


def test_the_built_page_is_a_single_file():
    """When the frontend has been built, the page must stand alone. Skipped where it is not built."""
    index = cf.SITE_DIR / "index.html"
    if not index.is_file():
        pytest.skip("forecast page not built in this tree")
    html = index.read_text(encoding="utf-8")
    assert static_page.data_element(cf.DATA_ELEMENT_ID) in html
    assert 'src="./assets' not in html and 'href="./assets' not in html
    assert [p.name for p in cf.SITE_DIR.iterdir()] == ["index.html"]


# ---------------------------------------------------------------- routes and sampler


class _Snap:
    def __init__(self, payload, *, cluster_id="catalog:p/c", age=0):
        self.payload = payload
        self.cluster_id = cluster_id
        self.last_success_at = time.time() - age


def _quiet(monkeypatch, route, payload, *, key="p/c", stage2_loading=False, age=0, stage2_available=True):
    from api import _tracker_inputs as inputs

    snap = _Snap(payload, cluster_id=f"catalog:{key}" if key else "", age=age)
    monkeypatch.setattr(inputs, "get_cluster_snapshot", lambda _d, wait=False: snap)
    monkeypatch.setattr(inputs, "_ensure_rack_status_background_thread", lambda: None)
    monkeypatch.setattr(inputs, "_start_cmsh_rack_list_warm_thread", lambda: None)
    monkeypatch.setattr(inputs, "_merge_naming_into_status_payload", lambda _p: None)
    monkeypatch.setattr(inputs, "active_cluster_name", lambda: "NC")
    monkeypatch.setattr(route.rack_status_engine, "cluster_snapshot_identity", lambda: f"catalog:{key}" if key else "")
    monkeypatch.setattr(route, "_resolve_log_dir", lambda _raw: PurePosixPath("/logs"))
    monkeypatch.setattr(
        inputs.node_stages, "node_stages",
        lambda pairs, logs, wait_for_bringup=False: {
            "stage2_loading": stage2_loading,
            "stage2_available": stage2_available,
            "nodes": [{"node": n, "stage1": {"state": "done"}, "stage2": {"state": "done"}} for n, _r in pairs],
        },
    )


_FLOOR = {
    "nodes": [{"id": "gpu1", "rack": "V20", "status": "up", "scheduler_status": "idle"}],
    "rows": [{"rack": "V20", "stage2": "pending"}],
    "scalable_units": [{"id": "su20", "label": "SU20", "racks": ["V20"]}],
}


def test_route_serves_the_forecast_with_its_sampling(monkeypatch):
    import app as app_module
    from api import cluster_forecast as route

    _quiet(monkeypatch, route, _FLOOR)
    route._last_check.clear()
    route._last_check.update({"at": "2026-10-23T15:00:00+00:00", "outcome": "Not due yet."})
    r = app_module.app.test_client().get("/api/cluster-forecast")
    if r.status_code in (401, 403):
        pytest.skip("route requires a session in this app configuration")
    body = r.get_json()
    assert r.status_code == 200 and body["ok"]
    assert body["summary"]["nodes_passed"] == 1 and body["summary"]["racks_passed"] == 0
    assert body["meta"]["cluster_key"] == "p/c"
    sampling = body["meta"]["sampling"]
    assert sampling["interval_sec"] == route.DEFAULT_SAMPLE_INTERVAL_SEC
    assert sampling["last_check"]["outcome"] == "Not due yet."
    assert sampling["observes"] == "active cluster only"


def test_route_says_retry_while_the_inventory_loads(monkeypatch):
    import app as app_module
    from api import cluster_forecast as route

    _quiet(monkeypatch, route, {})
    r = app_module.app.test_client().get("/api/cluster-forecast")
    if r.status_code in (401, 403):
        pytest.skip("route requires a session in this app configuration")
    assert r.status_code == 503 and r.headers.get("Retry-After") == "30"


def test_site_route_serves_the_page_as_a_download(monkeypatch, tmp_path):
    import app as app_module
    from api import cluster_forecast as route

    (tmp_path / "index.html").write_text(f"<html>{static_page.data_element(cf.DATA_ELEMENT_ID)}</html>")
    monkeypatch.setattr(cf, "SITE_DIR", tmp_path)
    _quiet(monkeypatch, route, _FLOOR)
    r = app_module.app.test_client().get("/api/cluster-forecast/site.html")
    if r.status_code in (401, 403):
        pytest.skip("route requires a session in this app configuration")
    assert r.status_code == 200 and r.mimetype == "text/html"
    assert "cluster-forecast.html" in r.headers["Content-Disposition"]
    assert "su20" in r.get_data(as_text=True)


@pytest.fixture
def live(monkeypatch):
    from api import cluster_forecast as route

    monkeypatch.setenv("RACK_STATUS_DEMO", "0")
    monkeypatch.setattr(route.host_exec, "cluster_reachable", lambda force=False: True)
    return route


def test_the_sampler_files_a_sample_under_the_snapshots_cluster_when_due(monkeypatch, live):
    _quiet(monkeypatch, live, _FLOOR)
    assert live.sample_once() == "Recorded 1 group(s)."
    assert live.sample_once() == "Not due yet."
    assert rh.progress_series("p/c")[0]["nodes_passed"] == 1


def test_the_sampler_says_why_it_skips(monkeypatch, live):
    # Stage 2 still loading: a sample now would record a regression that never happened.
    _quiet(monkeypatch, live, _FLOOR, stage2_loading=True)
    assert live.sample_once().startswith("Skipped: Stage 2 verdicts are still loading")
    # A snapshot nobody has refreshed lately is not today's fleet.
    _quiet(monkeypatch, live, _FLOOR, age=3600)
    assert live.sample_once() == "Skipped: the cluster snapshot is stale (60 min old), so the counts would not be today's."
    # The active cluster changed between choosing whose sample is due and reading the snapshot.
    _quiet(monkeypatch, live, _FLOOR)
    monkeypatch.setattr(live.rack_status_engine, "cluster_snapshot_identity", lambda: "catalog:p/other")
    assert live.sample_once().startswith("Skipped: the active cluster changed")
    assert rh.progress_series("p/c") == [] and rh.progress_series("p/other") == []
    # Unreachable, and every skip lands in the published last check.
    _quiet(monkeypatch, live, _FLOOR)
    monkeypatch.setattr(live.host_exec, "cluster_reachable", lambda force=False: False)
    live._check()
    assert live._last_check["outcome"] == "Skipped: the cluster is unreachable from Rack Status."


def test_the_sampler_samples_a_cluster_with_no_stage2_source(monkeypatch, live):
    _quiet(monkeypatch, live, _FLOOR, stage2_available=False)
    assert live.sample_once() == "Recorded 1 group(s)."


def test_the_sampler_stays_quiet_where_it_has_nothing_to_measure(monkeypatch):
    from api import cluster_forecast as route

    _quiet(monkeypatch, route, _FLOOR, key="")
    monkeypatch.setenv("RACK_STATUS_DEMO", "1")
    assert route.sample_once().startswith("Sampling is off")
    monkeypatch.setenv("RACK_STATUS_DEMO", "0")
    assert route.sample_once() == "No cluster identity to file a sample under."
    monkeypatch.setenv("RACK_FORECAST_SAMPLE_INTERVAL_SEC", "0")
    assert route.sample_once().startswith("Sampling is off")
    monkeypatch.setenv("RACK_FORECAST_SAMPLE_INTERVAL_SEC", "60")
    assert route.sample_interval_sec() == 300  # floored


def test_a_snapshot_identity_becomes_a_history_key():
    assert cf.cluster_key_of("catalog:default/default") == "default/default"
    # A deployment with no catalog cluster names its snapshot by host, and keeps a history too.
    assert cf.cluster_key_of("10.10.20.21") == "10.10.20.21"


# ---------------------------------------------------------------- other cluster shapes


def test_no_su_map_is_one_group_of_racks_never_counted_as_an_su():
    tracker = {"units": [{
        "id": dt.UNASSIGNED_UNIT, "label": "All racks", "handed_over_at": "",
        "rows": [{"racks": [_rack("R1", [_n("a"), _n("b")], "done"), _rack("R2", [_n("c", "fail")])]}],
    }]}
    d = cf.build_dataset(tracker, [_point(3, 3, 1, racks=2, racks_passed=0, source="sampler")], now=NOW)
    assert d["units"][0]["kind"] == "racks" and d["units"][0]["label"] == "All racks"
    assert d["shape"]["has_units"] is False and d["shape"]["group_label"] == "Group"
    assert d["summary"]["units"] == 0 and d["summary"]["racks"] == 2
    ids = [m["id"] for m in d["milestones"]]
    assert "unit_first" not in ids and "units_half" not in ids and "racks_half" in ids
    assert d["shape"]["finish"]["label"] == "Every rack passed"
    assert "unit_complete" not in d["meta"]["definitions"]


def test_a_pool_is_forecast_by_its_nodes_alone():
    tracker = {"units": [{
        "id": dt.UNPLACED_UNIT, "label": "Pool", "handed_over_at": "",
        "rows": [{"racks": [_rack(dt.UNPLACED_RACK, [_n("a"), _n("b", "fail"), _n("c", "pending", "pending")])]}],
    }]}
    d = cf.build_dataset(tracker, [_point(3, 3, 0, racks=0, racks_passed=0, source="sampler")], now=NOW)
    pool = d["units"][0]
    assert pool["kind"] == "pool" and pool["racks"] == 0 and pool["open_racks"] == []
    assert pool["nodes_missing"] == 2 and not pool["complete"]
    assert d["shape"]["has_racks"] is False and d["rack_buckets"] == []
    assert d["meta"]["rack_run_days"] == 0
    ids = [m["id"] for m in d["milestones"]]
    assert ids == ["nodes_95", "nodes_99", "all"]
    finish = next(m for m in d["milestones"] if m["id"] == "all")
    assert finish["label"] == "Every node passed"
    # The pool finishes with its last node: the whole backlog at the measured pace, no rack runs.
    per_day = d["pace"]["nodes_per_day"]
    assert finish["current_pace"] == (NOW + timedelta(days=2 / per_day)).date().isoformat()
    assert pool["current_pace"] is not None


def test_without_a_stage2_source_stage1_is_the_ladder(tracker):
    tracker["meta"]["stage2_available"] = False
    for unit in tracker["units"]:
        for row in unit["rows"]:
            for rack in row["racks"]:
                for node in rack["nodes"]:
                    node["stage2"] = "pending"
    units = {u["unit"]: u for u in cf.unit_progress(tracker)}
    assert units["su20"]["nodes_passed"] == 2
    d = cf.build_dataset(tracker, [], now=NOW)
    assert "Stage 1 is the whole node ladder" in d["meta"]["definitions"]["node_passed"]
    assert d["meta"]["stage2_available"] is False


# ---------------------------------------------------------------- import


def test_history_imports_from_a_csv_and_a_dry_run_writes_nothing(tmp_path, capsys):
    import cli

    csv_path = tmp_path / "history.csv"
    csv_path.write_text(
        "sampled_at,nodes,nodes_passed,racks,racks_passed\n"
        "2026-10-16T15:58:00Z,2178,1694,121,31\n"
        "2026-10-19T15:58:00Z,2178,1779,121,38\n"
    )
    assert cli.main(["import-progress", str(csv_path), "--cluster-key", "p/c", "--dry-run"]) == 0
    assert rh.progress_series("p/c") == []
    assert cli.main(["import-progress", str(csv_path), "--cluster-key", "p/c"]) == 0
    series = rh.progress_series("p/c")
    assert [(p["source"], p["nodes_passed"]) for p in series] == [("import", 1694), ("import", 1779)]
    assert "2 sample(s) for p/c" in capsys.readouterr().out

    bad = tmp_path / "bad.csv"
    bad.write_text("sampled_at,nodes\n2026-10-16T15:58:00Z,1\n")
    assert cli.main(["import-progress", str(bad), "--cluster-key", "p/c"]) == cli.EXIT_FAULT
