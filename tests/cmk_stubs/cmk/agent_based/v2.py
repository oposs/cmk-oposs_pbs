"""Minimal stand-ins for the Checkmk agent_based v2 API used in offline tests."""
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

CheckResult = Iterable[object]
DiscoveryResult = Iterable[object]
HostLabelGenerator = Iterable[object]


class State(enum.Enum):
    OK = 0
    WARN = 1
    CRIT = 2
    UNKNOWN = 3

    @classmethod
    def worst(cls, *states):
        # Checkmk severity order: OK < WARN < UNKNOWN < CRIT.
        rank = {cls.OK: 0, cls.WARN: 1, cls.UNKNOWN: 2, cls.CRIT: 3}
        return max(states, key=lambda s: rank[s]) if states else cls.OK


@dataclass
class Result:
    state: State
    summary: str | None = None
    notice: str | None = None
    details: str | None = None


@dataclass
class Metric:
    name: str
    value: float
    levels: tuple[float, float] | None = None
    boundaries: tuple[float | None, float | None] | None = None


@dataclass
class Service:
    item: str | None = None
    labels: list = field(default_factory=list)


@dataclass
class ServiceLabel:
    name: str
    value: str


@dataclass
class HostLabel:
    name: str
    value: str


class AgentSection:
    def __init__(self, *, name, parse_function, **kw):
        self.name = name
        self.parse_function = parse_function


class CheckPlugin:
    def __init__(self, *, name, service_name, discovery_function, check_function,
                 sections=None, check_ruleset_name=None, check_default_parameters=None, **kw):
        self.name = name
        self.service_name = service_name
        self.discovery_function = discovery_function
        self.check_function = check_function
        self.sections = sections
        self.check_ruleset_name = check_ruleset_name
        self.check_default_parameters = check_default_parameters


def _fixed(levels) -> tuple[float, float] | None:
    if not levels or levels[0] in (None, "no_levels"):
        return None
    if levels[0] == "fixed":
        return levels[1]
    return None


def check_levels(value, *, levels_upper=None, levels_lower=None, metric_name=None,
                 render_func=None, label=None, boundaries=None, notice_only=False
                 ) -> Iterable[Result | Metric]:
    rf: Callable[[float], str] = render_func or (lambda v: str(v))
    state = State.OK
    up = _fixed(levels_upper)
    if up is not None:
        warn, crit = up
        if value >= crit:
            state = State.CRIT
        elif value >= warn:
            state = State.WARN
    low = _fixed(levels_lower)
    if low is not None:
        warn, crit = low
        if value < crit:
            state = State.CRIT
        elif value < warn and state is State.OK:
            state = State.WARN
    text = f"{label}: {rf(value)}" if label else rf(value)
    if notice_only and state is State.OK:
        yield Result(state=state, notice=text)
    else:
        yield Result(state=state, summary=text)
    if metric_name:
        yield Metric(metric_name, float(value), levels=up, boundaries=boundaries)


class render:  # noqa: N801  (mirror real API's lowercase module-like name)
    @staticmethod
    def percent(v): return f"{v:.2f}%"
    @staticmethod
    def bytes(v): return f"{v:.0f}B"
    @staticmethod
    def timespan(v): return f"{v:.0f}s"
    @staticmethod
    def datetime(v): return f"@{int(v)}"
