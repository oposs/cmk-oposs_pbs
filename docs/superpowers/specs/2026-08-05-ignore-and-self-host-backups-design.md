# Ignoring backup groups and reporting the PBS host's own backup inline

Date: 2026-08-05
Status: approved, ready for implementation planning

## Problems

**1. PBS running as a VM on the Proxmox cluster it backs up.**
PVE writes the guest name into the snapshot comment, the collector reads it as
`guest`, and `piggyback_host()` renders it into the piggyback host name. When
the PBS VM's guest name equals the Checkmk host name of the PBS host, the
special agent emits a `<<<<pbs01>>>>` piggyback block inside the output of host
`pbs01` — a host piggybacking to itself. Regardless of how Checkmk resolves
that, it is the wrong shape: the backup of the PBS VM should simply be a
service on the PBS host, reported directly.

**2. Backups of decommissioned machines.**
When a machine stops existing but its backups are deliberately retained, the
backup group keeps ageing and the freshness check keeps escalating. There is no
way to tell the monitor to leave a group alone.

## Design

### 1. Ignore filter

**Match target.** A canonical group path, built once in `oposs_pbs_util.py`:

```python
def group_path(store: str, ns: str, btype: str, bid: str) -> str:
    return f"{store}/{ns}/{btype}/{bid}"
```

With an empty namespace this yields the double-slash form, e.g.
`store1//vm/105`; with a namespace, `store1/tenantA/ct/210`. Patterns are
applied with `re.search`, so `vm/105$` pins one group, `^store1/tenantA/`
ignores a namespace, and `/host/oldbox$` ignores one host backup.

**Configuration.**

- Ruleset (`rulesets/oposs_pbs.py`, `_agent_form()`): new element
  `backup_ignore`, a `List` whose `element_template` is a `RegularExpression`
  with `MatchingScope.INFIX`, titled "Ignore these backup groups (regex)".
  Help text states the match target format including the empty-namespace
  double slash, and that ignored groups still occupy disk and are still
  counted in the datastore's group/backup counts.
- `server_side_calls/oposs_pbs.py`: `Params` gains
  `backup_ignore: list[str] = []`; each pattern is passed as a repeatable
  `--ignore-backup PATTERN`, mirroring `--exclude-datastore`.
- `agent_oposs_pbs`: `p.add_argument("--ignore-backup", action="append",
  default=[])`. Patterns are compiled once at agent start; an invalid pattern
  is a hard, loud failure at startup rather than a silent per-group skip.
- `collect_mod.Options` gains an `ignore` field holding the compiled patterns.

**Where it applies.** The first statement inside the `for g in groups:` loop of
`_collect_store()` — before the cache lookup, before `needs_refresh()`, before
any `/snapshots` call. An ignored group therefore costs zero API calls and
causes no cache churn, which is a performance win on top of the monitoring
suppression.

**Effect.** An ignored group produces:

- no piggyback record,
- no `oposs_pbs_backup_rollup` entry (the roll-up is derived from the piggyback
  list, so this follows automatically),
- no `unmapped_backups` entry.

`group_count`, `backup_count` and datastore usage are computed from the raw
`groups` list *above* the loop and stay untouched — they describe what is
actually on disk.

**Visibility.** The collector accumulates a count across all datastores and
sets `host["oposs_pbs_server"]["ignored_backups"] = N`.
`check_oposs_pbs_server()` yields an OK `notice` —
`"N backup group(s) ignored by configuration"` — when `N > 0`. A notice rather
than a summary, so it appears in the service details without cluttering the
service line.

**Deliberate non-goal.** Cache entries for newly-ignored groups are not purged.
They sit unused in the JSON cache, are harmless, and are reused if the group is
un-ignored later.

**Composition with `no_piggyback`.** A datastore listed in `no_piggyback`
already `continue`s before the group loop, so no group in it reaches the ignore
check. The two features compose without overlapping.

### 2. PBS-as-VM: report the host's own backup inline

**Detection.** `server_side_calls` passes the Checkmk host name as
`--self-host <host_config.name>`. A group is "self" when its resolved piggyback
host name compares equal under `str.casefold()` to that value. Exact match
only: if the guest name is `pbs01` and the Checkmk host is
`pbs01.example.com`, behaviour is unchanged from today. This is chosen over
short-name/FQDN tolerance because an unrelated VM literally named `pbs01`
would otherwise be folded onto the PBS host.

**Mechanism.** The collector is untouched. The split happens in the agent's
output loop in `agent_oposs_pbs`, the only place that knows about piggyback
framing:

```
<<<oposs_pbs_server:sep(0)>>>          unchanged
<<<oposs_pbs_datastore:sep(0)>>>       unchanged
<<<oposs_pbs_jobs:sep(0)>>>            unchanged
<<<oposs_pbs_backup_rollup:sep(0)>>>   unchanged — still covers every group
<<<oposs_pbs_backup:sep(0)>>>          NEW — one JSON line per self-matched group
{...}
{...}
<<<<guest-a>>>>                        unchanged for every other group
<<<oposs_pbs_backup:sep(0)>>>
{...}
<<<<>>>>
```

The inline section must be printed *before* the first piggyback marker,
otherwise it would be attributed to the preceding piggyback host.

**Why no check-plugin changes are needed.** `parse_backup()` already iterates
rows, so a multi-record section parses correctly. `_backup_item()` already
yields a unique item per group. The PBS host therefore gains a
`PBS Backup store1 vm/105` service alongside its existing `PBS Server`,
`PBS Datastore` and `PBS Backups` services, using the same `oposs_pbs_backup`
check plugin and the same `oposs_pbs_backup` check ruleset as every
piggybacked guest.

**Roll-up.** The self-matched group stays in `oposs_pbs_backup_rollup`, exactly
as every piggybacked group does today. No special-casing.

**Accepted side effect.** `host_label_oposs_pbs_backup()` now runs on the PBS
host too, so the PBS host acquires the `oposs_pbs/backup: yes` and
`oposs_pbs/datastore` host labels. This is correct — the PBS host does have a
PBS backup.

**When `--self-host` is absent** (e.g. an older SSC, or a manual invocation),
output is byte-identical to today.

## Testing

- `oposs_pbs_util.group_path()`: namespaced and empty-namespace (`//`) forms.
- Collector, ignore filter:
  - an ignored group is absent from the piggyback list, the roll-up and
    `unmapped_backups`;
  - `host["oposs_pbs_server"]["ignored_backups"]` counts it;
  - `group_count` / `backup_count` for its datastore are unchanged;
  - the fake client records **no** `/admin/datastore/*/snapshots` call for it;
  - a pattern matching nothing changes no behaviour.
- Agent main, self-host:
  - `--self-host pbs01` with a group resolving to `PBS01` produces a plain
    `oposs_pbs_backup` section, no `<<<<pbs01>>>>` marker, and the group still
    present in the roll-up;
  - the inline section appears before the first `<<<<` marker;
  - without `--self-host`, output is byte-identical to today.
- `check_oposs_pbs_server()` renders the ignored-groups notice when the count
  is non-zero and stays silent at zero.

## Documentation

- README: both new configuration fields, with the group-path format and worked
  pattern examples.
- CHANGES.md: the `--self-host` change alters where the service lands for
  anyone whose PBS VM guest name already equals their Checkmk PBS host name —
  record it as a behaviour change, not just an addition.
