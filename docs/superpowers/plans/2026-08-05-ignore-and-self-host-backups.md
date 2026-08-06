# Backup Ignore Filter and Inline Self-Host Backup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators suppress monitoring of retained backups by regex, and make the PBS host's own backup (PBS running as a VM on the cluster it backs up) report as a normal service on the PBS host instead of as self-referential piggyback.

**Architecture:** Two independent additions to the existing special agent. (1) An ignore filter matched against a canonical group path `<datastore>/<ns>/<type>/<id>`, applied at the very top of the per-group loop in `_collect_store()` so ignored groups cost no API calls; the count is surfaced on the `PBS Server` service. (2) A `--self-host` flag consumed only by the agent's output loop: groups whose resolved piggyback host name equals the Checkmk host name are printed as a plain `oposs_pbs_backup` section instead of inside a `<<<<host>>>>` block. No check-plugin logic changes — the existing `oposs_pbs_backup` plugin discovers the inline section on the PBS host unchanged.

**Tech Stack:** Python 3, Checkmk 2.3 plugin APIs (`cmk.agent_based.v2`, `cmk.rulesets.v1`, `cmk.server_side_calls.v1`), pytest with offline cmk stubs (`tests/cmk_stubs`, loaded via `tests/conftest.py:load_module`).

**Spec:** `docs/superpowers/specs/2026-08-05-ignore-and-self-host-backups-design.md`

## Global Constraints

- Comments, identifiers, docstrings and technical documentation in English. GUI
  help text in English (this plugin's existing convention).
- Run tests with at most 4 parallel jobs. Plain `pytest` (serial) is what this
  repo uses — do not add `-n auto`.
- The agent must always exit 0 on PBS-side failures; only a genuine
  misconfiguration (an invalid ignore regex) may abort at startup.
- Never print warnings or diagnostics on stdout — stdout is agent section data.
  Use `_warn()` / stderr.
- Ignored backup groups must not change `group_count`, `backup_count` or
  datastore usage figures.
- Without `--self-host`, agent output must be byte-identical to today.
- Test command for the whole suite: `pytest -q` from the repo root.

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/oposs_pbs_util.py` | modify | add `group_path()` — the canonical string the ignore regex matches |
| `.../libexec/oposs_pbs_collect.py` | modify | `Options.ignore`, skip ignored groups, count them into `oposs_pbs_server.ignored_backups` |
| `.../agent_based/oposs_pbs.py` | modify | `check_oposs_pbs_server()` reports the ignored count as a notice |
| `.../libexec/agent_oposs_pbs` | modify | `--ignore-backup` (compile + pass through), `--self-host` (output split) |
| `.../server_side_calls/oposs_pbs.py` | modify | `backup_ignore` param → `--ignore-backup`; always pass `--self-host <host name>` |
| `.../rulesets/oposs_pbs.py` | modify | `backup_ignore` GUI element |
| `tests/test_util.py` | modify | `group_path()` formatting |
| `tests/test_collect.py` | modify | ignore filter behaviour and cost |
| `tests/test_check_server.py` | modify | ignored-count notice |
| `tests/test_agent_cli.py` | modify | `--ignore-backup` and `--self-host` end-to-end |
| `tests/test_server_side_calls.py` | modify | new flags emitted |
| `tests/test_rulesets.py` | modify | new GUI element present |
| `README.md`, `CHANGES.md` | modify | user-facing documentation |

---

### Task 1: Canonical group path helper

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/oposs_pbs_util.py`
- Test: `tests/test_util.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `oposs_pbs_util.group_path(store: str, ns: str, btype: str, bid: str) -> str`.
  Task 2 imports it as `u.group_path(...)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_util.py` (the module is already bound to `u` at the top
of that file):

```python
def test_group_path_is_the_ignore_match_target():
    """The ignore filter matches against '<store>/<ns>/<type>/<id>'. With no
    namespace this collapses to a double slash, which patterns must be able to
    rely on."""
    assert u.group_path("store1", "", "vm", "105") == "store1//vm/105"
    assert u.group_path("store1", "tenantA", "ct", "210") == "store1/tenantA/ct/210"
    assert u.group_path("backup2", "", "host", "oldbox") == "backup2//host/oldbox"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_util.py::test_group_path_is_the_ignore_match_target -q`
Expected: FAIL with `AttributeError: module 'oposs_pbs_util' has no attribute 'group_path'`

- [ ] **Step 3: Write minimal implementation**

In `oposs_pbs_util.py`, add after `dedup_factor()`:

```python
def group_path(store: str, ns: str, btype: str, bid: str) -> str:
    """Canonical identifier of a backup group, matched by the ignore filter.

    An empty namespace yields the double-slash form, e.g. "store1//vm/105";
    a namespaced group yields "store1/tenantA/ct/210".
    """
    return f"{store}/{ns}/{btype}/{bid}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_util.py -q`
Expected: PASS, all tests in the file green.

- [ ] **Step 5: Commit**

```bash
git add local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/oposs_pbs_util.py tests/test_util.py
git commit -m "feat: add group_path() helper for the backup ignore filter"
```

---

### Task 2: Ignore filter in the collector

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/oposs_pbs_collect.py`
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `oposs_pbs_util.group_path()` from Task 1.
- Produces:
  - `collect.Options` gains field `ignore: list` — a list of **compiled**
    `re.Pattern` objects, defaulting to `[]`. It is the last dataclass field,
    so all existing positional/keyword constructions keep working.
  - `collect()` sets `host["oposs_pbs_server"]["ignored_backups"] = <int>`.
    Task 3 renders it; Task 4 produces the patterns.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_collect.py`. Add `import re` at the top of the file
(next to the existing `import sys`).

```python
# --- ignore filter ----------------------------------------------------------

def test_ignored_group_is_dropped_everywhere():
    """A matching group produces no piggyback record and no roll-up entry, and
    is counted on the server section so the suppression stays discoverable."""
    opts = _opts(); opts.ignore = [re.compile(r"vm/100$")]
    c = FakePbs(sample_routes(NOW))
    host, pig = collect.collect(c, opts, cache.StateCache({}), NOW)

    assert pig == []
    assert host["oposs_pbs_backup_rollup"] == []
    assert host["oposs_pbs_server"]["ignored_backups"] == 1


def test_ignored_group_costs_no_snapshot_call():
    """The filter runs before the cache lookup, so an ignored group never
    triggers the expensive /snapshots enumeration."""
    opts = _opts(); opts.ignore = [re.compile(r"vm/100$")]
    c = FakePbs(sample_routes(NOW))
    collect.collect(c, opts, cache.StateCache({}), NOW)
    assert not any(p.endswith("/snapshots") for p, _ in c.calls)


def test_ignored_group_still_counted_in_datastore_totals():
    """Ignored backups still occupy disk, so the datastore's own figures must
    not change."""
    opts = _opts(); opts.ignore = [re.compile(r"vm/100$")]
    c = FakePbs(sample_routes(NOW))
    host, _ = collect.collect(c, opts, cache.StateCache({}), NOW)
    ds = host["oposs_pbs_datastore"]["main"]
    assert ds["group_count"] == 1 and ds["backup_count"] == 7
    assert ds["used"] == 250


def test_ignored_group_not_reported_as_unmapped():
    """A vm group with no guest name would normally be flagged as unmapped;
    ignoring it must silence that too."""
    routes = sample_routes(NOW)
    routes["/admin/datastore/main/groups"] = [
        {"backup-type": "vm", "backup-id": "116", "last-backup": NOW - 100,
         "backup-count": 3}]                      # no comment -> no guest name
    routes["/admin/datastore/main/snapshots"] = [
        {"backup-type": "vm", "backup-id": "116", "backup-time": NOW - 100,
         "size": 1}]
    opts = _opts(); opts.ignore = [re.compile(r"^main//vm/116$")]
    host, pig = collect.collect(FakePbs(routes), opts, cache.StateCache({}), NOW)
    assert host["oposs_pbs_server"]["unmapped_backups"] == []
    assert pig == []


def test_namespace_pattern_ignores_whole_namespace():
    routes = _two_group_routes(NOW)
    routes["/admin/datastore/main/namespace"] = [{"ns": ""}, {"ns": "tenantA"}]
    opts = _opts(); opts.ignore = [re.compile(r"^main/tenantA/")]
    host, pig = collect.collect(FakePbs(routes), opts, cache.StateCache({}), NOW)
    # Both namespaces serve the same two groups here; only the "" ones survive.
    assert {rec["ns"] for _, rec in pig} == {""}
    assert host["oposs_pbs_server"]["ignored_backups"] == 2


def test_no_ignore_patterns_changes_nothing():
    c = FakePbs(sample_routes(NOW))
    host, pig = collect.collect(c, _opts(), cache.StateCache({}), NOW)
    assert len(pig) == 1
    assert host["oposs_pbs_server"]["ignored_backups"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_collect.py -q -k ignore`
Expected: FAIL — `AttributeError`/`TypeError` around `opts.ignore` and
`KeyError: 'ignored_backups'`.

- [ ] **Step 3: Write the implementation**

In `oposs_pbs_collect.py`:

Change the dataclass import line:

```python
from dataclasses import dataclass, field
```

Extend `Options` (add the new field **last**, so existing constructions that
omit it keep working):

```python
@dataclass
class Options:
    include: list
    exclude: list
    task_limit: int
    piggyback_template: str
    piggyback_regex: tuple | None
    no_piggyback: set
    # Compiled regexes; a backup group whose group_path() matches any of them
    # is dropped from all backup monitoring (see agent_oposs_pbs).
    ignore: list = field(default_factory=list)
```

In `collect()`, add a stats counter before the datastore loop and pass it
through, then publish it. Replace the block from `datastores: dict = {}` down
to `host["oposs_pbs_server"]["unmapped_backups"] = unmapped` with:

```python
    datastores: dict = {}
    piggyback: list = []
    unmapped: list = []
    # Cross-datastore counters surfaced on the server section.
    stats: dict = {"ignored": 0}
    for store in stores:
        # One unreachable/slow datastore must not sink the others.
        try:
            _collect_store(client, store, opts, cache, tasks, now,
                           datastores, piggyback, budget, saver, unmapped,
                           stats)
        except Exception as exc:
            _warn(f"datastore {store!r} collection failed, skipped: {exc}")
        saver.flush()
    host["oposs_pbs_datastore"] = datastores
    # vm/ct backups with no resolved guest name land on their VMID; surface them
    # so the operator can fix the PVE notes-template.
    host["oposs_pbs_server"]["unmapped_backups"] = unmapped
    # Backup groups suppressed by the configured ignore patterns. Reported as a
    # count only, so a stale pattern is discoverable without cluttering output.
    host["oposs_pbs_server"]["ignored_backups"] = stats["ignored"]
```

Update the `_collect_store` signature:

```python
def _collect_store(client, store, opts, cache, tasks, now, datastores,
                   piggyback, budget, saver, unmapped, stats):
```

And make the ignore check the first statement of the per-group loop:

```python
        for g in groups:
            # Ignored groups are dropped before any cache lookup or /snapshots
            # call, so suppression is also a cost saving. Datastore group and
            # backup counts above are unaffected: the data is still on disk.
            if opts.ignore:
                path = u.group_path(store, ns, g["backup-type"], g["backup-id"])
                if any(p.search(path) for p in opts.ignore):
                    stats["ignored"] += 1
                    continue
            last_backup = int(g.get("last-backup", 0) or 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_collect.py -q`
Expected: PASS — the new ignore tests plus every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/oposs_pbs_collect.py tests/test_collect.py
git commit -m "feat: drop configured backup groups from monitoring in the collector"
```

---

### Task 3: Report the ignored count on the PBS Server service

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/agent_based/oposs_pbs.py` (in `check_oposs_pbs_server`, after the `unmapped` block that ends around line 96)
- Test: `tests/test_check_server.py`

**Interfaces:**
- Consumes: `section["ignored_backups"]` (int) produced by Task 2.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_check_server.py`:

```python
def test_server_reports_ignored_backup_count():
    """Groups suppressed by the ignore patterns are counted so a stale pattern
    is discoverable, but stay OK and out of the summary line."""
    sec = _sec({"reachable": True, "version": "4.2", "node": "localhost",
                "datastore_count": 1, "unmapped_backups": [],
                "ignored_backups": 3})
    res = list(m.check_oposs_pbs_server(DEFAULTS, sec))
    hits = [r for r in res if "ignored" in (getattr(r, "summary", "") or "")
            or "ignored" in (getattr(r, "details", "") or "")]
    assert hits and hits[0].state is State.OK
    assert "3" in (hits[0].details or hits[0].summary)
    # Never escalates and never takes over the service summary line.
    assert all(r.state is State.OK for r in res if hasattr(r, "state"))
    assert "ignored" not in res[0].summary


def test_server_silent_when_nothing_ignored():
    sec = _sec({"reachable": True, "version": "4.2", "node": "localhost",
                "datastore_count": 1, "unmapped_backups": [],
                "ignored_backups": 0})
    res = list(m.check_oposs_pbs_server(DEFAULTS, sec))
    assert not any("ignored" in (getattr(r, "details", "") or "") for r in res)


def test_server_tolerates_missing_ignored_key():
    """Sections from an older agent have no ignored_backups key."""
    res = list(m.check_oposs_pbs_server(DEFAULTS, _sec(
        {"reachable": True, "version": "4.2", "node": "localhost",
         "datastore_count": 1})))
    assert res[0].state is State.OK
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_check_server.py -q -k ignored`
Expected: FAIL — `assert hits` fails because no result mentions "ignored".

- [ ] **Step 3: Write the implementation**

In `check_oposs_pbs_server()`, directly after the `if unmapped:` block and
before the function ends, add:

```python
    ignored = section.get("ignored_backups") or 0
    if ignored:
        yield Result(
            state=State.OK,
            notice=f"{ignored} backup group(s) ignored by configuration",
            details=("These backup groups match an ignore pattern in the "
                     "special agent rule and are excluded from all backup "
                     "monitoring. Remove the pattern to monitor them again."))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_check_server.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add local/lib/python3/cmk_addons/plugins/oposs_pbs/agent_based/oposs_pbs.py tests/test_check_server.py
git commit -m "feat: surface the ignored backup group count on the PBS Server service"
```

---

### Task 4: Agent CLI — `--ignore-backup` and `--self-host`

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/agent_oposs_pbs`
- Test: `tests/test_agent_cli.py`

**Interfaces:**
- Consumes: `collect.Options.ignore` (Task 2).
- Produces: two CLI flags Task 5 emits —
  - `--ignore-backup PATTERN` (repeatable, `action="append"`, default `[]`)
  - `--self-host NAME` (single value, optional)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_cli.py`:

```python
def _run(tmp_path, now, *extra):
    routes_file = tmp_path / "routes.json"
    routes_file.write_text(json.dumps(_routes(now)))
    return subprocess.check_output(
        [sys.executable, str(AGENT), "pbs.example",
         "--token-id", "root@pam!mon", "--token-secret", "x",
         "--test-file", str(routes_file), "--cache-dir", str(tmp_path),
         "--now", str(now), *extra],
        text=True)


def test_self_host_backup_reported_inline_not_as_piggyback(tmp_path):
    """PBS running as a VM on the cluster it backs up: its own backup must be a
    plain section on the PBS host, never a piggyback block addressed to itself."""
    now = 1_000_000
    out = _run(tmp_path, now, "--self-host", "web01")   # guest name in fixture
    assert "<<<<web01>>>>" not in out
    assert "<<<oposs_pbs_backup:sep(0)>>>" in out
    # The inline section must precede any piggyback marker, or it would be
    # attributed to the preceding piggyback host.
    if "<<<<" in out:
        assert out.index("<<<oposs_pbs_backup:sep(0)>>>") < out.index("<<<<")
    # Still present in the host-level roll-up.
    rollup = out.split("<<<oposs_pbs_backup_rollup:sep(0)>>>\n", 1)[1].splitlines()[0]
    assert json.loads(rollup)[0]["backup_id"] == "100"


def test_self_host_match_is_case_insensitive(tmp_path):
    out = _run(tmp_path, 1_000_000, "--self-host", "WEB01")
    assert "<<<<web01>>>>" not in out
    assert "<<<oposs_pbs_backup:sep(0)>>>" in out


def test_self_host_no_match_keeps_piggyback(tmp_path):
    """An exact match is required: an unrelated name leaves output unchanged."""
    out = _run(tmp_path, 1_000_000, "--self-host", "web01.example.com")
    assert "<<<<web01>>>>" in out


def test_ignore_backup_suppresses_group(tmp_path):
    now = 1_000_000
    out = _run(tmp_path, now, "--ignore-backup", r"vm/100$")
    assert "<<<<web01>>>>" not in out
    server = out.split("<<<oposs_pbs_server:sep(0)>>>\n", 1)[1].splitlines()[0]
    assert json.loads(server)["ignored_backups"] == 1
    rollup = out.split("<<<oposs_pbs_backup_rollup:sep(0)>>>\n", 1)[1].splitlines()[0]
    assert json.loads(rollup) == []


def test_invalid_ignore_pattern_fails_loudly(tmp_path):
    """A broken regex is a misconfiguration, not a PBS-side error: fail at
    startup rather than silently monitoring nothing."""
    now = 1_000_000
    routes_file = tmp_path / "routes.json"
    routes_file.write_text(json.dumps(_routes(now)))
    proc = subprocess.run(
        [sys.executable, str(AGENT), "pbs.example",
         "--token-id", "root@pam!mon", "--token-secret", "x",
         "--test-file", str(routes_file), "--cache-dir", str(tmp_path),
         "--now", str(now), "--ignore-backup", "vm/[100"],
        text=True, capture_output=True)
    assert proc.returncode != 0
    assert "vm/[100" in proc.stderr
    assert proc.stdout == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_cli.py -q`
Expected: FAIL — `subprocess.CalledProcessError` (`unrecognized arguments:
--self-host`).

- [ ] **Step 3: Write the implementation**

In `agent_oposs_pbs`:

Add `import re` to the imports at the top (next to `import os`).

In `parse_args()`, after the `--no-piggyback-datastore` line:

```python
    # Repeatable regex; matched (re.search) against "<store>/<ns>/<type>/<id>".
    p.add_argument("--ignore-backup", action="append", default=[])
    # Checkmk host name of this PBS host. A backup group resolving to exactly
    # this name is this server's own backup (PBS running as a VM on the cluster
    # it backs up); it is reported inline instead of as self-referential
    # piggyback.
    p.add_argument("--self-host")
```

In `main()`, after the `regex = ...` block and before building `opts`:

```python
    # Compile once, at startup: an invalid pattern is a misconfiguration and
    # must fail loudly rather than silently suppressing nothing (or everything).
    try:
        ignore = [re.compile(pat) for pat in args.ignore_backup]
    except re.error as exc:
        print(f"invalid --ignore-backup pattern {exc.pattern!r}: {exc}",
              file=sys.stderr)
        return 2
```

Pass it into `Options`:

```python
    opts = collect_mod.Options(
        include=args.include_datastore, exclude=args.exclude_datastore,
        task_limit=args.task_limit, piggyback_template=args.piggyback_template,
        piggyback_regex=regex, no_piggyback=set(args.no_piggyback_datastore),
        ignore=ignore)
```

Replace the piggyback output loop (currently the `for host_name, record in
piggyback:` block) with:

```python
    # Split the groups into this host's own backup and everyone else's. The
    # inline section must be printed before the first piggyback marker,
    # otherwise it would be attributed to the preceding piggyback host.
    self_host = (args.self_host or "").casefold()
    own: list = []
    remote: list = []
    for host_name, record in piggyback:
        if not host_name:
            continue
        if self_host and host_name.casefold() == self_host:
            own.append(record)
        else:
            remote.append((host_name, record))

    if own:
        print("<<<oposs_pbs_backup:sep(0)>>>")
        for record in own:
            print(json.dumps(record, separators=(",", ":")))

    for host_name, record in remote:
        print(f"<<<<{host_name}>>>>")
        _print_section("oposs_pbs_backup", record)
        print("<<<<>>>>")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_cli.py -q`
Expected: PASS, including the pre-existing `test_agent_test_file_mode` (which
passes no `--self-host` and must still see `<<<<web01>>>>`).

- [ ] **Step 5: Commit**

```bash
git add local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/agent_oposs_pbs tests/test_agent_cli.py
git commit -m "feat: add --ignore-backup and inline --self-host backup reporting"
```

---

### Task 5: GUI ruleset and server-side call wiring

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/rulesets/oposs_pbs.py` (in `_agent_form()`)
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/server_side_calls/oposs_pbs.py`
- Test: `tests/test_rulesets.py`, `tests/test_server_side_calls.py`

**Interfaces:**
- Consumes: the CLI flags from Task 4.
- Produces: `Params.backup_ignore: list[str]`; the GUI element key
  `backup_ignore` in the special-agent form.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server_side_calls.py`:

```python
def test_backup_ignore_patterns_forwarded():
    params = ssc.Params(token_id="root@pam!mon", token_secret=Secret(3),
                        backup_ignore=[r"vm/105$", r"^store1/tenantA/"])
    args = list(ssc.special_agent_oposs_pbs.commands_function(
        params, HostConfig(name="pbs01")))[0].command_arguments
    assert args.count("--ignore-backup") == 2
    assert r"vm/105$" in args and r"^store1/tenantA/" in args


def test_no_ignore_flag_when_unconfigured():
    args = list(ssc.special_agent_oposs_pbs.commands_function(
        ssc.Params(token_id="root@pam!mon", token_secret=Secret(3)),
        HostConfig(name="pbs01")))[0].command_arguments
    assert "--ignore-backup" not in args


def test_self_host_always_passed_as_checkmk_host_name():
    """The agent needs the Checkmk host name (not the IP) to recognise its own
    backup when PBS runs as a VM on the cluster it backs up."""
    args = list(ssc.special_agent_oposs_pbs.commands_function(
        ssc.Params(token_id="root@pam!mon", token_secret=Secret(3)),
        HostConfig(name="pbs01")))[0].command_arguments
    assert args[args.index("--self-host") + 1] == "pbs01"
    assert args[-1] == "10.0.0.1"          # host address still last
```

Append to `tests/test_rulesets.py`:

```python
def test_agent_form_has_backup_ignore_list_of_regexes():
    elements = rs._agent_form().kwargs["elements"]
    assert "backup_ignore" in elements
    lst = elements["backup_ignore"].kwargs["parameter_form"]
    # List(element_template=RegularExpression(...))
    assert lst.kwargs["element_template"] is not None
    # The match target must be documented in the GUI, including the empty-
    # namespace double-slash form operators will otherwise get wrong.
    # (The Help stub is a str subclass, hence str() rather than .args[0].)
    assert "store1//vm/105" in str(lst.kwargs["help_text"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rulesets.py tests/test_server_side_calls.py -q`
Expected: FAIL — `ValidationError`/`AttributeError` for `backup_ignore` and
`ValueError: '--self-host' is not in list`.

- [ ] **Step 3: Write the implementation**

In `rulesets/oposs_pbs.py`, add to the `elements` dict of `_agent_form()`,
after the `no_piggyback` entry:

```python
            "backup_ignore": DictElement(parameter_form=List(
                title=Title("Ignore these backup groups (regex)"),
                help_text=Help(
                    "Backup groups matching any of these patterns are excluded "
                    "from all backup monitoring: no piggyback service, no entry "
                    "in the 'PBS Backups' roll-up, no missing-guest-name "
                    "complaint. Use it to keep the backups of a decommissioned "
                    "machine without alerting on their growing age. The pattern "
                    "is searched (not anchored) in "
                    "'<datastore>/<namespace>/<type>/<id>' -- with no namespace "
                    "that reads 'store1//vm/105' (note the double slash), with "
                    "one 'store1/tenantA/ct/210'. The datastore's group and "
                    "backup counts still include ignored groups, because the "
                    "data is still on disk. The 'PBS Server' service reports "
                    "how many groups are being ignored."),
                element_template=RegularExpression(
                    title=Title("Pattern"),
                    predefined_help_text=MatchingScope.INFIX))),
```

In `server_side_calls/oposs_pbs.py`, add the field to `Params` after
`no_piggyback`:

```python
    backup_ignore: list[str] = []
```

and in `_commands()`, after the `--no-piggyback-datastore` loop and before the
address is appended:

```python
    for pat in params.backup_ignore:
        args += ["--ignore-backup", pat]
    # The Checkmk host name (not the address): lets the agent recognise this
    # PBS server's own backup and report it inline instead of piggybacking to
    # itself. See rulesets help for "Ignore these backup groups".
    args += ["--self-host", host_config.name]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q`
Expected: PASS — the full suite, including `test_smoke.py`.

- [ ] **Step 5: Commit**

```bash
git add local/lib/python3/cmk_addons/plugins/oposs_pbs/rulesets/oposs_pbs.py \
        local/lib/python3/cmk_addons/plugins/oposs_pbs/server_side_calls/oposs_pbs.py \
        tests/test_rulesets.py tests/test_server_side_calls.py
git commit -m "feat: GUI and server-side-call wiring for backup ignore and self-host"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGES.md`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: nothing.

- [ ] **Step 1: Add a configuration section to the README**

Insert after the introductory paragraph in `README.md`, before `## Development`:

```markdown
## Configuration notes

### Ignoring retained backups

`Ignore these backup groups (regex)` in the special agent rule suppresses all
monitoring of matching backup groups — no piggyback service, no entry in the
`PBS Backups` roll-up, no missing-guest-name complaint. Use it when a machine
has been decommissioned but its backups are deliberately retained.

Patterns are searched (not anchored) in the group path
`<datastore>/<namespace>/<type>/<id>`. With no namespace the path contains a
double slash:

| Pattern | Effect |
| --- | --- |
| `vm/105$` | ignores VMID 105 in every datastore and namespace |
| `^store1/tenantA/` | ignores everything in namespace `tenantA` of `store1` |
| `/host/oldbox$` | ignores the `host/oldbox` backup group |

Ignored groups still count towards the datastore's group and backup totals —
the data is still on disk. The `PBS Server` service reports how many groups are
currently ignored, so a pattern that has outlived its purpose stays visible.

### PBS running as a VM on the cluster it backs up

When PBS itself is a Proxmox guest and is backed up to its own datastore, its
backup would otherwise be piggybacked to the very host that produced the agent
output. The agent detects this — the resolved piggyback host name matches the
Checkmk host name exactly, ignoring case — and reports the backup as a normal
`PBS Backup ...` service on the PBS host instead. No configuration is needed.

The match is exact: if the PVE guest name is `pbs01` but the Checkmk host is
`pbs01.example.com`, they do not match and the backup is piggybacked as before.
Align the two names, or use the piggyback host rewrite, to enable the inline
reporting.
```

- [ ] **Step 2: Add the CHANGES.md entries**

Under `## [Unreleased]`, fill in the `### New` and `### Changed` sections:

```markdown
### New
- **Ignore backup groups by regex.** The special agent rule gained
  `Ignore these backup groups (regex)`. Matching groups are excluded from all
  backup monitoring — no piggyback service, no roll-up entry, no
  missing-guest-name complaint — so backups of decommissioned machines can be
  retained without alerting. The pattern is searched in
  `<datastore>/<namespace>/<type>/<id>` (e.g. `store1//vm/105`). Ignored groups
  are skipped before any snapshot enumeration, so ignoring also saves API calls.
  The `PBS Server` service reports the number of ignored groups.

### Changed
- **A PBS server that backs up its own VM now reports that backup on itself.**
  Previously the agent emitted a piggyback block addressed to the host that
  produced the output. When the backup's resolved piggyback host name equals
  the Checkmk host name (case-insensitive, exact), the `PBS Backup` service now
  appears directly on the PBS host. If this applies to you, the affected
  service moves from a piggyback host to the PBS host and the PBS host gains
  the `oposs_pbs/backup` and `oposs_pbs/datastore` host labels; re-run service
  discovery on both. Setups where the names differ are unaffected.
```

- [ ] **Step 3: Verify the full suite is still green**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGES.md
git commit -m "docs: document backup ignore patterns and inline self-host backup"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
| --- | --- |
| `group_path()` helper, `//` for empty namespace | 1 |
| `backup_ignore` ruleset element, INFIX regex list | 5 |
| `Params.backup_ignore` → `--ignore-backup` | 5 |
| `--ignore-backup` CLI arg, compiled once, loud on bad regex | 4 |
| `Options.ignore` | 2 |
| Filter as first statement of the group loop, before cache/snapshots | 2 |
| No piggyback / roll-up / unmapped entry for ignored groups | 2 |
| Datastore counts untouched | 2 |
| `ignored_backups` count in server section | 2 |
| `PBS Server` notice for the count | 3 |
| Cache entries deliberately not purged | 2 (no code — nothing purges them) |
| Composition with `no_piggyback` | 2 (filter sits after the existing `continue`) |
| `--self-host` from `host_config.name` | 5 |
| casefold exact match, inline section before first `<<<<` | 4 |
| Roll-up still includes the self group | 4 (collector untouched) |
| Byte-identical output without `--self-host` | 4 |
| Tests enumerated in the spec | 1–5 |
| README + CHANGES | 6 |

**Placeholder scan:** none — every code step carries the literal code.

**Type consistency:** `group_path(store, ns, btype, bid) -> str` is defined in
Task 1 and called with exactly that signature in Task 2. `Options.ignore` holds
compiled `re.Pattern` objects in Task 2, Task 4 supplies compiled patterns, and
the Task 2 tests construct them with `re.compile`. `stats` is a
`dict` with the single key `"ignored"` in both `collect()` and `_collect_store()`.
`section["ignored_backups"]` is written in Task 2 and read in Task 3.
