# Per-backup-group PBS Backup services

## Problem

The per-guest `PBS Backup` piggyback check discovers **one service per
datastore[/namespace]**, not one per backup group. Consequences:

1. A node that backs up several groups (e.g. `host/root`, `host/data`,
   `host/srv`) into a single datastore collapses into **one** service.
   `check_oposs_pbs_backup` then matches only the *first* record via
   `next(...)`, so the other groups are invisible.
2. Services discovered for datastores this host never writes to keep matching
   nothing and go stale / error out.

Root cause — `agent_based/oposs_pbs.py`, `_backup_item()`:

```python
def _backup_item(rec) -> str:
    ns = rec.get("ns")
    return f"{rec['datastore']}/{ns}" if ns else rec.get("datastore", "?")
```

The item omits `backup_type` / `backup_id`.

The collector (`oposs_pbs_collect.py`) already emits **one piggyback record per
backup group** with every needed field, so no collector change is required.

## Change 1 — Fully qualified item identity

`_backup_item()` includes the backup group, fully qualified (chosen: option B,
collision-free):

```
"{datastore}/{ns} {backup_type}/{backup_id}"   # namespaced
"{datastore} {backup_type}/{backup_id}"        # root namespace (ns == "")
```

Resulting service names:

- `PBS Backup store1 host/data`
- `PBS Backup store1/prod vm/101`

Because the same `_backup_item()` drives both `discover_oposs_pbs_backup` and
the record lookup in `check_oposs_pbs_backup`, one edit fixes discovery
granularity **and** the wrong-record `next()` match. Each group becomes its own
service; a group that disappears from PBS becomes a *vanished* service at the
next discovery instead of silently receiving nothing.

## Change 2 — Cadence in the summary

Today the cadence is emitted as a `notice`, invisible in the summary unless the
state is non-OK. Move it into the summary line (chosen: option B — cadence only,
thresholds stay implicit in the age levels).

Terminology: the plugin has no *configured* expectation. `interval` is the
**observed median gap** between snapshots (`u.median_interval`), which is what
the alert thresholds derive from (`warn_missed × interval`). The summary shows
what the check currently believes the cadence to be.

`check_oposs_pbs_backup` yields, after the `check_levels(age, …)` call:

```
Last backup age: 3 hours, cadence ~1 day
Last backup age: 3 hours, cadence ~1 day (assumed)   # interval_known is False
```

Implementation: keep the `check_levels(... label="Last backup age" ...)` call,
then yield `Result(state=State.OK, summary=f"cadence ~{render.timespan(interval)}{suffix}")`
where `suffix` is `""` or `" (assumed)"`. Checkmk joins OK summary fragments
with `, `. The snapshot count stays a `notice`.

## Change 3 — Ruleset item title

`rulesets/oposs_pbs.py`, `rule_spec_oposs_pbs_backup`: item title
`Datastore/namespace` → `Backup group`. Existing per-item rules will no longer
match the new item names regardless (see migration).

## Change 4 — Migration (breaking)

This renames every `PBS Backup *` service. After upgrade:

- Run a service rediscovery on the affected piggyback hosts.
- Old items appear as **vanished**; remove them.
- Per-item check rules (`oposs_pbs_backup`) referencing old items must be
  re-pointed to the new `{datastore}[/ns] {type}/{id}` items.

Documented in `CHANGES.md` under a new Unreleased entry as a breaking change.

## Out of scope

- The roll-up service (`PBS Backups`) — already per-group in its details, no
  change.
- Collector, cache, client, util — unchanged.

## Tests (`tests/test_check_backup.py`)

- Update existing item expectations from `"main"` / `"backup2"` to the new
  fully-qualified form (`"main vm/100"`, `"backup2 vm/100"`).
- New: two groups on one host in one datastore
  (`rec(backup_id="100")`, `rec(backup_id="101")`) → discovery yields two
  distinct services; checking each item reports that group's own age (the other
  group's staleness does not leak in).
- New: cadence text appears in the joined summary — both known
  (`cadence ~1 day`) and assumed (`(assumed)`) forms.
- Existing multi-datastore regression test updated to the new item names.
