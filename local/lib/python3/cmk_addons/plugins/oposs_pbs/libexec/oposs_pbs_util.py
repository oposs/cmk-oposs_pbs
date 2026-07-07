"""Pure helpers for the PBS collector: intervals, dedup, task matching."""
from __future__ import annotations
import re
from statistics import median
from typing import Callable

_VERIFY_TYPES = {"verificationjob", "verify", "verify_group", "verify_snapshot"}


def median_interval(times: list[int]) -> int | None:
    if len(times) < 2:
        return None
    ordered = sorted(times)
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
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


def piggyback_host(template: str, group: dict, regex: tuple[str, str] | None) -> str:
    name = template.format(
        id=group.get("backup-id", ""),
        type=group.get("backup-type", ""),
        comment=group.get("comment", "") or "",
    )
    if regex:
        pattern, repl = regex
        name = re.sub(pattern, repl, name)
    return name


def _finished(task: dict) -> bool:
    return task.get("endtime") is not None and task.get("status") is not None


def latest_task(tasks, worker_type, match: Callable[[str], bool]):
    latest = None
    for t in tasks:
        if t.get("worker_type") != worker_type or not _finished(t):
            continue
        if not match(t.get("worker_id", "") or ""):
            continue
        if latest is None or t["starttime"] > latest["starttime"]:
            latest = t
    return latest


def task_running(tasks, worker_type, match: Callable[[str], bool]) -> bool:
    for t in tasks:
        if t.get("worker_type") != worker_type:
            continue
        if t.get("endtime") is None and match(t.get("worker_id", "") or ""):
            return True
    return False


def latest_verify_activity(tasks, store: str) -> int:
    newest = 0
    for t in tasks:
        if t.get("worker_type") not in _VERIFY_TYPES or not _finished(t):
            continue
        if (t.get("worker_id", "") or "").startswith(store):
            newest = max(newest, int(t["endtime"]))
    return newest
