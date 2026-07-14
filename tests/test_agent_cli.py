import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / \
    "local/lib/python3/cmk_addons/plugins/oposs_pbs"
AGENT = PLUGIN / "libexec/agent_oposs_pbs"


def _routes(now):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
    from fake_pbs import sample_routes
    # Only static routes survive JSON; callables aren't used in sample_routes.
    return sample_routes(now)


def test_agent_test_file_mode(tmp_path):
    now = 1_000_000
    routes_file = tmp_path / "routes.json"
    routes_file.write_text(json.dumps(_routes(now)))
    out = subprocess.check_output(
        [sys.executable, str(AGENT), "pbs.example",
         "--token-id", "root@pam!mon", "--token-secret", "x",
         "--test-file", str(routes_file), "--cache-dir", str(tmp_path),
         "--now", str(now)],
        text=True)
    assert "<<<oposs_pbs_server:sep(0)>>>" in out
    assert "<<<oposs_pbs_datastore:sep(0)>>>" in out
    # default template is {guest} -> piggyback host is the guest name (snapshot
    # comment "web01"), not the numeric VMID 100.
    assert "<<<<web01>>>>" in out
    assert "<<<oposs_pbs_backup:sep(0)>>>" in out
    # server section parses and is reachable
    line = out.split("<<<oposs_pbs_server:sep(0)>>>\n", 1)[1].splitlines()[0]
    assert json.loads(line)["reachable"] is True
