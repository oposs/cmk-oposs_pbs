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


# --- PBS Datastore ----------------------------------------------------------

def _dedup_factor(index_data_bytes, disk_bytes):
    try:
        if not disk_bytes or index_data_bytes is None:
            return None
        return float(index_data_bytes) / float(disk_bytes)
    except (TypeError, ZeroDivisionError):
        return None


def discover_oposs_pbs_datastore(section) -> DiscoveryResult:
    for store in section or {}:
        yield Service(item=store, labels=[ServiceLabel("oposs_pbs/datastore", "yes")])


def check_oposs_pbs_datastore(item, params, section) -> CheckResult:
    ds = (section or {}).get(item)
    if ds is None:
        return
    total = ds.get("total") or 0
    used = ds.get("used") or 0
    avail = ds.get("avail") or 0
    used_pct = (used / total * 100.0) if total else 0.0

    yield from check_levels(
        used_pct, levels_upper=params.get("usage_levels"),
        metric_name="oposs_pbs_datastore_used_pct", label="Usage",
        render_func=render.percent, boundaries=(0.0, 100.0))
    yield Metric("oposs_pbs_datastore_size", float(total))
    yield Metric("oposs_pbs_datastore_used", float(used))
    yield Metric("oposs_pbs_datastore_avail", float(avail))
    yield Result(state=State.OK, notice=(
        f"Size {render.bytes(total)}, used {render.bytes(used)}, "
        f"free {render.bytes(avail)}"))

    yield Metric("oposs_pbs_group_count", float(ds.get("group_count", 0)))
    yield Metric("oposs_pbs_backup_count", float(ds.get("backup_count", 0)))
    yield Result(state=State.OK, notice=(
        f"{ds.get('backup_count', 0)} backups in {ds.get('group_count', 0)} groups"))

    gc = ds.get("gc") or {}
    factor = _dedup_factor(gc.get("index_data_bytes"), gc.get("disk_bytes"))
    if factor is not None:
        yield Metric("oposs_pbs_dedup_factor", factor)
        yield Result(state=State.OK, notice=f"Deduplication factor {factor:.2f}")

    if gc.get("running"):
        yield Result(state=State.OK, summary="GC running")
    elif gc.get("status") is None:
        yield Result(state=State.UNKNOWN, summary="GC not run yet")
    elif gc.get("status") == "OK":
        end = gc.get("endtime")
        if end:
            age = max(0.0, time.time() - end)
            yield from check_levels(
                age, levels_upper=params.get("gc_age_levels"),
                metric_name="oposs_pbs_gc_age", label="Last GC",
                render_func=render.timespan)
        else:
            yield Result(state=State.OK, summary="GC ok")
    else:
        yield Result(state=State.WARN, summary=f"GC failed: {gc.get('status')}")


check_plugin_oposs_pbs_datastore = CheckPlugin(
    name="oposs_pbs_datastore", service_name="PBS Datastore %s",
    sections=["oposs_pbs_datastore"],
    discovery_function=discover_oposs_pbs_datastore,
    check_function=check_oposs_pbs_datastore,
    check_ruleset_name="oposs_pbs_datastore",
    check_default_parameters={"usage_levels": ("fixed", (80.0, 90.0)),
                              "gc_age_levels": ("no_levels", None)})
