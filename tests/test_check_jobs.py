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
