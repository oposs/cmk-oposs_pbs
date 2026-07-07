from conftest import load_module
from cmk.agent_based.v2 import State, Metric
m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")

NOW = 1_000_000
DAY = 86400
DEFAULTS = {"warn_missed": 2, "crit_missed": 3,
            "fallback_interval": 86400.0, "unverified_state": "ok"}


def rec(**kw):
    base = {"datastore": "main", "ns": "", "backup_type": "vm", "backup_id": "100",
            "last_backup": NOW - 3600, "backup_count": 7, "interval": DAY,
            "interval_known": True, "verify_state": "ok", "data_size": 41_000_000_000}
    base.update(kw)
    return base


def _states(res):
    return [r.state for r in res if hasattr(r, "state")]


def test_fresh_backup_ok(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS, rec()))
    assert State.WARN not in _states(res) and State.CRIT not in _states(res)
    mt = {r.name: r.value for r in res if isinstance(r, Metric)}
    assert mt["oposs_pbs_backup_size"] == 41_000_000_000
    assert mt["oposs_pbs_backup_age"] == 3600


def test_missed_two_intervals_warns(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS,
                                        rec(last_backup=NOW - 2 * DAY - 10)))
    assert State.WARN in _states(res)


def test_missed_three_intervals_crit(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS,
                                        rec(last_backup=NOW - 3 * DAY - 10)))
    assert State.CRIT in _states(res)


def test_verify_failed_is_crit(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS, rec(verify_state="failed")))
    assert State.CRIT in _states(res)


def test_unknown_interval_uses_fallback(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS,
               rec(interval=None, interval_known=False, last_backup=NOW - 3 * DAY)))
    assert State.CRIT in _states(res)  # 3 * fallback(1d) missed
