from cmk.agent_based.v2 import Metric, State
from conftest import load_module

m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")

NOW = 1_000_000
JOBS = {
    "sync": [{"id": "s1", "store": "main", "remote": "r1", "remote-store": "rs",
              "ns": "", "schedule": "daily",
              "last_run": {"status": "OK", "endtime": NOW - 100}, "running": False}],
    "verify": [{"id": "v1", "store": "main", "schedule": "weekly",
                "last_run": {"status": "bad chunks"}, "running": False}],
    "prune": [{"id": "p1", "store": "main", "schedule": "daily",
               "last_run": None, "running": False}],
}


def test_sync_item_and_ok(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    items = [s.item for s in m.discover_oposs_pbs_sync(JOBS)]
    assert items == ["r1:rs"]
    res = list(m.check_oposs_pbs_sync("r1:rs", {"age_levels": ("no_levels", None)}, JOBS))
    assert res[0].state is State.OK
    assert any(isinstance(r, Metric) and r.name == "oposs_pbs_sync_age" for r in res)


def test_verify_failure_is_crit():
    res = list(m.check_oposs_pbs_verify("main", {"age_levels": ("no_levels", None)}, JOBS))
    assert res[0].state is State.CRIT and "bad chunks" in res[0].summary


def test_prune_never_run_is_ok():
    res = list(m.check_oposs_pbs_prune("main", {"age_levels": ("no_levels", None)}, JOBS))
    assert res[0].state is State.OK and "No completed" in res[0].summary


def test_job_age_levels_apply(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    for levels, want in (((50.0, 200.0), State.WARN), ((20.0, 50.0), State.CRIT),
                         ((200.0, 400.0), State.OK)):
        res = list(m.check_oposs_pbs_sync("r1:rs", {"age_levels": ("fixed", levels)}, JOBS))
        assert res[0].state is want, levels


def test_job_items_carry_the_namespace():
    jobs = {"sync": [{"id": "s2", "remote": "r1", "remote-store": "rs", "ns": "tenantA"}],
            "verify": [{"id": "v2", "store": "main", "ns": "tenantA"}],
            "prune": [{"id": "p2", "store": "main", "ns": "tenantA"}]}
    assert [s.item for s in m.discover_oposs_pbs_sync(jobs)] == ["r1:rs -> tenantA"]
    assert [s.item for s in m.discover_oposs_pbs_verify(jobs)] == ["main/tenantA"]
    assert [s.item for s in m.discover_oposs_pbs_prune(jobs)] == ["main/tenantA"]


def test_jobs_without_an_id_are_not_discovered():
    jobs = {"sync": [{"remote": "r1", "remote-store": "rs"}], "verify": [{}], "prune": []}
    assert list(m.discover_oposs_pbs_sync(jobs)) == []
    assert list(m.discover_oposs_pbs_verify(jobs)) == []
    assert list(m.discover_oposs_pbs_sync({})) == []


def test_a_running_job_still_reports_its_failed_last_run(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    jobs = {"verify": [{"id": "v1", "store": "main", "running": True,
                        "last_run": {"status": "bad chunks", "endtime": NOW - 100 * 86400}}]}
    res = list(m.check_oposs_pbs_verify(
        "main", {"age_levels": ("fixed", (86400.0, 7 * 86400.0))}, jobs))
    assert State.CRIT in [r.state for r in res]


LEVELS = {"age_levels": ("fixed", (86400.0, 7 * 86400.0))}


def _running_verify(last_run):
    return {"verify": [{"id": "v1", "store": "main", "running": True,
                        "last_run": last_run}]}


def test_a_running_job_with_a_good_last_run_reports_both(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_verify(
        "main", LEVELS, _running_verify({"status": "OK", "endtime": NOW - 3600})))
    assert [(r.state, r.summary) for r in res if hasattr(r, "state")] == [
        (State.OK, "verification running"),
        (State.OK, "Last verification: 1 hour 0 minutes"),
    ]
    assert any(isinstance(r, Metric) and r.value == 3600 for r in res)


def test_a_running_job_with_a_failed_last_run_stays_crit(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_verify(
        "main", LEVELS, _running_verify({"status": "bad chunks", "endtime": NOW - 3600})))
    assert [r.state for r in res] == [State.OK, State.CRIT]
    assert res[0].summary == "verification running"
    assert res[1].summary.startswith("Last verification failed at ")
    assert res[1].summary.endswith(": bad chunks")


def test_a_running_job_with_a_too_old_last_run_hits_the_age_levels(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_sync("r1:rs", LEVELS, {"sync": [
        {"id": "s1", "remote": "r1", "remote-store": "rs", "running": True,
         "last_run": {"status": "OK", "endtime": NOW - 10 * 86400}}]}))
    states = [r.state for r in res if hasattr(r, "state")]
    assert states == [State.OK, State.CRIT]
    assert res[0].summary == "sync running"
    assert any(isinstance(r, Metric) and r.name == "oposs_pbs_sync_age" for r in res)


def test_a_first_run_in_progress_is_reported_as_running():
    res = list(m.check_oposs_pbs_prune("main", LEVELS, {"prune": [
        {"id": "p1", "store": "main", "running": True, "last_run": None}]}))
    assert [(r.state, r.summary) for r in res] == [
        (State.OK, "prune running"), (State.OK, "No completed prune run yet")]
