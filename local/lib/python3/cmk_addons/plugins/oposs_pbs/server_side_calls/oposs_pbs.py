"""Translate ruleset params into agent_oposs_pbs command-line arguments."""
from collections.abc import Iterator

from pydantic import BaseModel
from cmk.server_side_calls.v1 import (
    HostConfig, Secret, SpecialAgentCommand, SpecialAgentConfig,
)


class Params(BaseModel):
    token_id: str
    token_secret: Secret
    port: int | None = None
    verify_tls: bool = True
    cacert: str | None = None
    datastore_include: list[str] = []
    datastore_exclude: list[str] = []
    task_limit: int = 1000
    piggyback_template: str = "{id}"
    piggyback_regex: str | None = None
    no_piggyback: list[str] = []


def _commands(params: Params, host_config: HostConfig) -> Iterator[SpecialAgentCommand]:
    args: list = ["--token-id", params.token_id,
                  "--token-secret", params.token_secret]  # bare Secret => pw-store ref
    if params.port:
        args += ["--port", str(params.port)]
    if not params.verify_tls:
        args.append("--no-verify-tls")
    if params.cacert:
        args += ["--cacert", params.cacert]
    for pat in params.datastore_include:
        args += ["--include-datastore", pat]
    for pat in params.datastore_exclude:
        args += ["--exclude-datastore", pat]
    args += ["--task-limit", str(params.task_limit)]
    args += ["--piggyback-template", params.piggyback_template]
    if params.piggyback_regex:
        args += ["--piggyback-regex", params.piggyback_regex]
    for ds in params.no_piggyback:
        args += ["--no-piggyback-datastore", ds]
    args.append(host_config.primary_ip_config.address or host_config.name)
    yield SpecialAgentCommand(command_arguments=args)


special_agent_oposs_pbs = SpecialAgentConfig(
    name="oposs_pbs",
    parameter_parser=Params.model_validate,
    commands_function=_commands,
)
