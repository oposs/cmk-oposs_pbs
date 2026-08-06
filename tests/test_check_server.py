import json
from conftest import load_module
from cmk.agent_based.v2 import State
m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")


def _sec(d):
    return m.parse_json([[json.dumps(d)]])


def test_parse_json_empty():
    assert m.parse_json([]) == {}


DEFAULTS = {"unmapped_state": "warn"}


def test_server_ok_and_unreachable():
    ok = list(m.check_oposs_pbs_server(DEFAULTS, _sec(
        {"reachable": True, "version": "3.2.7", "node": "pbs01",
         "datastore_count": 2})))
    assert ok[0].state is State.OK and "3.2.7" in ok[0].summary

    bad = list(m.check_oposs_pbs_server(DEFAULTS, _sec(
        {"reachable": False, "error": "timeout"})))
    assert bad[0].state is State.CRIT and "timeout" in bad[0].summary


def test_server_discovery():
    assert len(list(m.discover_oposs_pbs_server(_sec({"reachable": True})))) == 1


def test_server_reports_unmapped_backups():
    """vm/ct backups without a guest name (landing on their VMID) are surfaced
    so the operator can fix the PVE notes-template; state is configurable."""
    sec = _sec({"reachable": True, "version": "4.2", "node": "localhost",
                "datastore_count": 3,
                "unmapped_backups": [{"datastore": "backup-store-02", "ns": "op/volki",
                                      "backup": "vm/116"}]})
    warn = list(m.check_oposs_pbs_server({"unmapped_state": "warn"}, sec))
    unmapped_res = [r for r in warn if "vm/116" in (getattr(r, "details", "") or "")
                    or "without a guest name" in (getattr(r, "summary", "") or "")]
    assert unmapped_res and unmapped_res[0].state is State.WARN

    # Configurable down to OK for operators who don't care.
    okd = list(m.check_oposs_pbs_server({"unmapped_state": "ok"}, sec))
    assert State.WARN not in [r.state for r in okd if hasattr(r, "state")]


def test_server_no_unmapped_no_note():
    res = list(m.check_oposs_pbs_server(DEFAULTS, _sec(
        {"reachable": True, "version": "4.2", "node": "localhost",
         "datastore_count": 3, "unmapped_backups": []})))
    assert all(r.state is State.OK for r in res if hasattr(r, "state"))


def test_server_reports_ignored_backup_count():
    """Groups suppressed by the ignore patterns are counted so a stale pattern
    is discoverable, but stay OK and out of the summary line."""
    sec = _sec({"reachable": True, "version": "4.2", "node": "localhost",
                "datastore_count": 1, "unmapped_backups": [],
                "ignored_backups": 3})
    res = list(m.check_oposs_pbs_server(DEFAULTS, sec))
    hits = [r for r in res if "ignored" in (getattr(r, "summary", "") or "")
            or "ignored" in (getattr(r, "details", "") or "")]
    assert hits and hits[0].state is State.OK
    assert "3" in (hits[0].details or hits[0].summary)
    # Never escalates and never takes over the service summary line.
    assert all(r.state is State.OK for r in res if hasattr(r, "state"))
    assert "ignored" not in res[0].summary


def test_server_silent_when_nothing_ignored():
    sec = _sec({"reachable": True, "version": "4.2", "node": "localhost",
                "datastore_count": 1, "unmapped_backups": [],
                "ignored_backups": 0})
    res = list(m.check_oposs_pbs_server(DEFAULTS, sec))
    assert not any("ignored" in (getattr(r, "details", "") or "") for r in res)


def test_server_tolerates_missing_ignored_key():
    """Sections from an older agent have no ignored_backups key."""
    res = list(m.check_oposs_pbs_server(DEFAULTS, _sec(
        {"reachable": True, "version": "4.2", "node": "localhost",
         "datastore_count": 1})))
    assert res[0].state is State.OK
