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
    assert host["oposs_pbs_server"]["node"] == "pbs01"
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
