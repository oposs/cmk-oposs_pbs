"""Check plugins for the oposs_pbs special agent."""
from __future__ import annotations
import json
import time

from cmk.agent_based.v2 import (
    AgentSection, CheckPlugin, CheckResult, DiscoveryResult, Metric, Result,
    Service, ServiceLabel, State, check_levels, render,
)


def parse_json(string_table):
    if not string_table or not string_table[0]:
        return {}
    try:
        return json.loads(string_table[0][0])
    except (ValueError, IndexError):
        return {}


agent_section_oposs_pbs_server = AgentSection(name="oposs_pbs_server", parse_function=parse_json)
agent_section_oposs_pbs_datastore = AgentSection(name="oposs_pbs_datastore", parse_function=parse_json)
agent_section_oposs_pbs_jobs = AgentSection(name="oposs_pbs_jobs", parse_function=parse_json)
agent_section_oposs_pbs_backup = AgentSection(name="oposs_pbs_backup", parse_function=parse_json)


# --- PBS Server -------------------------------------------------------------

def discover_oposs_pbs_server(section) -> DiscoveryResult:
    if section:
        yield Service()


def check_oposs_pbs_server(section) -> CheckResult:
    if not section:
        yield Result(state=State.UNKNOWN, summary="No data from agent")
        return
    if not section.get("reachable"):
        yield Result(state=State.CRIT,
                     summary=f"PBS API unreachable: {section.get('error', 'unknown error')}")
        return
    yield Result(state=State.OK, summary=(
        f"Version {section.get('version', '?')}, node {section.get('node', '?')}, "
        f"{section.get('datastore_count', 0)} datastore(s)"))


check_plugin_oposs_pbs_server = CheckPlugin(
    name="oposs_pbs_server", service_name="PBS Server",
    sections=["oposs_pbs_server"],
    discovery_function=discover_oposs_pbs_server,
    check_function=check_oposs_pbs_server)
