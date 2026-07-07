import json
from conftest import load_module
from cmk.agent_based.v2 import State
m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")


def _sec(d):
    return m.parse_json([[json.dumps(d)]])


def test_parse_json_empty():
    assert m.parse_json([]) == {}


def test_server_ok_and_unreachable():
    ok = list(m.check_oposs_pbs_server(_sec(
        {"reachable": True, "version": "3.2.7", "node": "pbs01",
         "datastore_count": 2})))
    assert ok[0].state is State.OK and "3.2.7" in ok[0].summary

    bad = list(m.check_oposs_pbs_server(_sec(
        {"reachable": False, "error": "timeout"})))
    assert bad[0].state is State.CRIT and "timeout" in bad[0].summary


def test_server_discovery():
    assert len(list(m.discover_oposs_pbs_server(_sec({"reachable": True})))) == 1
