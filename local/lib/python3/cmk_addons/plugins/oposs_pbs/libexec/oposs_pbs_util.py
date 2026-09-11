"""Pure helpers for the PBS collector: intervals, dedup, task matching."""
from __future__ import annotations
import re
from statistics import median
from typing import Callable

_VERIFY_TYPES = {"verificationjob", "verify", "verify_group", "verify_snapshot"}


def median_interval(times: list[int], recent: int | None = None) -> int | None:
    """Median gap between the given backup times.

    `recent` keeps only the newest N gaps. Prune thins the old end of a
    retention into weeklies and monthlies, so a median over the whole list
    reports a cadence several times longer than the backup actually runs at,
    which delays the stale-backup alarm by days.
    """
    if len(times) < 2:
        return None
    ordered = sorted(times)
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
    if recent:
        gaps = gaps[-recent:]
    if not gaps:
        return None
    return int(median(gaps))


def dedup_factor(index_data_bytes, disk_bytes):
    try:
        if not disk_bytes or index_data_bytes is None:
            return None
        return float(index_data_bytes) / float(disk_bytes)
    except (TypeError, ZeroDivisionError):
        return None


def group_path(store: str, ns: str, btype: str, bid: str) -> str:
    """Canonical identifier of a backup group, matched by the ignore filter.

    An empty namespace yields the double-slash form, e.g. "store1//vm/105";
    a namespaced group yields "store1/tenantA/ct/210".
    """
    return f"{store}/{ns}/{btype}/{bid}"


def piggyback_host(template: str, group: dict, regex: tuple[str, str] | None,
                   guest: str | None = None) -> str:
    bid = group.get("backup-id", "")
    # {guest} is the PVE guest name (the backup's snapshot comment) -- the same
    # string the built-in Proxmox VE agent piggybacks under. Fall back to the
    # backup-id when there is no guest name so the host is never empty.
    guest_name = (guest or "").strip() or bid
    name = template.format(
        id=bid,
        type=group.get("backup-type", ""),
        comment=group.get("comment", "") or "",
        guest=guest_name,
    )
    if regex:
        pattern, repl = regex
        name = re.sub(pattern, repl, name)
    return name


# --- Task history -----------------------------------------------------------

# Worker types the checks derive state from. PBS matches `typefilter` on the
# *exact* worker type (verified on PBS 4.2: "verify" does not match
# "verificationjob"), so each one needs its own query.
TASK_TYPES: tuple[str, ...] = (
    "garbage_collection", "syncjob", "prunejob", *sorted(_VERIFY_TYPES),
)

# Reserved StateCache key. Group keys are "ds|ns|type|id", so this cannot clash.
TASK_CACHE_KEY = "__tasks__"


class TaskHistory:
    """What the PBS task list told us, remembered between agent runs.

    The agent used to read one global task list truncated at --task-limit and
    derive every job and GC state from it. That window reaches back only as far
    as overall task volume allows: on a busy server the last garbage collection
    drops out of it and the check reports "GC not run yet" for a datastore
    whose GC runs nightly.

    Instead we keep one finding per (worker type, worker id) in the state cache
    and top it up each run. Two consequences:

    * A finding survives both the window and PBS's own history retention, so a
      state change cannot fall between two polls.
    * Once the whole history of a type has been read (a poll that came back
      short of the limit), later polls only need the tasks that started since
      `since_anchor`, which is a few rows instead of a few thousand.
    """

    def __init__(self, state: dict | None = None) -> None:
        self._t: dict = dict(state or {})

    # -- state -------------------------------------------------------------
    def as_state(self) -> dict:
        return self._t

    def _type(self, worker_type: str) -> dict:
        return self._t.setdefault(
            worker_type,
            {"workers": {}, "truncated": True, "oldest_seen": None,
             "polled_at": None})

    # -- ingestion ---------------------------------------------------------
    def absorb(self, worker_type: str, tasks: list, *, limit: int,
               now: int) -> None:
        """Fold one fetch of `worker_type` into the findings.

        `limit` is the limit that fetch was made with: coming back short of it
        proves nothing older was withheld, which is what lets later polls go
        incremental and what tells the check whether "no run found" means
        "never ran" or merely "not within reach".
        """
        t = self._type(worker_type)
        workers: dict = t["workers"]
        for task in tasks:
            wid = task.get("worker_id", "") or ""
            entry = workers.setdefault(wid, {})
            start = task.get("starttime")
            if start is None:
                continue
            if task.get("endtime") is None:
                # Unfinished. Keep the newest start only; an older run of the
                # same worker cannot still be alive.
                prev_run = entry.get("running_since")
                if prev_run is None or start >= prev_run:
                    entry["running_since"] = start
                continue
            prev_start = entry.get("starttime")
            if prev_start is None or start >= prev_start:
                entry.update(starttime=start, endtime=task["endtime"],
                             status=task.get("status"))
            # This start is accounted for, so it is no longer running.
            if entry.get("running_since") == start:
                entry.pop("running_since", None)
        starts = [x["starttime"] for x in tasks if x.get("starttime") is not None]
        if starts:
            oldest = min(starts)
            prev = t["oldest_seen"]
            t["oldest_seen"] = oldest if prev is None else min(prev, oldest)
        t["truncated"] = limit > 0 and len(tasks) >= limit
        t["polled_at"] = now

    def retain(self, worker_type: str, worker_ids) -> None:
        """Drop findings for workers that no longer exist (deleted job or
        datastore), so the cache cannot grow without bound."""
        keep = set(worker_ids)
        self.retain_matching(worker_type, [lambda w: w in keep])

    def retain_matching(self, worker_type: str, matchers) -> None:
        """Same, for workers reachable only through a predicate: a job's PBS
        worker id embeds the remote, store and namespace, so the job lookup
        matches on a suffix rather than on a known id."""
        t = self._type(worker_type)
        t["workers"] = {w: e for w, e in t["workers"].items()
                        if any(m(w) for m in matchers)}

    # -- queries -----------------------------------------------------------
    def since_anchor(self, worker_type: str) -> int | None:
        """Oldest start time the next poll of this type must reach back to, or
        None when the whole history has to be read again.

        PBS filters `since` on a task's *start* time, so a run that started
        before the anchor and finished after it is never returned again. On a
        real server that is precisely the multi-hour GC or sync whose outcome
        matters most, so the anchor is pinned to the oldest run we still
        believe to be unfinished.
        """
        t = self._t.get(worker_type)
        if not t or t.get("truncated", True) or t.get("polled_at") is None:
            return None
        running = [e["running_since"] for e in t["workers"].values()
                   if e.get("running_since") is not None]
        return min([t["polled_at"], *running])

    def truncated(self, worker_type: str) -> bool:
        t = self._t.get(worker_type)
        return True if t is None else bool(t.get("truncated", True))

    def oldest_seen(self, worker_type: str) -> int | None:
        t = self._t.get(worker_type)
        return None if t is None else t.get("oldest_seen")

    def latest(self, worker_type: str, match: Callable[[str], bool]):
        """Newest finished run of this type whose worker id matches."""
        best = None
        for wid, entry in self._items(worker_type, match):
            if entry.get("endtime") is None:
                continue
            if best is None or entry["starttime"] > best["starttime"]:
                best = entry
        return dict(best) if best else None

    def running(self, worker_type: str, match: Callable[[str], bool]):
        """Start time of a matching run still in flight, or None."""
        best = None
        for wid, entry in self._items(worker_type, match):
            since = entry.get("running_since")
            if since is not None and (best is None or since > best):
                best = since
        return best

    def latest_verify_activity(self, store: str) -> int:
        """Newest end time of any verification touching `store`."""
        newest = 0
        for wtype in _VERIFY_TYPES:
            last = self.latest(
                wtype, lambda w: w == store or w.startswith(store + ":"))
            if last and last.get("endtime"):
                newest = max(newest, int(last["endtime"]))
        return newest

    def _items(self, worker_type: str, match: Callable[[str], bool]):
        t = self._t.get(worker_type)
        if not t:
            return
        for wid, entry in t["workers"].items():
            if match(wid):
                yield wid, entry
