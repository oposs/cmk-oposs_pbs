import json
from conftest import load_module
from cmk.agent_based.v2 import State, Metric
m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")

NOW = 1_000_000
SECTION = {"main": {
    "total": 1000, "used": 950, "avail": 50,
    "group_count": 3, "backup_count": 21,
    "gc": {"status": "OK", "endtime": NOW - 3600, "running": False,
           "index_data_bytes": 4000, "disk_bytes": 1000}}}
DEFAULTS = {"usage_levels": ("fixed", (80.0, 90.0)),
            "gc_age_levels": ("no_levels", None)}


def _metrics(results):
    return {r.name: r.value for r in results if isinstance(r, Metric)}


def test_datastore_usage_crit_and_metrics(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_datastore("main", DEFAULTS, SECTION))
    states = [r.state for r in res if hasattr(r, "state")]
    assert State.CRIT in states                       # 95% > 90%
    mt = _metrics(res)
    assert mt["oposs_pbs_datastore_used"] == 950
    assert mt["oposs_pbs_datastore_used_pct"] == 95.0
    assert mt["oposs_pbs_dedup_factor"] == 4.0
    assert mt["oposs_pbs_backup_count"] == 21


def test_datastore_gc_failure_warns(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    sec = json.loads(json.dumps(SECTION))
    sec["main"]["gc"]["status"] = "some error"
    res = list(m.check_oposs_pbs_datastore("main", DEFAULTS, sec))
    assert any(r.state is State.WARN and "GC" in (r.summary or r.notice or "")
               for r in res if hasattr(r, "state"))


def test_datastore_missing_item():
    assert list(m.check_oposs_pbs_datastore("nope", DEFAULTS, SECTION)) == []
