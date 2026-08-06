from conftest import load_module
from cmk.server_side_calls.v1 import HostConfig, Secret
ssc = load_module("server_side_calls/oposs_pbs.py", "oposs_pbs_ssc")


class _NoIPHostConfig:
    """Stand-in for a host with no resolvable IP: the real API raises
    ValueError/RuntimeError from primary_ip_config rather than returning
    something falsy."""
    name = "pbs01"

    @property
    def primary_ip_config(self):
        raise ValueError("no IP address configured for this host")


def test_command_arguments_use_bare_secret_and_host_last():
    params = ssc.Params(token_id="root@pam!mon", token_secret=Secret(3),
                        verify_tls=True, task_limit=500,
                        datastore_exclude=["^tmp"], piggyback_template="{type}-{id}")
    cmds = list(ssc.special_agent_oposs_pbs.commands_function(
        params, HostConfig(name="pbs01")))
    args = cmds[0].command_arguments
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
    base = dict(token_id="root@pam!mon", token_secret=Secret(3))
    no_to = list(ssc.special_agent_oposs_pbs.commands_function(
        ssc.Params(**base), HostConfig(name="pbs01")))[0].command_arguments
    assert "--timeout" not in no_to                     # unset -> agent default
    with_to = list(ssc.special_agent_oposs_pbs.commands_function(
        ssc.Params(**base, timeout=90), HostConfig(name="pbs01")))[0].command_arguments
    assert with_to[with_to.index("--timeout") + 1] == "90"


def test_default_piggyback_template_is_guest():
    """Default piggyback host = the PVE guest name, matching the Proxmox VE
    agent's piggyback host (not the numeric VMID)."""
    args = list(ssc.special_agent_oposs_pbs.commands_function(
        ssc.Params(token_id="root@pam!mon", token_secret=Secret(3)),
        HostConfig(name="pbs01")))[0].command_arguments
    assert args[args.index("--piggyback-template") + 1] == "{guest}"


def test_refresh_budget_flag_emitted_only_when_set():
    base = dict(token_id="root@pam!mon", token_secret=Secret(3))
    off = list(ssc.special_agent_oposs_pbs.commands_function(
        ssc.Params(**base), HostConfig(name="pbs01")))[0].command_arguments
    assert "--refresh-budget" not in off
    on = list(ssc.special_agent_oposs_pbs.commands_function(
        ssc.Params(**base, refresh_budget=0), HostConfig(name="pbs01")))[0].command_arguments
    assert on[on.index("--refresh-budget") + 1] == "0"  # 0 forwarded = unlimited


def test_command_arguments_fall_back_to_host_name_when_no_ip():
    params = ssc.Params(token_id="root@pam!mon", token_secret=Secret(3))
    cmds = list(ssc.special_agent_oposs_pbs.commands_function(
        params, _NoIPHostConfig()))
    args = cmds[0].command_arguments
    assert args[-1] == "pbs01"


def test_backup_ignore_patterns_forwarded():
    params = ssc.Params(token_id="root@pam!mon", token_secret=Secret(3),
                        backup_ignore=[r"vm/105$", r"^store1/tenantA/"])
    args = list(ssc.special_agent_oposs_pbs.commands_function(
        params, HostConfig(name="pbs01")))[0].command_arguments
    assert args.count("--ignore-backup") == 2
    assert r"vm/105$" in args and r"^store1/tenantA/" in args


def test_no_ignore_flag_when_unconfigured():
    args = list(ssc.special_agent_oposs_pbs.commands_function(
        ssc.Params(token_id="root@pam!mon", token_secret=Secret(3)),
        HostConfig(name="pbs01")))[0].command_arguments
    assert "--ignore-backup" not in args


def test_self_host_always_passed_as_checkmk_host_name():
    """The agent needs the Checkmk host name (not the IP) to recognise its own
    backup when PBS runs as a VM on the cluster it backs up."""
    args = list(ssc.special_agent_oposs_pbs.commands_function(
        ssc.Params(token_id="root@pam!mon", token_secret=Secret(3)),
        HostConfig(name="pbs01")))[0].command_arguments
    assert args[args.index("--self-host") + 1] == "pbs01"
    assert args[-1] == "10.0.0.1"          # host address still last
