import pytest
from conftest import load_module
from cmk.agent_based.v2 import State, Metric
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


@pytest.mark.xfail(strict=True, reason=(
    "BUG: a running sync/verify/prune job hides the failure and the age of its "
    "last completed run (the GC check was fixed for this, the job checks were not)"))
def test_a_running_job_still_reports_its_failed_last_run(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    jobs = {"verify": [{"id": "v1", "store": "main", "running": True,
                        "last_run": {"status": "bad chunks", "endtime": NOW - 100 * 86400}}]}
    res = list(m.check_oposs_pbs_verify(
        "main", {"age_levels": ("fixed", (86400.0, 7 * 86400.0))}, jobs))
    assert State.CRIT in [r.state for r in res]
