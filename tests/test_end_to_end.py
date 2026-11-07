"""The special agent's real output, read the way Checkmk reads it.

The other check tests build sections by hand. These run agent_oposs_pbs's
main() against the sample PBS of tests/fixtures/fake_pbs.py, split
its stdout into piggyback hosts and `sep(0)` sections as the Checkmk fetcher
does, and feed the string tables through every parse, discovery and check
function. A change to the agent's output format that the check does not
follow fails here.
"""

import importlib.util
import json
import re
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
from cmk.agent_based.v2 import HostLabel, Metric, Result, Service, State
from conftest import load_module

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from fake_pbs import DAY, FakePbs, sample_routes, task_route

m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks_e2e")
g = load_module("graphing/oposs_pbs.py", "oposs_pbs_graphing_e2e")

AGENT = (Path(__file__).resolve().parent.parent
         / "local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/agent_oposs_pbs")
NOW = 1_000_000
DEFINED_METRICS = {v.name for k, v in vars(g).items() if k.startswith("metric_")}

SECTIONS = {
    "oposs_pbs_server": m.agent_section_oposs_pbs_server,
    "oposs_pbs_datastore": m.agent_section_oposs_pbs_datastore,
    "oposs_pbs_jobs": m.agent_section_oposs_pbs_jobs,
    "oposs_pbs_backup": m.agent_section_oposs_pbs_backup,
    "oposs_pbs_backup_rollup": m.agent_section_oposs_pbs_backup_rollup,
}


def split_agent_output(text):
    """{host: {section: string_table}}, "" being the PBS host itself.

    `<<<<name>>>>` opens a piggyback block, `<<<<>>>>` returns to the host.
    With sep(0) every line is a single cell.
    """
    hosts = {"": {}}
    host, section = "", None
    for line in text.splitlines():
        pig = re.fullmatch(r"<<<<(.*)>>>>", line)
        if pig:
            host, section = pig.group(1), None
            hosts.setdefault(host, {})
            continue
        sec = re.fullmatch(r"<<<([^:>]+)(:sep\(0\))?>>>", line)
        if sec:
            assert sec.group(2), f"section {sec.group(1)} lacks sep(0); JSON would be split"
            section = sec.group(1)
            hosts[host].setdefault(section, [])
            continue
        assert section is not None, f"data outside a section: {line!r}"
        hosts[host][section].append([line])
    return hosts


def _load_agent():
    loader = SourceFileLoader("agent_oposs_pbs_e2e", str(AGENT))
    spec = importlib.util.spec_from_loader("agent_oposs_pbs_e2e", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_oposs_pbs_e2e"] = mod
    loader.exec_module(mod)
    return mod


agent = _load_agent()


@pytest.fixture
def run_agent(tmp_path, monkeypatch, capsys):
    """Run the agent against a FakePbs that answers the task list like PBS.

    Not --test-file: that mode serves each path from a static JSON value and
    ignores the query, so every typefilter would get every task.
    """
    def run(routes, *extra):
        routes = dict(routes)
        tasks = routes.get("/nodes/localhost/tasks")
        if isinstance(tasks, list):
            routes["/nodes/localhost/tasks"] = task_route(tasks)
        monkeypatch.setattr(agent, "_make_client", lambda _args: FakePbs(routes))
        rc = agent.main(["pbs.example", "--token-id", "root@pam!mon",
                         "--token-secret", "x", "--cache-dir", str(tmp_path / "cache"),
                         "--now", str(NOW), *extra])
        assert rc == 0
        return split_agent_output(capsys.readouterr().out)
    return run


def parsed(host_sections, name):
    return SECTIONS[name].parse_function(host_sections[name])


@pytest.fixture
def at_now(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)


@pytest.fixture
def output(run_agent):
    return run_agent(sample_routes(NOW))


def _results(res):
    return [r for r in res if isinstance(r, Result)]


def _metrics(res):
    return {r.name: r.value for r in res if isinstance(r, Metric)}


def test_agent_output_has_the_pbs_host_and_one_piggyback_guest(output):
    assert set(output) == {"", "web01"}
    assert set(output[""]) == {"oposs_pbs_server", "oposs_pbs_datastore",
                               "oposs_pbs_jobs", "oposs_pbs_backup_rollup"}
    assert set(output["web01"]) == {"oposs_pbs_backup"}


def test_server_service_from_agent_output(output):
    sec = parsed(output[""], "oposs_pbs_server")
    assert list(m.discover_oposs_pbs_server(sec)) == [Service()]
    res = list(m.check_oposs_pbs_server({"unmapped_state": "warn"}, sec))
    assert [r.state for r in _results(res)] == [State.OK]
    assert res[0].summary == "Version 3.2.7, node localhost, 1 datastore(s)"


def test_datastore_service_from_agent_output(output, at_now):
    sec = parsed(output[""], "oposs_pbs_datastore")
    assert [s.item for s in m.discover_oposs_pbs_datastore(sec)] == ["main"]
    res = list(m.check_oposs_pbs_datastore(
        "main", m.check_plugin_oposs_pbs_datastore.check_default_parameters, sec))
    assert State.worst(*(r.state for r in _results(res))) is State.OK
    metrics = _metrics(res)
    assert metrics["oposs_pbs_datastore_used_pct"] == 25.0
    assert metrics["oposs_pbs_datastore_size"] == 1000.0
    assert metrics["oposs_pbs_dedup_factor"] == 4.0
    assert metrics["oposs_pbs_gc_age"] == 3500.0
    assert metrics["oposs_pbs_backup_count"] == 7.0


def test_datastore_usage_levels_from_agent_output(run_agent, at_now):
    routes = sample_routes(NOW)
    params = m.check_plugin_oposs_pbs_datastore.check_default_parameters
    for used, want in ((800, State.WARN), (900, State.CRIT), (799, State.OK)):
        routes["/admin/datastore/main/status"].update(used=used, avail=1000 - used)
        sec = parsed(run_agent(routes)[""], "oposs_pbs_datastore")
        usage = next(iter(m.check_oposs_pbs_datastore("main", params, sec)))
        assert usage.state is want, used


@pytest.mark.parametrize(("plugin", "item", "metric", "age"), [
    ("sync", "r1:rs", "oposs_pbs_sync_age", 100.0),
    ("verify", "main", "oposs_pbs_verify_age", 300.0),
    ("prune", "main", "oposs_pbs_prune_age", 450.0),
])
def test_job_services_from_agent_output(output, at_now, plugin, item, metric, age):
    sec = parsed(output[""], "oposs_pbs_jobs")
    discover = getattr(m, f"discover_oposs_pbs_{plugin}")
    check = getattr(m, f"check_oposs_pbs_{plugin}")
    assert [s.item for s in discover(sec)] == [item]
    res = list(check(item, {"age_levels": ("fixed", (200.0, 400.0))}, sec))
    assert _metrics(res) == {metric: age}
    want = State.OK if age < 200 else State.WARN if age < 400 else State.CRIT
    assert _results(res)[0].state is want


def test_piggyback_backup_service_from_agent_output(output, at_now):
    sec = parsed(output["web01"], "oposs_pbs_backup")
    assert list(m.host_label_oposs_pbs_backup(sec)) == [
        HostLabel("oposs_pbs/backup", "yes"), HostLabel("oposs_pbs/datastore", "main")]
    items = [s.item for s in m.discover_oposs_pbs_backup(sec)]
    assert items == ["main vm/100"]
    res = list(m.check_oposs_pbs_backup(
        "main vm/100", m.check_plugin_oposs_pbs_backup.check_default_parameters, sec))
    assert State.worst(*(r.state for r in _results(res))) is State.OK
    metrics = _metrics(res)
    assert metrics["oposs_pbs_backup_age"] == 100.0
    assert metrics["oposs_pbs_backup_size"] == 41_000_000_000.0
    assert any("verified OK" in r.details for r in _results(res))


def test_stale_piggyback_backup_goes_warn_then_crit(run_agent, monkeypatch):
    out = run_agent(sample_routes(NOW))
    sec = parsed(out["web01"], "oposs_pbs_backup")
    params = m.check_plugin_oposs_pbs_backup.check_default_parameters
    last = NOW - 100
    # Two snapshots one day apart: the cadence is one day.
    for age, want in ((DAY, State.OK), (2 * DAY, State.WARN), (3 * DAY, State.CRIT)):
        monkeypatch.setattr(m.time, "time", lambda age=age: last + age)
        res = list(m.check_oposs_pbs_backup("main vm/100", params, sec))
        assert res[0].state is want, age


def test_rollup_service_from_agent_output(output, at_now):
    sec = parsed(output[""], "oposs_pbs_backup_rollup")
    assert list(m.discover_oposs_pbs_backups(sec)) == [Service()]
    res = list(m.check_oposs_pbs_backups(
        m.check_plugin_oposs_pbs_backups.check_default_parameters, sec))
    assert _results(res)[0].state is State.OK
    assert _results(res)[0].summary == "1 backups OK"
    assert _metrics(res) == {"oposs_pbs_backups_total": 1.0,
                             "oposs_pbs_backups_unhealthy": 0.0}


def test_unreachable_pbs_gives_a_crit_server_service_and_nothing_else(run_agent):
    """FakePbs raises for every path an empty route table lacks."""
    out = run_agent({})
    assert set(out) == {""}
    assert set(out[""]) == {"oposs_pbs_server"}
    sec = parsed(out[""], "oposs_pbs_server")
    assert list(m.discover_oposs_pbs_server(sec)) == [Service()]
    res = list(m.check_oposs_pbs_server({"unmapped_state": "warn"}, sec))
    assert [r.state for r in res] == [State.CRIT]
    assert res[0].summary.startswith("PBS API unreachable: ")


@pytest.mark.parametrize("table", [[], [[""]], [["not json"]], [["{\"a\":"]]])
def test_garbage_sections_parse_to_nothing_and_discover_nothing(table):
    assert m.parse_json(table) == {}
    assert m.parse_rollup(table) == []
    assert list(m.discover_oposs_pbs_server(m.parse_json(table))) == []
    assert list(m.discover_oposs_pbs_datastore(m.parse_json(table))) == []
    assert list(m.discover_oposs_pbs_sync(m.parse_json(table))) == []
    assert list(m.discover_oposs_pbs_backups(m.parse_rollup(table))) == []


def test_garbage_lines_in_the_backup_section_are_skipped():
    good = json.dumps({"datastore": "main", "backup_type": "ct", "backup_id": "7"})
    sec = m.parse_backup([["garbage"], [], [good], ["{"]])
    assert [s.item for s in m.discover_oposs_pbs_backup(sec)] == ["main ct/7"]


def test_server_section_without_data_is_unknown():
    res = list(m.check_oposs_pbs_server({"unmapped_state": "warn"}, {}))
    assert res[0].state is State.UNKNOWN


def test_vanished_items_produce_no_result(output):
    """Checkmk turns an empty check result into "item not found"."""
    params = {"age_levels": ("no_levels", None)}
    assert list(m.check_oposs_pbs_datastore(
        "gone", m.check_plugin_oposs_pbs_datastore.check_default_parameters,
        parsed(output[""], "oposs_pbs_datastore"))) == []
    assert list(m.check_oposs_pbs_sync("gone", params,
                                       parsed(output[""], "oposs_pbs_jobs"))) == []
    assert list(m.check_oposs_pbs_backup(
        "gone", m.check_plugin_oposs_pbs_backup.check_default_parameters,
        parsed(output["web01"], "oposs_pbs_backup"))) == []


def _all_metric_names(output):
    names = set()
    host = output[""]
    names |= set(_metrics(m.check_oposs_pbs_datastore(
        "main", m.check_plugin_oposs_pbs_datastore.check_default_parameters,
        parsed(host, "oposs_pbs_datastore"))))
    jobs = parsed(host, "oposs_pbs_jobs")
    names |= set(_metrics(m.check_oposs_pbs_sync("r1:rs", {}, jobs)))
    names |= set(_metrics(m.check_oposs_pbs_verify("main", {}, jobs)))
    names |= set(_metrics(m.check_oposs_pbs_prune("main", {}, jobs)))
    names |= set(_metrics(m.check_oposs_pbs_backup(
        "main vm/100", m.check_plugin_oposs_pbs_backup.check_default_parameters,
        parsed(output["web01"], "oposs_pbs_backup"))))
    names |= set(_metrics(m.check_oposs_pbs_backups(
        m.check_plugin_oposs_pbs_backups.check_default_parameters,
        parsed(host, "oposs_pbs_backup_rollup"))))
    return names


def test_metrics_of_the_per_host_services_are_defined(output, at_now):
    names = _all_metric_names(output) - {"oposs_pbs_backups_total",
                                         "oposs_pbs_backups_unhealthy"}
    assert names <= DEFINED_METRICS


@pytest.mark.xfail(strict=True, reason=(
    "BUG: PBS Backups emits oposs_pbs_backups_total and "
    "oposs_pbs_backups_unhealthy, which graphing/oposs_pbs.py never defines"))
def test_every_emitted_metric_is_defined_in_graphing(output, at_now):
    assert _all_metric_names(output) <= DEFINED_METRICS


def test_two_runs_per_night_keep_a_daily_cadence(run_agent, monkeypatch):
    """PR #7: a group backed up twice in quick succession every night must not
    read as a 2 h 15 min cadence, or the backup goes stale every afternoon."""
    routes = sample_routes(NOW)
    short = 2 * 3600 + 15 * 60
    first = NOW - 7 * DAY
    times = sorted(t for day in range(8) for t in (first + day * DAY, first + day * DAY + short))
    last = times[-1]
    routes["/admin/datastore/main/groups"][0]["last-backup"] = last
    routes["/admin/datastore/main/snapshots"] = [
        {"backup-type": "vm", "backup-id": "100", "backup-time": t,
         "size": 1000, "comment": "web01"} for t in times]
    sec = parsed(run_agent(routes)["web01"], "oposs_pbs_backup")
    assert sec[0]["interval"] == DAY - short
    params = m.check_plugin_oposs_pbs_backup.check_default_parameters
    monkeypatch.setattr(m.time, "time", lambda: last + 12 * 3600)
    res = list(m.check_oposs_pbs_backup("main vm/100", params, sec))
    assert res[0].state is State.OK
