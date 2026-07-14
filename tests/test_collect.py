import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from conftest import load_module
from fake_pbs import FakePbs, sample_routes, DAY
collect = load_module("libexec/oposs_pbs_collect.py", "oposs_pbs_collect")
cache = load_module("libexec/oposs_pbs_cache.py", "oposs_pbs_cache")

NOW = 1_000_000


def _opts():
    return collect.Options(include=[], exclude=[], task_limit=1000,
                           piggyback_template="{id}", piggyback_regex=None,
                           no_piggyback=set())


def test_collect_builds_all_sections():
    c = FakePbs(sample_routes(NOW))
    host, pig = collect.collect(c, _opts(), cache.StateCache({}), NOW)

    assert host["oposs_pbs_server"]["reachable"] is True
    assert host["oposs_pbs_server"]["node"] == "localhost"
    ds = host["oposs_pbs_datastore"]["main"]
    assert ds["used"] == 250 and ds["group_count"] == 1 and ds["backup_count"] == 7
    assert ds["gc"]["status"] == "OK"
    assert ds["gc"]["index_data_bytes"] == 4000 and ds["gc"]["disk_bytes"] == 1000
    jobs = host["oposs_pbs_jobs"]
    assert jobs["sync"][0]["last_run"]["status"] == "OK"
    assert jobs["prune"][0]["last_run"]["status"] == "OK"

    assert len(pig) == 1
    pbhost, rec = pig[0]
    assert pbhost == "100"
    assert rec["interval"] == DAY and rec["interval_known"] is True
    assert rec["verify_state"] == "ok"
    assert rec["data_size"] == 41_000_000_000
    assert rec["last_backup"] == NOW - 100


def test_node_index_not_probed_localhost_alias_used():
    """The PBS /nodes index needs more than the Audit privilege our
    least-privilege monitoring token holds, so probing it only yields a 403
    (logged server-side every run). We must never call it: the always-valid
    'localhost' alias is used for node-scoped paths instead."""
    c = FakePbs(sample_routes(NOW))
    host, _ = collect.collect(c, _opts(), cache.StateCache({}), NOW)
    assert host["oposs_pbs_server"]["node"] == "localhost"
    assert not any(p == "/nodes" for p, _ in c.calls)      # never probed
    assert any(p == "/nodes/localhost/tasks" for p, _ in c.calls)


def test_piggyback_uses_guest_name_from_snapshot_comment():
    """With the {guest} template the backup lands on the PVE guest name (from
    the snapshot comment), matching the Proxmox VE agent's piggyback host —
    not the numeric VMID."""
    opts = _opts(); opts.piggyback_template = "{guest}"
    c = FakePbs(sample_routes(NOW))
    _, pig = collect.collect(c, opts, cache.StateCache({}), NOW)
    assert pig[0][0] == "web01"          # snapshot comment, not backup-id "100"


def test_guest_name_persists_when_refresh_skipped():
    """The guest name is cached, so a later run that does not re-enumerate
    snapshots still maps the host correctly."""
    opts = _opts(); opts.piggyback_template = "{guest}"
    st = cache.StateCache({})
    collect.collect(FakePbs(sample_routes(NOW)), opts, st, NOW)  # warm cache
    # Second run: nothing changed -> no /snapshots call, guest from cache.
    c = FakePbs(sample_routes(NOW))
    _, pig = collect.collect(c, opts, st, NOW)
    assert not any(p.endswith("/snapshots") for p, _ in c.calls)
    assert pig[0][0] == "web01"


def test_rollup_section_lists_every_group():
    """A host-level roll-up section carries one record per backup group, with the
    resolved piggyback host name, for the single 'PBS Backups' summary service."""
    c = FakePbs(_two_group_routes(NOW))
    host, pig = collect.collect(c, _opts(), cache.StateCache({}), NOW)
    rollup = host["oposs_pbs_backup_rollup"]
    assert len(rollup) == len(pig) == 2
    r0 = rollup[0]
    assert {"host", "datastore", "ns", "backup_type", "backup_id",
            "last_backup", "interval", "interval_known", "verify_state"} <= set(r0)
    # host is the resolved piggyback name (default {id} in tests here -> "100")
    assert {r["backup_id"] for r in rollup} == {"100", "200"}


def test_unmapped_vms_reported_in_server_section():
    """vm/ct groups without a guest name (empty snapshot comment) fall back to
    the VMID and are reported so the operator can spot the gap; host/ backups
    (whose id already is the name) are not flagged."""
    routes = sample_routes(NOW)
    routes["/admin/datastore/main/groups"] = [
        {"backup-type": "vm", "backup-id": "116", "last-backup": NOW - 100,
         "backup-count": 3},                       # no guest name -> unmapped
        {"backup-type": "host", "backup-id": "services-argus",
         "last-backup": NOW - 100, "backup-count": 3},  # host id == name, ok
    ]
    # snapshots carry no comment -> no guest name resolved
    routes["/admin/datastore/main/snapshots"] = [
        {"backup-type": "vm", "backup-id": "116", "backup-time": NOW - 100,
         "size": 1}]
    host, _ = collect.collect(FakePbs(routes), _opts(), cache.StateCache({}), NOW)
    unmapped = host["oposs_pbs_server"]["unmapped_backups"]
    ids = {u["backup"] for u in unmapped}
    assert "vm/116" in ids
    assert "host/services-argus" not in ids


def test_snapshots_not_refetched_when_unchanged():
    routes = sample_routes(NOW)
    c = FakePbs(routes)
    st = cache.StateCache({})
    collect.collect(c, _opts(), st, NOW)
    first = sum(1 for p, _ in c.calls if p.endswith("/snapshots"))
    collect.collect(c, _opts(), st, NOW)  # same last_backup + verify activity
    second = sum(1 for p, _ in c.calls if p.endswith("/snapshots"))
    assert first == 1 and second == 1  # no extra snapshot call on 2nd run


def test_datastore_filtering():
    opts = _opts(); opts.exclude = ["^main$"]
    c = FakePbs(sample_routes(NOW))
    host, pig = collect.collect(c, opts, cache.StateCache({}), NOW)
    assert host["oposs_pbs_datastore"] == {} and pig == []


class FailingClient:
    """Fake client that raises on first get() call to simulate auth/connection failure."""
    def get(self, path, params=None):
        raise RuntimeError("401 unauthorized")


def test_collect_handles_api_failure():
    """Test that collect() handles connection/auth failures gracefully."""
    c = FailingClient()
    host, pig = collect.collect(c, _opts(), cache.StateCache({}), NOW)

    assert host["oposs_pbs_server"]["reachable"] is False
    assert "401" in host["oposs_pbs_server"]["error"]
    assert "oposs_pbs_datastore" not in host
    assert "oposs_pbs_jobs" not in host
    assert pig == []


class _FailPath(FakePbs):
    """FakePbs that raises for any path containing a given substring."""
    def __init__(self, routes, fail_substr):
        super().__init__(routes)
        self._fail = fail_substr

    def get(self, path, params=None):
        if self._fail in path:
            raise RuntimeError(f"read timeout on {path}")
        return super().get(path, params)


def test_group_refresh_failure_does_not_abort(capsys):
    """A slow/failing /snapshots call must not crash the whole collect()."""
    c = _FailPath(sample_routes(NOW), "/snapshots")
    host, pig = collect.collect(c, _opts(), cache.StateCache({}), NOW)

    # Reachable, other sections still produced.
    assert host["oposs_pbs_server"]["reachable"] is True
    assert "oposs_pbs_datastore" in host
    assert host["oposs_pbs_datastore"]["main"]["group_count"] == 1
    # The group is still emitted, but degraded (unknown cadence, no size).
    assert len(pig) == 1
    _, rec = pig[0]
    assert rec["interval_known"] is False
    assert rec["data_size"] == 0
    assert rec["verify_state"] == "none"
    assert rec["last_backup"] == NOW - 100  # group-level data is intact
    # Failure is surfaced on stderr, never on stdout.
    assert "snapshot" in capsys.readouterr().err.lower()


def test_group_refresh_failure_reuses_cached_value():
    """On refresh failure, a prior cache entry is reused (stale, not lost)."""
    good = FakePbs(sample_routes(NOW))
    st = cache.StateCache({})
    collect.collect(good, _opts(), st, NOW)  # warm the cache

    # Now a new backup appears (last_backup changes) but /snapshots fails.
    routes = sample_routes(NOW)
    routes["/admin/datastore/main/groups"] = [
        {"backup-type": "vm", "backup-id": "100", "last-backup": NOW,
         "backup-count": 8, "comment": "web01"}]
    c = _FailPath(routes, "/snapshots")
    host, pig = collect.collect(c, _opts(), st, NOW)

    _, rec = pig[0]
    # Stale but usable cadence/size preserved from the earlier successful run.
    assert rec["interval_known"] is True
    assert rec["data_size"] == 41_000_000_000
    # Cache not overwritten, so the next run will retry the refresh.
    assert st.needs_refresh(
        cache.group_key("main", "", "vm", "100"), NOW, 0) is True


def test_store_failure_is_isolated(capsys):
    """A failure enumerating one datastore must not abort the agent."""
    c = _FailPath(sample_routes(NOW), "/status")
    host, pig = collect.collect(c, _opts(), cache.StateCache({}), NOW)

    assert host["oposs_pbs_server"]["reachable"] is True
    assert host["oposs_pbs_jobs"]["sync"]  # jobs still collected
    assert host["oposs_pbs_datastore"] == {}  # the broken store is skipped
    assert "main" in capsys.readouterr().err


# --- B: per-run refresh budget ---------------------------------------------

class _FakeBudget:
    """Duck-typed budget: allows `n` refreshes, then blocks the rest."""
    def __init__(self, n):
        self.n = n
    def allow(self):
        return self.n > 0
    def record(self, _dt):
        self.n -= 1


def _two_group_routes(now):
    routes = sample_routes(now)
    routes["/admin/datastore/main/groups"] = [
        {"backup-type": "vm", "backup-id": "100", "last-backup": now - 100,
         "backup-count": 7, "comment": "web01"},
        {"backup-type": "vm", "backup-id": "200", "last-backup": now - 50,
         "backup-count": 5, "comment": "web02"},
    ]

    def snaps(params):
        bid = params.get("backup-id")
        return [{"backup-type": "vm", "backup-id": bid, "backup-time": now - 100 - DAY,
                 "size": 10_000_000_000},
                {"backup-type": "vm", "backup-id": bid, "backup-time": now - 50,
                 "size": 11_000_000_000, "verification": {"state": "ok", "upid": "x"}}]
    routes["/admin/datastore/main/snapshots"] = snaps
    return routes


def test_budget_zero_skips_all_snapshot_calls():
    c = FakePbs(_two_group_routes(NOW))
    st = cache.StateCache({})
    host, pig = collect.collect(c, _opts(), st, NOW, budget=_FakeBudget(0))

    snap_calls = sum(1 for p, _ in c.calls if p.endswith("/snapshots"))
    assert snap_calls == 0                       # nothing expensive attempted
    assert len(pig) == 2 and all(not r["interval_known"] for _, r in pig)
    assert all(r["data_size"] == 0 for _, r in pig)
    # Both groups stay dirty so a later run retries them.
    for bid in ("100", "200"):
        assert st.needs_refresh(cache.group_key("main", "", "vm", bid),
                                NOW, 0) is True


def test_budget_allows_partial_refresh():
    c = FakePbs(_two_group_routes(NOW))
    st = cache.StateCache({})
    host, pig = collect.collect(c, _opts(), st, NOW, budget=_FakeBudget(1))

    snap_calls = sum(1 for p, _ in c.calls if p.endswith("/snapshots"))
    assert snap_calls == 1                       # exactly one group refreshed
    by_id = {r["backup_id"]: r for _, r in pig}
    fresh = [r for r in by_id.values() if r["interval_known"]]
    degraded = [r for r in by_id.values() if not r["interval_known"]]
    assert len(fresh) == 1 and len(degraded) == 1
    assert fresh[0]["data_size"] == 11_000_000_000


# --- C: cadence from accumulated last-backup observations -------------------

def test_interval_derived_from_observations_without_fetch():
    """Even when /snapshots never succeeds, a cadence emerges from the
    last-backup timestamps observed across successive runs."""
    st = cache.StateCache({})
    # Run 1: one backup observed, budget blocks the fetch -> cadence unknown.
    r1 = sample_routes(NOW)
    r1["/admin/datastore/main/groups"] = [
        {"backup-type": "vm", "backup-id": "100", "last-backup": NOW - DAY,
         "backup-count": 1, "comment": "web01"}]
    _, pig1 = collect.collect(FakePbs(r1), _opts(), st, NOW, budget=_FakeBudget(0))
    assert pig1[0][1]["interval_known"] is False

    # Run 2: a second backup one DAY later; still no fetch, but two
    # observations now yield the cadence.
    r2 = sample_routes(NOW)
    r2["/admin/datastore/main/groups"] = [
        {"backup-type": "vm", "backup-id": "100", "last-backup": NOW,
         "backup-count": 2, "comment": "web01"}]
    _, pig2 = collect.collect(FakePbs(r2), _opts(), st, NOW, budget=_FakeBudget(0))
    rec = pig2[0][1]
    assert rec["interval_known"] is True
    assert rec["interval"] == DAY


# --- A: incremental persistence --------------------------------------------

def test_save_callback_invoked_during_collection():
    calls = {"n": 0}
    c = FakePbs(sample_routes(NOW))
    collect.collect(c, _opts(), cache.StateCache({}), NOW,
                    save=lambda: calls.__setitem__("n", calls["n"] + 1))
    assert calls["n"] >= 1
