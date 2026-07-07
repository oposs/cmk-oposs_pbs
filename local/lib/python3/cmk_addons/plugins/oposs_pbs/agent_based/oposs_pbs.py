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


def parse_backup(string_table):
    records = []
    for row in string_table:
        if not row:
            continue
        try:
            records.append(json.loads(row[0]))
        except (ValueError, IndexError, TypeError):
            continue
    return records


agent_section_oposs_pbs_server = AgentSection(name="oposs_pbs_server", parse_function=parse_json)
agent_section_oposs_pbs_datastore = AgentSection(name="oposs_pbs_datastore", parse_function=parse_json)
agent_section_oposs_pbs_jobs = AgentSection(name="oposs_pbs_jobs", parse_function=parse_json)
agent_section_oposs_pbs_backup = AgentSection(name="oposs_pbs_backup", parse_function=parse_backup)


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


# --- Jobs: sync / verify / prune --------------------------------------------

def _sync_item(job) -> str:
    base = f"{job.get('remote', '?')}:{job.get('remote-store', '?')}"
    ns = job.get("ns")
    return f"{base} -> {ns}" if ns else base


def _store_ns_item(job) -> str:
    store = job.get("store", "?")
    ns = job.get("ns")
    return f"{store}/{ns}" if ns else store


def _check_job(job, params, kind: str, metric: str) -> CheckResult:
    if job is None:
        return
    if job.get("running"):
        yield Result(state=State.OK, summary=f"{kind} running")
        return
    last = job.get("last_run")
    if not last:
        yield Result(state=State.OK, summary=f"No completed {kind} run yet")
        return
    status = last.get("status")
    end = last.get("endtime")
    if status == "OK":
        if end:
            age = max(0.0, time.time() - end)
            yield from check_levels(age, levels_upper=params.get("age_levels"),
                                    metric_name=metric, label=f"Last {kind}",
                                    render_func=render.timespan)
        else:
            yield Result(state=State.OK, summary=f"Last {kind} OK")
    else:
        when = f" at {render.datetime(end)}" if end else ""
        yield Result(state=State.CRIT, summary=f"Last {kind} failed{when}: {status}")


def discover_oposs_pbs_sync(section) -> DiscoveryResult:
    for j in (section or {}).get("sync", []):
        if j.get("id"):
            yield Service(item=_sync_item(j))


def check_oposs_pbs_sync(item, params, section) -> CheckResult:
    job = {(_sync_item(j)): j for j in (section or {}).get("sync", []) if j.get("id")}.get(item)
    yield from _check_job(job, params, "sync", "oposs_pbs_sync_age")


def discover_oposs_pbs_verify(section) -> DiscoveryResult:
    for j in (section or {}).get("verify", []):
        if j.get("id"):
            yield Service(item=_store_ns_item(j))


def check_oposs_pbs_verify(item, params, section) -> CheckResult:
    job = {(_store_ns_item(j)): j for j in (section or {}).get("verify", []) if j.get("id")}.get(item)
    yield from _check_job(job, params, "verification", "oposs_pbs_verify_age")


def discover_oposs_pbs_prune(section) -> DiscoveryResult:
    for j in (section or {}).get("prune", []):
        if j.get("id"):
            yield Service(item=_store_ns_item(j))


def check_oposs_pbs_prune(item, params, section) -> CheckResult:
    job = {(_store_ns_item(j)): j for j in (section or {}).get("prune", []) if j.get("id")}.get(item)
    yield from _check_job(job, params, "prune", "oposs_pbs_prune_age")


_JOB_DEFAULTS = {"age_levels": ("no_levels", None)}

check_plugin_oposs_pbs_sync = CheckPlugin(
    name="oposs_pbs_sync", service_name="PBS Sync Job %s", sections=["oposs_pbs_jobs"],
    discovery_function=discover_oposs_pbs_sync, check_function=check_oposs_pbs_sync,
    check_ruleset_name="oposs_pbs_job", check_default_parameters=_JOB_DEFAULTS)

check_plugin_oposs_pbs_verify = CheckPlugin(
    name="oposs_pbs_verify", service_name="PBS Verify Job %s", sections=["oposs_pbs_jobs"],
    discovery_function=discover_oposs_pbs_verify, check_function=check_oposs_pbs_verify,
    check_ruleset_name="oposs_pbs_job", check_default_parameters=_JOB_DEFAULTS)

check_plugin_oposs_pbs_prune = CheckPlugin(
    name="oposs_pbs_prune", service_name="PBS Prune Job %s", sections=["oposs_pbs_jobs"],
    discovery_function=discover_oposs_pbs_prune, check_function=check_oposs_pbs_prune,
    check_ruleset_name="oposs_pbs_job", check_default_parameters=_JOB_DEFAULTS)


# --- PBS Backup freshness (piggyback) ---------------------------------------

def _backup_item(rec) -> str:
    ns = rec.get("ns")
    return f"{rec['datastore']}/{ns}" if ns else rec.get("datastore", "?")


def discover_oposs_pbs_backup(section) -> DiscoveryResult:
    for rec in section or []:
        if rec.get("datastore"):
            yield Service(item=_backup_item(rec))


def check_oposs_pbs_backup(item, params, section) -> CheckResult:
    rec = next((r for r in (section or []) if _backup_item(r) == item), None)
    if rec is None:
        return
    now = time.time()
    last = rec.get("last_backup") or 0
    age = max(0.0, now - last)
    interval = rec.get("interval") if rec.get("interval_known") \
        else params.get("fallback_interval", 86400.0)
    if not interval:
        interval = params.get("fallback_interval", 86400.0)

    warn_missed = params.get("warn_missed", 2)
    crit_missed = params.get("crit_missed", 3)
    levels = ("fixed", (warn_missed * interval, crit_missed * interval))
    suffix = "" if rec.get("interval_known") else " (assumed cadence)"
    yield from check_levels(
        age, levels_upper=levels, metric_name="oposs_pbs_backup_age",
        label="Last backup age", render_func=render.timespan)
    yield Result(state=State.OK, notice=(
        f"Cadence ~{render.timespan(interval)}{suffix}, "
        f"{rec.get('backup_count', 0)} snapshots"))

    size = rec.get("data_size") or 0
    yield Metric("oposs_pbs_backup_size", float(size))
    yield Result(state=State.OK, notice=f"Protected data {render.bytes(size)}")

    vstate = rec.get("verify_state", "none")
    if vstate == "failed":
        yield Result(state=State.CRIT, summary="Newest snapshot verification failed")
    elif vstate == "ok":
        yield Result(state=State.OK, notice="Newest snapshot verified OK")
    else:  # none / unverified
        unver = State.WARN if params.get("unverified_state") == "warn" else State.OK
        yield Result(state=unver, notice="Newest snapshot not verified")


check_plugin_oposs_pbs_backup = CheckPlugin(
    name="oposs_pbs_backup", service_name="PBS Backup %s",
    sections=["oposs_pbs_backup"],
    discovery_function=discover_oposs_pbs_backup,
    check_function=check_oposs_pbs_backup,
    check_ruleset_name="oposs_pbs_backup",
    check_default_parameters={"warn_missed": 2, "crit_missed": 3,
                              "fallback_interval": 86400.0, "unverified_state": "ok"})
