from cmk.server_side_calls.v1 import HostConfig, IPv4Config, Secret
from conftest import load_module

ssc = load_module("server_side_calls/oposs_pbs.py", "oposs_pbs_ssc")

HOST = HostConfig(name="pbs01", ipv4_config=IPv4Config(address="10.0.0.1"))
# "No IP" in the host setup: the real API raises from primary_ip_config.
NO_IP_HOST = HostConfig(name="pbs01")
# An IPv4 stack whose address could not be resolved.
UNRESOLVED_HOST = HostConfig(name="pbs01", ipv4_config=IPv4Config(address=None))


def _args(params, host=HOST):
    """Run the special agent config the way Checkmk does: raw rule values in,
    command lines out."""
    return next(iter(ssc.special_agent_oposs_pbs(params, host))).command_arguments


def test_command_arguments_use_bare_secret_and_host_last():
    args = _args({"token_id": "root@pam!mon", "token_secret": Secret(3),
                  "verify_tls": True, "task_limit": 500,
                  "datastore_exclude": ["^tmp"], "piggyback_template": "{type}-{id}"})
    assert args[-1] == "10.0.0.1"                       # host address last
    assert "--token-id" in args and "root@pam!mon" in args
    # bare Secret (pass_safely True) -> password-store reference, not plaintext
    sec = args[args.index("--token-secret") + 1]
    assert isinstance(sec, Secret) and sec.pass_safely is True
    assert "--exclude-datastore" in args and "^tmp" in args
    assert "--task-limit" in args and "500" in args
    assert "--piggyback-template" in args and "{type}-{id}" in args
    assert "--no-verify-tls" not in args                # verify default on


def test_timeout_flag_emitted_only_when_set():
    base = {"token_id": "root@pam!mon", "token_secret": Secret(3)}
    no_to = _args(base)
    assert "--timeout" not in no_to                     # unset -> agent default
    with_to = _args({**base, "timeout": 90})
    assert with_to[with_to.index("--timeout") + 1] == "90"


def test_default_piggyback_template_is_guest():
    """Default piggyback host = the PVE guest name, matching the Proxmox VE
    agent's piggyback host (not the numeric VMID)."""
    args = _args({"token_id": "root@pam!mon", "token_secret": Secret(3)})
    assert args[args.index("--piggyback-template") + 1] == "{guest}"


def test_refresh_budget_flag_emitted_only_when_set():
    base = {"token_id": "root@pam!mon", "token_secret": Secret(3)}
    off = _args(base)
    assert "--refresh-budget" not in off
    on = _args({**base, "refresh_budget": 0})
    assert on[on.index("--refresh-budget") + 1] == "0"  # 0 forwarded = unlimited


def test_command_arguments_fall_back_to_host_name_when_no_ip():
    args = _args({"token_id": "root@pam!mon", "token_secret": Secret(3)}, NO_IP_HOST)
    assert args[-1] == "pbs01"


def test_command_arguments_fall_back_to_host_name_when_unresolved():
    args = _args({"token_id": "root@pam!mon", "token_secret": Secret(3)},
                 UNRESOLVED_HOST)
    assert args[-1] == "pbs01"


def test_backup_ignore_patterns_forwarded():
    args = _args({"token_id": "root@pam!mon", "token_secret": Secret(3),
                  "backup_ignore": [r"vm/105$", r"^store1/tenantA/"]})
    assert args.count("--ignore-backup") == 2
    assert r"vm/105$" in args and r"^store1/tenantA/" in args


def test_no_ignore_flag_when_unconfigured():
    args = _args({"token_id": "root@pam!mon", "token_secret": Secret(3)})
    assert "--ignore-backup" not in args


def test_self_host_always_passed_as_checkmk_host_name():
    """The agent needs the Checkmk host name (not the IP) to recognise its own
    backup when PBS runs as a VM on the cluster it backs up."""
    args = _args({"token_id": "root@pam!mon", "token_secret": Secret(3)})
    assert args[args.index("--self-host") + 1] == "pbs01"
    assert args[-1] == "10.0.0.1"          # host address still last


def test_every_rule_option_reaches_the_command_line():
    """A rule with every field the GUI offers, as the backend passes it."""
    args = _args({
        "token_id": "root@pam!mon", "token_secret": Secret(3), "port": 8443,
        "verify_tls": False, "cacert": "/etc/ssl/pbs.pem",
        "datastore_include": ["^prod"], "datastore_exclude": ["^tmp"],
        "task_limit": 0, "timeout": 30, "refresh_budget": 120,
        "piggyback_template": "{id}", "piggyback_regex": "^(.*)$=pve-\\1",
        "no_piggyback": ["archive"], "backup_ignore": ["vm/105$"],
    })
    pairs = {args[i]: args[i + 1] for i in range(len(args) - 1)
             if isinstance(args[i], str) and args[i].startswith("--")}
    assert pairs["--port"] == "8443"
    assert "--no-verify-tls" in args
    assert pairs["--cacert"] == "/etc/ssl/pbs.pem"
    assert pairs["--include-datastore"] == "^prod"
    assert pairs["--task-limit"] == "0"
    assert pairs["--piggyback-regex"] == "^(.*)$=pve-\\1"
    assert pairs["--no-piggyback-datastore"] == "archive"
    assert args[-1] == "10.0.0.1"


def test_secret_is_never_plain_text_on_the_command_line():
    args = _args({"token_id": "root@pam!mon", "token_secret": Secret(3)})
    assert not any(isinstance(a, Secret) and not a.pass_safely for a in args)
