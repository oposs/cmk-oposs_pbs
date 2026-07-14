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
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS, [rec()]))
    assert State.WARN not in _states(res) and State.CRIT not in _states(res)
    mt = {r.name: r.value for r in res if isinstance(r, Metric)}
    assert mt["oposs_pbs_backup_size"] == 41_000_000_000
    assert mt["oposs_pbs_backup_age"] == 3600


def test_missed_two_intervals_warns(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS,
                                        [rec(last_backup=NOW - 2 * DAY - 10)]))
    assert State.WARN in _states(res)


def test_missed_three_intervals_crit(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS,
                                        [rec(last_backup=NOW - 3 * DAY - 10)]))
    assert State.CRIT in _states(res)


def test_verify_failed_is_crit(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS, [rec(verify_state="failed")]))
    assert State.CRIT in _states(res)


def test_unknown_interval_uses_fallback(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS,
               [rec(interval=None, interval_known=False, last_backup=NOW - 3 * DAY)]))
    assert State.CRIT in _states(res)  # 3 * fallback(1d) missed


def test_backup_host_labels():
    """Each piggyback host we report on gets discovered host labels so operators
    can filter/alert on 'has a PBS backup' and by datastore."""
    labels = list(m.host_label_oposs_pbs_backup([rec(datastore="backup-store-01")]))
    pairs = {(l.name, l.value) for l in labels}
    assert ("oposs_pbs/backup", "yes") in pairs
    assert ("oposs_pbs/datastore", "backup-store-01") in pairs


def test_backup_host_labels_empty_section():
    assert list(m.host_label_oposs_pbs_backup([])) == []


def test_discovery_yields_one_service_per_record():
    section = [rec(), rec(datastore="backup2", verify_state="failed",
                          last_backup=NOW - 5 * DAY)]
    services = list(m.discover_oposs_pbs_backup(section))
    assert [s.item for s in services] == ["main", "backup2"]


def test_multi_record_section_second_datastore_not_dropped(monkeypatch):
    # Regression test for C1: a guest backed up to multiple datastores/namespaces
    # produces multiple piggyback records with the same host name, merged by
    # Checkmk into one section with multiple json lines. All records must remain
    # visible, not just the first.
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    section = [rec(), rec(datastore="backup2", verify_state="failed",
                          last_backup=NOW - 5 * DAY)]
    res_backup2 = list(m.check_oposs_pbs_backup("backup2", DEFAULTS, section))
    assert State.CRIT in _states(res_backup2)

    res_main = list(m.check_oposs_pbs_backup("main", DEFAULTS, section))
    assert State.WARN not in _states(res_main) and State.CRIT not in _states(res_main)
