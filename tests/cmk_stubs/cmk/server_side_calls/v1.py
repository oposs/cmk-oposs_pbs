from dataclasses import dataclass
from typing import Any, Callable, NamedTuple, Sequence


class Secret(NamedTuple):
    id: int = 0
    format: str = "%s"
    pass_safely: bool = True
    def unsafe(self, template: str = "%s") -> "Secret":
        return self._replace(pass_safely=False, format=template)


@dataclass
class IPv4Config:
    address: str = "10.0.0.1"


@dataclass
class HostConfig:
    name: str = "pbs-host"
    @property
    def primary_ip_config(self):
        return IPv4Config()


@dataclass(frozen=True, kw_only=True)
class SpecialAgentCommand:
    command_arguments: Sequence[Any]
    stdin: str | None = None


class SpecialAgentConfig:
    def __init__(self, *, name, parameter_parser, commands_function):
        self.name = name
        self.parameter_parser = parameter_parser
        self.commands_function = commands_function
