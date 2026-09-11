from conftest import load_module
u = load_module("libexec/oposs_pbs_util.py", "oposs_pbs_util")


def test_median_interval_daily():
    day = 86400
    assert u.median_interval([0, day, 2 * day, 3 * day]) == day
    assert u.median_interval([100]) is None
    assert u.median_interval([]) is None


def test_dedup_factor():
    assert u.dedup_factor(1000.0, 250.0) == 4.0
    assert u.dedup_factor(1000.0, 0) is None
    assert u.dedup_factor(None, 10.0) is None


def test_piggyback_host_template_and_regex():
    grp = {"backup-type": "vm", "backup-id": "100", "comment": "web01"}
    assert u.piggyback_host("{id}", grp, None) == "100"
    assert u.piggyback_host("{type}-{id}", grp, None) == "vm-100"
    assert u.piggyback_host("{comment}", grp, None) == "web01"
    assert u.piggyback_host("{id}", grp, (r"^(\d+)$", r"vm-\1")) == "vm-100"


def test_piggyback_host_guest_placeholder_and_fallback():
    """{guest} is the PVE guest name (the backup's snapshot comment) — the same
    string the built-in Proxmox VE agent piggybacks under. When there is no
    guest name we must fall back to the backup-id so the host is never empty."""
    grp = {"backup-type": "vm", "backup-id": "102", "comment": ""}
    assert u.piggyback_host("{guest}", grp, None, guest="web-volki-01") == "web-volki-01"
    assert u.piggyback_host("{guest}", grp, None, guest="  db1 ") == "db1"   # trimmed
    assert u.piggyback_host("{guest}", grp, None, guest="") == "102"         # fallback
    assert u.piggyback_host("{guest}", grp, None, guest=None) == "102"       # fallback


def test_group_path_is_the_ignore_match_target():
    """The ignore filter matches against '<store>/<ns>/<type>/<id>'. With no
    namespace this collapses to a double slash, which patterns must be able to
    rely on."""
    assert u.group_path("store1", "", "vm", "105") == "store1//vm/105"
    assert u.group_path("store1", "tenantA", "ct", "210") == "store1/tenantA/ct/210"
    assert u.group_path("backup2", "", "host", "oldbox") == "backup2//host/oldbox"


def test_median_interval_recent_ignores_older_gaps():
    """`recent` limits the median to the newest N gaps, so a pruned-out old end
    cannot stretch the reported cadence."""
    day = 86400
    times = [0, 30 * day, 60 * day, 90 * day, 120 * day,
             121 * day, 122 * day, 123 * day]
    assert u.median_interval(times) == 30 * day
    assert u.median_interval(times, recent=3) == day


# --- TaskHistory: findings carried across runs ------------------------------

GC = "garbage_collection"


def _task(wtype, wid, start, end=None, status=None):
    t = {"worker_type": wtype, "worker_id": wid, "starttime": start}
    if end is not None:
        t["endtime"] = end
        t["status"] = status
    return t


def test_task_history_keeps_finding_after_it_leaves_the_window():
    """The whole point of caching findings: a GC seen once stays known even
    when a later poll no longer returns it."""
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "main", 1000, 1100, "OK")], limit=10, now=2000)
    assert h.latest(GC, lambda w: w == "main")["endtime"] == 1100
    h.absorb(GC, [], limit=10, now=9000)          # nothing new since
    assert h.latest(GC, lambda w: w == "main")["endtime"] == 1100


def test_task_history_newer_run_replaces_older_finding():
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "main", 1000, 1100, "OK")], limit=10, now=2000)
    h.absorb(GC, [_task(GC, "main", 5000, 5100, "some error")], limit=10, now=6000)
    last = h.latest(GC, lambda w: w == "main")
    assert last["status"] == "some error" and last["endtime"] == 5100


def test_task_history_running_then_finished():
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "main", 1000)], limit=10, now=2000)
    assert h.running(GC, lambda w: w == "main") == 1000
    assert h.latest(GC, lambda w: w == "main") is None
    h.absorb(GC, [_task(GC, "main", 1000, 8000, "OK")], limit=10, now=9000)
    assert h.running(GC, lambda w: w == "main") is None
    assert h.latest(GC, lambda w: w == "main")["endtime"] == 8000


def test_since_anchor_reaches_back_to_an_unfinished_run():
    """PBS filters `since` on a task's START time. A GC that started two days
    ago and is still running would never be seen again if the next poll asked
    only for tasks since the last poll -- its completion would be lost."""
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "main", 1000)], limit=10, now=2000)
    assert h.since_anchor(GC) == 1000


def test_since_anchor_is_last_poll_when_nothing_runs():
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "main", 1000, 1100, "OK")], limit=10, now=2000)
    assert h.since_anchor(GC) == 2000


def test_since_anchor_none_until_full_history_was_read():
    """A cold cache must do one unbounded read; only a poll that came back
    short of the limit proves the whole history was seen."""
    h = u.TaskHistory()
    assert h.since_anchor(GC) is None
    h.absorb(GC, [_task(GC, "main", i * 10, i * 10 + 1, "OK")
                  for i in range(1, 4)], limit=3, now=2000)
    assert h.truncated(GC) is True
    assert h.since_anchor(GC) is None          # still truncated -> read fully again


def test_task_history_round_trips_through_the_state_cache():
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "main", 1000, 1100, "OK")], limit=10, now=2000)
    again = u.TaskHistory(h.as_state())
    assert again.latest(GC, lambda w: w == "main")["endtime"] == 1100
    assert again.since_anchor(GC) == 2000


def test_task_history_forgets_workers_that_no_longer_exist():
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "gone", 1000, 1100, "OK"),
                  _task(GC, "main", 1000, 1100, "OK")], limit=10, now=2000)
    h.retain(GC, {"main"})
    assert h.latest(GC, lambda w: w == "gone") is None
    assert h.latest(GC, lambda w: w == "main") is not None


def test_task_history_oldest_seen_is_the_reporting_horizon():
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "other", 4000, 4100, "OK")], limit=1, now=5000)
    assert h.truncated(GC) is True
    assert h.oldest_seen(GC) == 4000


def test_task_history_forgets_jobs_that_were_deleted():
    """Job worker ids are only reachable through the same predicate the job
    lookup uses, so pruning is expressed with those predicates."""
    h = u.TaskHistory()
    h.absorb("syncjob", [_task("syncjob", "r:s:d:ns:keep", 1000, 1100, "OK"),
                         _task("syncjob", "r:s:d:ns:gone", 1000, 1100, "OK")],
             limit=10, now=2000)
    h.retain_matching("syncjob", [lambda w: w.rsplit(":", 1)[-1] == "keep"])
    assert h.latest("syncjob", lambda w: w.endswith("gone")) is None
    assert h.latest("syncjob", lambda w: w.endswith("keep")) is not None


def test_retain_matching_with_no_jobs_left_clears_the_type():
    h = u.TaskHistory()
    h.absorb("syncjob", [_task("syncjob", "r:s:d:ns:gone", 1000, 1100, "OK")],
             limit=10, now=2000)
    h.retain_matching("syncjob", [])
    assert h.latest("syncjob", lambda w: True) is None


def test_task_history_remembers_the_last_successful_run_separately():
    """A failing run must not erase when the job last actually worked --
    otherwise a nightly GC that aborts every time looks the same as one that
    failed once last night."""
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "main", 1000, 1100, "OK")], limit=10, now=2000)
    h.absorb(GC, [_task(GC, "main", 5000, 5100, "unknown")], limit=10, now=6000)
    assert h.latest(GC, lambda w: w == "main")["status"] == "unknown"
    assert h.latest_ok(GC, lambda w: w == "main")["endtime"] == 1100


def test_last_successful_run_advances_on_a_new_success():
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "main", 1000, 1100, "OK"),
                  _task(GC, "main", 5000, 5100, "OK")], limit=10, now=6000)
    assert h.latest_ok(GC, lambda w: w == "main")["endtime"] == 5100


def test_latest_ok_is_none_when_nothing_ever_succeeded():
    h = u.TaskHistory()
    h.absorb(GC, [_task(GC, "main", 1000, 1100, "unknown")], limit=10, now=2000)
    assert h.latest_ok(GC, lambda w: w == "main") is None
