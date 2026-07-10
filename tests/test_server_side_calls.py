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
