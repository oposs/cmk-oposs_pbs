import json
from conftest import load_module
from cmk.agent_based.v2 import State, Metric
m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")

NOW = 1_000_000
SECTION = {"main": {
    "total": 1000, "used": 950, "avail": 50,
    "group_count": 3, "backup_count": 21,
    "gc": {"status": "OK", "endtime": NOW - 3600, "running": False,
           "index_data_bytes": 4000, "disk_bytes": 1000}}}
DEFAULTS = {"usage_levels": ("fixed", (80.0, 90.0)),
            "gc_age_levels": ("no_levels", None)}


def _metrics(results):
    return {r.name: r.value for r in results if isinstance(r, Metric)}


def test_datastore_usage_crit_and_metrics(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_datastore("main", DEFAULTS, SECTION))
    states = [r.state for r in res if hasattr(r, "state")]
    assert State.CRIT in states                       # 95% > 90%
    mt = _metrics(res)
    assert mt["oposs_pbs_datastore_used"] == 950
    assert mt["oposs_pbs_datastore_used_pct"] == 95.0
    assert mt["oposs_pbs_dedup_factor"] == 4.0
    assert mt["oposs_pbs_backup_count"] == 21


def test_datastore_gc_failure_warns(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    sec = json.loads(json.dumps(SECTION))
    sec["main"]["gc"]["status"] = "some error"
    res = list(m.check_oposs_pbs_datastore("main", DEFAULTS, sec))
    assert any(r.state is State.WARN and "GC" in (r.summary or r.notice or "")
               for r in res if hasattr(r, "state"))


def test_datastore_missing_item():
    assert list(m.check_oposs_pbs_datastore("nope", DEFAULTS, SECTION)) == []


# --- garbage collection reporting -------------------------------------------

DAY = 86400


def _gc_section(**gc):
    sec = json.loads(json.dumps(SECTION))
    sec["main"]["gc"] = {"index_data_bytes": 4000, "disk_bytes": 1000,
                         "status": None, "endtime": None, "running": False,
                         "running_since": None, "history_truncated": False,
                         "history_start": None, **gc}
    return sec


def _summaries(results):
    return " | ".join(r.summary or r.notice or ""
                      for r in results if hasattr(r, "state"))


def _run(sec, params=None, monkeypatch=None, now=NOW):
    if monkeypatch:
        monkeypatch.setattr(m.time, "time", lambda: now)
    return list(m.check_oposs_pbs_datastore("main", params or DEFAULTS, sec))


def test_gc_never_run_says_never_not_yet(monkeypatch):
    """With the whole task history in reach, "never" is a fact we can state."""
    res = _run(_gc_section(history_truncated=False), monkeypatch=monkeypatch)
    text = _summaries(res)
    assert "never" in text.lower()
    assert State.UNKNOWN in [r.state for r in res if hasattr(r, "state")]


def test_gc_out_of_reach_reports_the_horizon_instead_of_claiming_never(monkeypatch):
    """Regression: the check said "GC not run yet" when all it knew was that no
    GC run was within the task history it had read."""
    res = _run(_gc_section(history_truncated=True,
                           history_start=NOW - 3 * DAY), monkeypatch=monkeypatch)
    text = _summaries(res)
    assert "never" not in text.lower()
    assert "3 days" in text and "history" in text.lower()


def test_gc_never_run_state_is_configurable(monkeypatch):
    params = dict(DEFAULTS, no_gc_state="ok")
    res = _run(_gc_section(), params, monkeypatch)
    gc_states = [r.state for r in res if hasattr(r, "state")
                 and "GC" in (r.summary or r.notice or "")]
    assert gc_states == [State.OK]


def test_gc_age_is_still_checked_while_a_gc_is_running(monkeypatch):
    """Regression: a running GC suppressed the age check entirely, so a server
    whose GC had not succeeded for months reported OK."""
    params = dict(DEFAULTS, gc_age_levels=("fixed", (2 * DAY, 7 * DAY)))
    res = _run(_gc_section(status="OK", endtime=NOW - 100 * DAY,
                           running=True, running_since=NOW - 2 * DAY),
               params, monkeypatch)
    assert State.CRIT in [r.state for r in res if hasattr(r, "state")]
    assert "running" in _summaries(res).lower()


def test_gc_running_duration_is_reported(monkeypatch):
    res = _run(_gc_section(status="OK", endtime=NOW - 3600,
                           running=True, running_since=NOW - 5 * 3600),
               monkeypatch=monkeypatch)
    assert "5 hours" in _summaries(res)


def test_gc_failure_is_reported_even_while_the_next_gc_runs(monkeypatch):
    """A GC that aborts and is retried must not be hidden by the retry."""
    res = _run(_gc_section(status="unknown", endtime=NOW - DAY,
                           running=True, running_since=NOW - 3600),
               monkeypatch=monkeypatch)
    assert State.WARN in [r.state for r in res if hasattr(r, "state")]
    assert "unknown" in _summaries(res)


def test_gc_section_from_an_older_agent_does_not_claim_never(monkeypatch):
    """An agent predating the reach fields says nothing about how far back it
    looked, so the check must not turn that silence into "never ran"."""
    sec = json.loads(json.dumps(SECTION))
    sec["main"]["gc"] = {"status": None, "endtime": None, "running": False,
                         "index_data_bytes": 4000, "disk_bytes": 1000}
    res = _run(sec, monkeypatch=monkeypatch)
    text = _summaries(res)
    assert "never" not in text.lower()
    assert "No GC run found" in text


def test_gc_age_is_measured_from_the_last_successful_run(monkeypatch):
    """Regression: the age was only checked when the *last attempt* succeeded,
    so a GC that aborts nightly kept the configured age levels permanently
    inactive -- exactly when they were needed."""
    params = dict(DEFAULTS, gc_age_levels=("fixed", (2 * DAY, 7 * DAY)))
    res = _run(_gc_section(status="unknown", endtime=NOW - DAY,
                           last_ok_endtime=NOW - 168 * DAY), params, monkeypatch)
    states = [r.state for r in res if hasattr(r, "state")]
    assert State.CRIT in states
    text = _summaries(res)
    assert "Last successful GC" in text and "168 days" in text
    assert "Last GC failed" in text          # the attempt is reported too
    assert "oposs_pbs_gc_age" in [r.name for r in res if isinstance(r, Metric)]


def test_gc_age_metric_is_emitted_even_when_the_last_attempt_failed(monkeypatch):
    res = _run(_gc_section(status="unknown", endtime=NOW - DAY,
                           last_ok_endtime=NOW - 3 * DAY), monkeypatch=monkeypatch)
    mt = {r.name: r.value for r in res if isinstance(r, Metric)}
    assert mt["oposs_pbs_gc_age"] == 3 * DAY


def test_gc_that_only_ever_failed_says_so(monkeypatch):
    res = _run(_gc_section(status="unknown", endtime=NOW - DAY,
                           last_ok_endtime=None, history_truncated=False),
               monkeypatch=monkeypatch)
    text = _summaries(res)
    assert "No successful GC run" in text
    assert "never" not in text.lower()       # it did run, it just never worked


def test_successful_gc_reports_its_age_as_before(monkeypatch):
    params = dict(DEFAULTS, gc_age_levels=("fixed", (2 * DAY, 7 * DAY)))
    res = _run(_gc_section(status="OK", endtime=NOW - 3600,
                           last_ok_endtime=NOW - 3600), params, monkeypatch)
    gc_results = [r for r in res if hasattr(r, "state")
                  and "GC" in (r.summary or r.notice or "")]
    assert [r.state for r in gc_results] == [State.OK]
    assert "Last successful GC" in _summaries(res)
    assert "failed" not in _summaries(res)
