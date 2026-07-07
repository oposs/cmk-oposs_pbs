from conftest import load_module
from cmk.server_side_calls.v1 import HostConfig, Secret
ssc = load_module("server_side_calls/oposs_pbs.py", "oposs_pbs_ssc")


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
