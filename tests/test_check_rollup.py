import json
from conftest import load_module
from cmk.agent_based.v2 import State, Metric
m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")

NOW = 1_000_000
DAY = 86400
DEFAULTS = {"warn_missed": 2, "crit_missed": 3,
            "fallback_interval": 86400.0, "unverified_state": "ok"}


def _rec(**kw):
    base = {"host": "web-volki-01", "datastore": "ds1", "ns": "op/volki",
            "backup_type": "vm", "backup_id": "102", "last_backup": NOW - 3600,
            "interval": DAY, "interval_known": True, "verify_state": "ok"}
    base.update(kw)
    return base


def _sec(recs):
    return m.parse_rollup([[json.dumps(recs)]])


def _states(res):
    return [r.state for r in res if hasattr(r, "state")]


def test_parse_rollup_empty():
    assert m.parse_rollup([]) == []


def test_rollup_discovery_one_service():
    assert len(list(m.discover_oposs_pbs_backups(_sec([_rec()])))) == 1
    assert list(m.discover_oposs_pbs_backups(_sec([]))) == []


def test_rollup_all_ok(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backups(DEFAULTS, _sec([_rec(), _rec(backup_id="107")])))
    assert State.WARN not in _states(res) and State.CRIT not in _states(res)
    summary = next(r.summary for r in res if getattr(r, "summary", None))
    assert "2 backups OK" in summary


def test_rollup_stale_is_crit_and_lists_only_culprit(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    section = _sec([_rec(),
                    _rec(backup_id="107", host="mysql-volki-01",
                         last_backup=NOW - 5 * DAY)])
    res = list(m.check_oposs_pbs_backups(DEFAULTS, section))
    crit = [r for r in res if hasattr(r, "state") and r.state is State.CRIT]
    assert crit
    details = crit[0].details or ""
    assert "mysql-volki-01" in details and "STALE" in details
    assert "web-volki-01" not in details          # healthy one not listed
    assert "1 stale" in (crit[0].summary or "")


def test_rollup_verify_failed_is_crit(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backups(DEFAULTS, _sec([_rec(verify_state="failed")])))
    crit = [r for r in res if hasattr(r, "state") and r.state is State.CRIT]
    assert crit and "verify" in (crit[0].details or "").lower()


def test_rollup_metrics_count_total_and_unhealthy(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backups(
        DEFAULTS, _sec([_rec(), _rec(verify_state="failed")])))
    mt = {r.name: r.value for r in res if isinstance(r, Metric)}
    assert mt["oposs_pbs_backups_total"] == 2
    assert mt["oposs_pbs_backups_unhealthy"] == 1


def test_rollup_empty_section_ok():
    res = list(m.check_oposs_pbs_backups(DEFAULTS, _sec([])))
    assert all(r.state is State.OK for r in res if hasattr(r, "state"))
