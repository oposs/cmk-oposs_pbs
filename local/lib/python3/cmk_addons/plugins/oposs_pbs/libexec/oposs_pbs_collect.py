"""Collect PBS state via REST and shape it into Checkmk sections + piggyback."""
from __future__ import annotations
import re
import sys
import time
from dataclasses import dataclass

import oposs_pbs_util as u
from oposs_pbs_cache import StateCache, group_key

# Degraded piggyback fields used when a group's /snapshots refresh fails and
# no previous value is cached. Chosen so the check reports "unknown cadence"
# and "not verified" rather than raising a false alarm.
_DEGRADED = {"interval": None, "interval_known": False,
             "verify_state": "none", "data_size": 0}

# Keep at most this many distinct last-backup timestamps per group; enough to
# derive a stable median cadence without unbounded cache growth.
_MAX_OBSERVATIONS = 32
# Persist the cache at most this often while iterating a datastore, so a long
# cold run that gets killed still leaves forward progress on disk.
_SAVE_INTERVAL_S = 2.0


def _warn(msg: str) -> None:
    """Report a non-fatal collection error on stderr (never on stdout)."""
    print(f"WARNING: {msg}", file=sys.stderr)


class RefreshBudget:
    """Wall-clock ceiling on time spent in expensive /snapshots refreshes.

    Once exhausted, remaining groups emit cached/degraded data and stay
    dirty, so a subsequent run drains the backlog. `limit=None` is unlimited.
    """
    def __init__(self, limit_s: float | None, clock=time.monotonic) -> None:
        self.limit = limit_s
        self._clock = clock
        self.spent = 0.0

    def allow(self) -> bool:
        return self.limit is None or self.spent < self.limit

    def record(self, dt: float) -> None:
        self.spent += dt


def _merge_observations(prev: dict | None, last_backup: int) -> list[int]:
    obs = list(prev.get("observations", [])) if prev else []
    if last_backup:
        obs.append(last_backup)
    return sorted(set(obs))[-_MAX_OBSERVATIONS:]


def _effective_interval(entry: dict, observations: list[int]):
    """Prefer the interval from a real snapshot fetch; otherwise fall back to
    the cadence implied by observed last-backup timestamps."""
    if entry.get("interval_known"):
        return entry.get("interval"), True
    iv = u.median_interval(observations)
    if iv is not None:
        return iv, True
    return None, False


@dataclass
class Options:
    include: list
    exclude: list
    task_limit: int
    piggyback_template: str
    piggyback_regex: tuple | None
    no_piggyback: set


def node_name(client) -> str:
    try:
        nodes = client.get("/nodes") or []
        if nodes and nodes[0].get("node"):
            return nodes[0]["node"]
    except Exception:
        pass
    return "localhost"


def select_datastores(stores: list[str], opts: Options) -> list[str]:
    def ok(name: str) -> bool:
        if opts.include and not any(re.search(p, name) for p in opts.include):
            return False
        if any(re.search(p, name) for p in opts.exclude):
            return False
        return True
    return [s for s in stores if ok(s)]


def _gc_state(tasks, store):
    running = u.task_running(tasks, "garbage_collection", lambda w: w == store)
    latest = u.latest_task(tasks, "garbage_collection", lambda w: w == store)
    return {
        "status": latest["status"] if latest else None,
        "endtime": latest["endtime"] if latest else None,
        "running": running,
    }


def _job_last_run(tasks, worker_type, match):
    latest = u.latest_task(tasks, worker_type, match)
    running = u.task_running(tasks, worker_type, match)
    return ({"status": latest["status"], "endtime": latest["endtime"]} if latest
            else None), running


def _collect_jobs(client, tasks):
    sync = []
    for j in client.get("/config/sync") or []:
        if not j.get("id"):
            continue
        lr, run = _job_last_run(tasks, "syncjob",
                                lambda w, i=j["id"]: w.rsplit(":", 1)[-1] == i)
        sync.append({**j, "last_run": lr, "running": run})
    verify = []
    for j in client.get("/config/verify") or []:
        if not j.get("id"):
            continue
        lr, run = _job_last_run(tasks, "verificationjob",
                                lambda w, i=j["id"]: w.rsplit(":", 1)[-1] == i)
        verify.append({**j, "last_run": lr, "running": run})
    prune = []
    for j in client.get("/config/prune") or []:
        if not j.get("id"):
            continue
        store, ns = j.get("store", ""), j.get("ns", "") or ""
        wid = f"{store}:{ns}" if ns else store
        lr, run = _job_last_run(tasks, "prunejob", lambda w, x=wid: w == x)
        prune.append({**j, "last_run": lr, "running": run})
    return {"sync": sync, "verify": verify, "prune": prune}


def _namespaces(client, store):
    seen = {""}
    out = [""]
    for entry in client.get(f"/admin/datastore/{store}/namespace") or []:
        ns = entry.get("ns", "")
        if ns not in seen:
            seen.add(ns)
            out.append(ns)
    return out


def _refresh_group(client, store, ns, group, now):
    """Fetch this group's snapshots; return (interval, known, verify_state, size)."""
    snaps = client.get(f"/admin/datastore/{store}/snapshots", params={
        "ns": ns, "backup-type": group["backup-type"],
        "backup-id": group["backup-id"],
    }) or []
    times = [int(s["backup-time"]) for s in snaps if s.get("backup-time") is not None]
    interval = u.median_interval(times)
    newest = max(snaps, key=lambda s: s.get("backup-time", 0)) if snaps else {}
    vstate = (newest.get("verification") or {}).get("state") or "none"
    size = int(newest.get("size", 0) or 0)
    return interval, interval is not None, vstate, size


def collect(client, opts: Options, cache: StateCache, now: int,
            budget: "RefreshBudget | None" = None, save=None):
    if budget is None:
        budget = RefreshBudget(None)
    host: dict = {}
    try:
        version = (client.get("/version") or {}).get("version")
        node = node_name(client)
        stores_raw = [d["store"] for d in (client.get("/admin/datastore") or [])]
    except Exception as exc:  # unreachable / auth failure
        host["oposs_pbs_server"] = {"reachable": False, "error": str(exc)}
        return host, []

    stores = select_datastores(stores_raw, opts)
    try:
        tasks = client.get(f"/nodes/{node}/tasks",
                           params={"limit": opts.task_limit}) or []
    except Exception as exc:  # task history is best-effort; degrade job/GC state
        _warn(f"task list fetch failed, job/GC state degraded: {exc}")
        tasks = []

    host["oposs_pbs_server"] = {"reachable": True, "version": version,
                               "node": node, "datastore_count": len(stores)}
    try:
        host["oposs_pbs_jobs"] = _collect_jobs(client, tasks)
    except Exception as exc:
        _warn(f"job config fetch failed: {exc}")
        host["oposs_pbs_jobs"] = {"sync": [], "verify": [], "prune": []}

    # Throttled incremental persistence: bounds data loss if a long cold run
    # is killed before it finishes (see agent's SIGTERM handler).
    saver = _Saver(save)

    datastores: dict = {}
    piggyback: list = []
    for store in stores:
        # One unreachable/slow datastore must not sink the others.
        try:
            _collect_store(client, store, opts, cache, tasks, now,
                           datastores, piggyback, budget, saver)
        except Exception as exc:
            _warn(f"datastore {store!r} collection failed, skipped: {exc}")
        saver.flush()
    host["oposs_pbs_datastore"] = datastores
    return host, piggyback


class _Saver:
    def __init__(self, save):
        self._save = save
        self._last = None

    def maybe(self):
        if self._save is None:
            return
        t = time.monotonic()
        if self._last is None or (t - self._last) >= _SAVE_INTERVAL_S:
            self._save()
            self._last = t

    def flush(self):
        if self._save is not None:
            self._save()
            self._last = time.monotonic()


def _collect_store(client, store, opts, cache, tasks, now, datastores,
                   piggyback, budget, saver):
    status = client.get(f"/admin/datastore/{store}/status") or {}
    gcs = status.get("gc-status") or {}
    group_count = backup_count = 0
    for ns in _namespaces(client, store):
        groups = client.get(f"/admin/datastore/{store}/groups",
                            params={"ns": ns}) or []
        group_count += len(groups)
        backup_count += sum(int(g.get("backup-count", 0)) for g in groups)
        if store in opts.no_piggyback:
            continue
        verify_activity = u.latest_verify_activity(tasks, store)
        for g in groups:
            last_backup = int(g.get("last-backup", 0) or 0)
            key = group_key(store, ns, g["backup-type"], g["backup-id"])
            prev = cache.get(key)
            observations = _merge_observations(prev, last_backup)
            refreshed = False
            if cache.needs_refresh(key, last_backup, verify_activity) \
                    and budget.allow():
                t0 = time.monotonic()
                try:
                    interval, known, vstate, size = _refresh_group(
                        client, store, ns, g, now)
                    cache.put(key, {"last_backup": last_backup,
                                    "verify_checked_at": verify_activity,
                                    "interval": interval, "interval_known": known,
                                    "verify_state": vstate, "data_size": size,
                                    "observations": observations})
                    refreshed = True
                except Exception as exc:
                    # Slow/failed /snapshots: keep any prior cached value (do
                    # NOT mark fresh, so needs_refresh stays true and we retry
                    # next run once PBS has warmed its manifest cache).
                    _warn(f"snapshot refresh failed for {store}/{ns} "
                          f"{g['backup-type']}/{g['backup-id']}: {exc}")
                finally:
                    budget.record(time.monotonic() - t0)
                saver.maybe()
            if not refreshed:
                # No fresh snapshot data (unchanged, budget-capped, or failed):
                # keep prior fields but persist the growing observation history.
                entry = dict(prev) if prev else dict(_DEGRADED)
                entry["observations"] = observations
                cache.put(key, entry)
            e = cache.get(key)
            interval, interval_known = _effective_interval(e, observations)
            host_name = u.piggyback_host(opts.piggyback_template, g,
                                         opts.piggyback_regex)
            piggyback.append((host_name, {
                "datastore": store, "ns": ns,
                "backup_type": g["backup-type"], "backup_id": g["backup-id"],
                "last_backup": last_backup, "backup_count": int(g.get("backup-count", 0)),
                "interval": interval, "interval_known": interval_known,
                "verify_state": e["verify_state"], "data_size": e["data_size"],
            }))
    datastores[store] = {
        "total": status.get("total"), "used": status.get("used"),
        "avail": status.get("avail"),
        "group_count": group_count, "backup_count": backup_count,
        "gc": {**_gc_state(tasks, store),
               "index_data_bytes": gcs.get("index-data-bytes"),
               "disk_bytes": gcs.get("disk-bytes")},
    }
