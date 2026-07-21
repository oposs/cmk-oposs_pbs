# Per-backup-group PBS Backup services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover one `PBS Backup` service per backup group per piggyback host (fully-qualified item), and show the observed cadence in the service summary.

**Architecture:** The collector already emits one piggyback record per backup group. The fix is entirely in the check plugin: make the service item fully qualified so discovery and the check lookup key on the backup group rather than only the datastore, and promote the cadence from a hidden `notice` to the summary line. The ruleset item title is relabelled to match.

**Tech Stack:** Python 3.12, Checkmk `cmk.agent_based.v2` / `cmk.rulesets.v1` APIs, pytest with the repo's `conftest.load_module` stub harness.

## Global Constraints

- Comments, identifiers, key names in English (UI/docs may be localized — not applicable here).
- Run pytest with at most 4 cores: `pytest -n0` or plain `pytest` (repo default is serial; do not add `-n`).
- Checkmk 2.3.x plugin APIs only; no new dependencies.
- This is a **breaking** change (service rename) — must be recorded in `CHANGES.md`.

---

### Task 1: Fully-qualified backup service item + cadence in summary

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/agent_based/oposs_pbs.py` (`_backup_item`, `check_oposs_pbs_backup`)
- Test: `tests/test_check_backup.py`

**Interfaces:**
- Consumes: piggyback record dict fields `datastore`, `ns`, `backup_type`, `backup_id`, `last_backup`, `interval`, `interval_known`, `backup_count`, `data_size`, `verify_state` (already produced by the collector, unchanged).
- Produces: `_backup_item(rec) -> str` returning `"{datastore}/{ns} {backup_type}/{backup_id}"` when `ns` is truthy, else `"{datastore} {backup_type}/{backup_id}"`. Used by both `discover_oposs_pbs_backup` and `check_oposs_pbs_backup`.

- [ ] **Step 1: Update the existing tests to the new item names and add new coverage**

In `tests/test_check_backup.py`, replace the discovery test and the multi-record regression test, and add two new tests. The `rec()` helper already defaults to `backup_type="vm"`, `backup_id="100"`, `ns=""`, so the fully-qualified item for a default record is `"main vm/100"`.

Replace `test_discovery_yields_one_service_per_record`:

```python
def test_discovery_yields_one_service_per_record():
    section = [rec(), rec(datastore="backup2", verify_state="failed",
                          last_backup=NOW - 5 * DAY)]
    services = list(m.discover_oposs_pbs_backup(section))
    assert [s.item for s in services] == ["main vm/100", "backup2 vm/100"]


def test_item_includes_namespace_when_present():
    services = list(m.discover_oposs_pbs_backup([rec(ns="prod", backup_id="101")]))
    assert [s.item for s in services] == ["main/prod vm/101"]


def test_two_groups_one_datastore_are_distinct_services(monkeypatch):
    # A node backing up several groups into one datastore must yield one
    # service per group, each keyed on its own age -- not collapse to one.
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    section = [rec(backup_id="100", last_backup=NOW - 3600),
               rec(backup_id="101", last_backup=NOW - 5 * DAY)]
    items = [s.item for s in m.discover_oposs_pbs_backup(section)]
    assert items == ["main vm/100", "main vm/101"]

    fresh = list(m.check_oposs_pbs_backup("main vm/100", DEFAULTS, section))
    assert State.WARN not in _states(fresh) and State.CRIT not in _states(fresh)
    stale = list(m.check_oposs_pbs_backup("main vm/101", DEFAULTS, section))
    assert State.CRIT in _states(stale)


def test_cadence_shown_in_summary(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main vm/100", DEFAULTS, [rec()]))
    summary = " ".join(r.summary for r in res
                       if getattr(r, "summary", ""))
    assert "cadence ~1 day" in summary
    assert "(assumed)" not in summary


def test_assumed_cadence_labelled(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup(
        "main vm/100", DEFAULTS,
        [rec(interval=None, interval_known=False)]))
    summary = " ".join(r.summary for r in res
                       if getattr(r, "summary", ""))
    assert "(assumed)" in summary
```

Replace `test_multi_record_section_second_datastore_not_dropped` body's item strings:

```python
def test_multi_record_section_second_datastore_not_dropped(monkeypatch):
    # Regression: a guest backed up to multiple datastores produces multiple
    # records merged into one section. Each must remain individually checkable.
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    section = [rec(), rec(datastore="backup2", verify_state="failed",
                          last_backup=NOW - 5 * DAY)]
    res_backup2 = list(m.check_oposs_pbs_backup("backup2 vm/100", DEFAULTS, section))
    assert State.CRIT in _states(res_backup2)

    res_main = list(m.check_oposs_pbs_backup("main vm/100", DEFAULTS, section))
    assert State.WARN not in _states(res_main) and State.CRIT not in _states(res_main)
```

Also update the four single-record check tests (`test_fresh_backup_ok`,
`test_missed_two_intervals_warns`, `test_missed_three_intervals_crit`,
`test_verify_failed_is_crit`, `test_unknown_interval_uses_fallback`) — change
their first `check_oposs_pbs_backup` argument from `"main"` to `"main vm/100"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_check_backup.py -q`
Expected: FAIL — the old `_backup_item` returns `"main"`, so lookups by
`"main vm/100"` find no record and the new/updated tests fail (no CRIT/WARN,
missing cadence summary).

- [ ] **Step 3: Rewrite `_backup_item` to be fully qualified**

In `agent_based/oposs_pbs.py`:

```python
def _backup_item(rec) -> str:
    ns = rec.get("ns")
    store = rec.get("datastore", "?")
    group = f"{rec.get('backup_type', '?')}/{rec.get('backup_id', '?')}"
    return f"{store}/{ns} {group}" if ns else f"{store} {group}"
```

- [ ] **Step 4: Promote cadence to the summary in `check_oposs_pbs_backup`**

Locate this block:

```python
    yield from check_levels(
        age, levels_upper=levels, metric_name="oposs_pbs_backup_age",
        label="Last backup age", render_func=render.timespan)
    yield Result(state=State.OK, notice=(
        f"Cadence ~{render.timespan(interval)}{suffix}, "
        f"{rec.get('backup_count', 0)} snapshots"))
```

Replace the `suffix` assignment and the `Result` above with a summary fragment
for cadence and a separate notice for the snapshot count. The `suffix`
definition earlier in the function currently reads:

```python
    suffix = "" if rec.get("interval_known") else " (assumed cadence)"
```

Change it to:

```python
    suffix = "" if rec.get("interval_known") else " (assumed)"
```

Then replace the `check_levels(...)` + `Result(... notice=...)` pair with:

```python
    yield from check_levels(
        age, levels_upper=levels, metric_name="oposs_pbs_backup_age",
        label="Last backup age", render_func=render.timespan)
    yield Result(state=State.OK,
                 summary=f"cadence ~{render.timespan(interval)}{suffix}")
    yield Result(state=State.OK,
                 notice=f"{rec.get('backup_count', 0)} snapshots")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_check_backup.py -q`
Expected: PASS (all tests, including the two new cadence tests and the
two-groups-one-datastore test).

- [ ] **Step 6: Commit**

```bash
git add local/lib/python3/cmk_addons/plugins/oposs_pbs/agent_based/oposs_pbs.py tests/test_check_backup.py
git commit -m "fix: one PBS Backup service per backup group, cadence in summary

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Ruleset item title + changelog

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/rulesets/oposs_pbs.py:174` (`rule_spec_oposs_pbs_backup` condition item title)
- Modify: `CHANGES.md` (Unreleased section)
- Test: `tests/test_rulesets.py` (verify it still imports/builds)

**Interfaces:**
- Consumes: nothing from Task 1 at runtime; purely GUI metadata + docs.
- Produces: no code symbols consumed downstream.

- [ ] **Step 1: Relabel the item title**

In `rulesets/oposs_pbs.py`, find:

```python
rule_spec_oposs_pbs_backup = CheckParameters(
    name="oposs_pbs_backup", title=Title("PBS backup freshness (piggyback)"),
    topic=Topic.STORAGE, parameter_form=_backup_form,
    condition=HostAndItemCondition(item_title=Title("Datastore/namespace")))
```

Change the item title:

```python
    condition=HostAndItemCondition(item_title=Title("Backup group")))
```

- [ ] **Step 2: Run the ruleset tests to verify they still pass**

Run: `pytest tests/test_rulesets.py -q`
Expected: PASS (the module imports and all rule specs build).

- [ ] **Step 3: Add the breaking-change changelog entry**

In `CHANGES.md`, under `## [Unreleased]`, fill the `### Changed` section:

```markdown
### Changed
- **BREAKING: `PBS Backup` services are now per backup group.** The service
  item is now fully qualified as `<datastore>[/<namespace>] <type>/<id>`
  (e.g. `store1 host/data`, `store1/prod vm/101`) instead of just the
  datastore. A host that backs up several groups into one datastore now gets
  one service per group, and services for datastores a host never writes to
  no longer appear. The observed backup cadence is now shown directly in the
  service summary (e.g. `cadence ~1 day`, or `cadence ~1 day (assumed)` when
  derived from a fallback). **After upgrade:** run a service rediscovery on the
  affected piggyback hosts, remove the vanished old items, and re-point any
  per-item `PBS backup freshness` rules to the new item names.
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest -q`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**

```bash
git add local/lib/python3/cmk_addons/plugins/oposs_pbs/rulesets/oposs_pbs.py CHANGES.md
git commit -m "docs: relabel backup item title, note breaking service rename

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Change 1 (fully-qualified item) → Task 1 Steps 3 + tests. ✓
- Change 2 (cadence in summary) → Task 1 Step 4 + cadence tests. ✓
- Change 3 (ruleset item title) → Task 2 Step 1. ✓
- Change 4 (migration/breaking changelog) → Task 2 Step 3. ✓
- Tests enumerated in spec → Task 1 Step 1 (all four bullet points covered). ✓

**Placeholder scan:** No TBD/TODO; all code shown in full. ✓

**Type consistency:** `_backup_item(rec) -> str` used identically in
`discover_oposs_pbs_backup` and `check_oposs_pbs_backup`. Record field names
(`backup_type`, `backup_id`, `ns`, `datastore`) match the collector's
`piggyback.append(...)` payload in `oposs_pbs_collect.py`. `suffix` reused
consistently within `check_oposs_pbs_backup`. ✓
