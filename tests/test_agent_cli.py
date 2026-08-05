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
    assert "<<<oposs_pbs_backup_rollup:sep(0)>>>" in out
    # server section parses and is reachable
    line = out.split("<<<oposs_pbs_server:sep(0)>>>\n", 1)[1].splitlines()[0]
    assert json.loads(line)["reachable"] is True


def _run(tmp_path, now, *extra):
    routes_file = tmp_path / "routes.json"
    routes_file.write_text(json.dumps(_routes(now)))
    return subprocess.check_output(
        [sys.executable, str(AGENT), "pbs.example",
         "--token-id", "root@pam!mon", "--token-secret", "x",
         "--test-file", str(routes_file), "--cache-dir", str(tmp_path),
         "--now", str(now), *extra],
        text=True)


def test_self_host_backup_reported_inline_not_as_piggyback(tmp_path):
    """PBS running as a VM on the cluster it backs up: its own backup must be a
    plain section on the PBS host, never a piggyback block addressed to itself."""
    now = 1_000_000
    out = _run(tmp_path, now, "--self-host", "web01")   # guest name in fixture
    assert "<<<<web01>>>>" not in out
    assert "<<<oposs_pbs_backup:sep(0)>>>" in out
    # The inline section must precede any piggyback marker, or it would be
    # attributed to the preceding piggyback host.
    if "<<<<" in out:
        assert out.index("<<<oposs_pbs_backup:sep(0)>>>") < out.index("<<<<")
    # Still present in the host-level roll-up.
    rollup = out.split("<<<oposs_pbs_backup_rollup:sep(0)>>>\n", 1)[1].splitlines()[0]
    assert json.loads(rollup)[0]["backup_id"] == "100"


def test_self_host_match_is_case_insensitive(tmp_path):
    out = _run(tmp_path, 1_000_000, "--self-host", "WEB01")
    assert "<<<<web01>>>>" not in out
    assert "<<<oposs_pbs_backup:sep(0)>>>" in out


def test_self_host_no_match_keeps_piggyback(tmp_path):
    """An exact match is required: an unrelated name leaves output unchanged."""
    out = _run(tmp_path, 1_000_000, "--self-host", "web01.example.com")
    assert "<<<<web01>>>>" in out


def test_ignore_backup_suppresses_group(tmp_path):
    now = 1_000_000
    out = _run(tmp_path, now, "--ignore-backup", r"vm/100$")
    assert "<<<<web01>>>>" not in out
    server = out.split("<<<oposs_pbs_server:sep(0)>>>\n", 1)[1].splitlines()[0]
    assert json.loads(server)["ignored_backups"] == 1
    rollup = out.split("<<<oposs_pbs_backup_rollup:sep(0)>>>\n", 1)[1].splitlines()[0]
    assert json.loads(rollup) == []


def test_invalid_ignore_pattern_fails_loudly(tmp_path):
    """A broken regex is a misconfiguration, not a PBS-side error: fail at
    startup rather than silently monitoring nothing."""
    now = 1_000_000
    routes_file = tmp_path / "routes.json"
    routes_file.write_text(json.dumps(_routes(now)))
    proc = subprocess.run(
        [sys.executable, str(AGENT), "pbs.example",
         "--token-id", "root@pam!mon", "--token-secret", "x",
         "--test-file", str(routes_file), "--cache-dir", str(tmp_path),
         "--now", str(now), "--ignore-backup", "vm/[100"],
        text=True, capture_output=True)
    assert proc.returncode != 0
    assert "vm/[100" in proc.stderr
    assert proc.stdout == ""
