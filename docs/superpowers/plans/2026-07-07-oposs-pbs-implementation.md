# oposs_pbs — Proxmox Backup Server special agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Checkmk 2.3 server-side special agent that monitors Proxmox Backup Server over its REST API — datastore usage, backup counts + GC, sync/verify/prune jobs, and per-guest backup freshness/verification/size via piggyback — replacing the agent-based `inett_proxmox_backup` plugin.

**Architecture:** A standalone Python collector (`libexec/agent_oposs_pbs`) authenticates to PBS with an API token, calls the REST API, and prints Checkmk agent sections (host-level) plus piggyback blocks (per guest). Pure logic (REST client, interval/dedup math, task matching, state cache, section building) lives in importable helper modules next to the agent so it is unit-testable without a Checkmk site. Check plugins, rulesets, server-side calls, and graphing follow the standard `cmk_addons/plugins/oposs_pbs/` layout.

**Tech Stack:** Python 3.11+, `requests`, `pydantic` (server-side-calls params), Checkmk plugin APIs `cmk.agent_based.v2` / `cmk.server_side_calls.v1` / `cmk.rulesets.v1` / `cmk.graphing.v1`. Tests: `pytest` + `responses` (HTTP mocking). Packaging: `oposs/mkp-builder@v2` GitHub Action.

**Design spec:** `docs/superpowers/specs/2026-07-07-oposs-pbs-special-agent-design.md` (read it — this plan implements it).

## Global Constraints

- Checkmk target: **2.3.x** (`version.min_required = 2.3.0p1`). Plugin APIs: `cmk.agent_based.v2`, `cmk.server_side_calls.v1`, `cmk.rulesets.v1`, `cmk.graphing.v1`.
- Company/metric prefix: **`oposs_pbs_`** on every metric. Store metrics in **base SI units** (bytes, seconds).
- Plugin `name` must match across `SpecialAgent(name=...)`, `SpecialAgentConfig(name=...)`, and the executable `libexec/agent_oposs_pbs` → **`oposs_pbs`**.
- Entry-point variable prefixes are mandatory: `agent_section_`, `check_plugin_`, `special_agent_`, `rule_spec_`, `metric_`, `graph_`, `perfometer_`.
- PBS REST: base path **`/api2/json`**, default port **8007**, auth header **`Authorization: PBSAPIToken TOKENID:TOKENSECRET`** (`TOKENID = user@realm!tokenname`).
- Scheduled-job task `worker_type` strings: **`garbage_collection`**, **`syncjob`**, **`verificationjob`**, **`prunejob`** (NOT `prune`).
- Secret passing: bare `Secret` in `command_arguments` (password-store reference), agent calls `replace_passwords()` first. Never `.unsafe()`.
- Build parallelism: never exceed **4 cores** for compilers/tests (this is a shared machine). Do not run `find /home/oetiker`.
- Local containers use **podman**. Node tooling (if any) uses **pnpm**. (This project is Python-only.)
- Comments, identifiers, and docs in **English**.

---

## File Structure

```
local/lib/check_mk -> python3/cmk                      # symlink (prod path safety)
local/lib/python3/cmk_addons/plugins/oposs_pbs/
    __init__.py
    libexec/
        agent_oposs_pbs            # executable entry (argparse, output)      [Task 5]
        oposs_pbs_client.py        # PbsClient: REST + auth + TLS + errors    [Task 1]
        oposs_pbs_util.py          # pure helpers: intervals, dedup, matching [Task 2]
        oposs_pbs_cache.py         # per-host state cache + refresh decision   [Task 3]
        oposs_pbs_collect.py       # build host sections + piggyback records   [Task 4]
    server_side_calls/oposs_pbs.py # Params + commands_function                [Task 6]
    rulesets/oposs_pbs.py          # special-agent form + check-params forms   [Task 7]
    agent_based/oposs_pbs.py       # parsers + all check plugins               [Tasks 8-11]
    graphing/oposs_pbs.py          # metrics, graphs, perfometers              [Task 12]
    checkman/oposs_pbs             # documentation                            [Task 13]
.mkp-builder.ini                                                              [Task 14]
.github/workflows/build.yml                                                   [Task 14]
tests/
    conftest.py                    # cmk stubs + module loader helper          [Task 0]
    cmk_stubs/                     # fake cmk.* packages for offline tests      [Task 0]
    fixtures/                      # sample PBS API responses + agent output    [Task 0+]
    test_client.py                                                            [Task 1]
    test_util.py                                                              [Task 2]
    test_cache.py                                                             [Task 3]
    test_collect.py                                                           [Task 4]
    test_agent_cli.py                                                         [Task 5]
    test_server_side_calls.py                                                 [Task 6]
    test_rulesets.py                                                          [Task 7]
    test_check_server.py                                                      [Task 8]
    test_check_datastore.py                                                   [Task 9]
    test_check_jobs.py                                                        [Task 10]
    test_check_backup.py                                                      [Task 11]
    test_graphing.py                                                         [Task 12]
requirements-dev.txt
pytest.ini
```

**Import strategy for tests (no Checkmk site required):** `tests/conftest.py` inserts `tests/cmk_stubs` onto `sys.path` as fake `cmk.*` packages and adds the libexec dir to `sys.path`. Plugin files under `agent_based/`, `server_side_calls/`, `rulesets/`, `graphing/` are loaded by a helper `load_module(relpath, name)` (importlib from file path) so tests never depend on Checkmk's namespace-package loader. The agent guards `from cmk.utils.password_store import replace_passwords` behind `try/except ImportError` so it runs offline.

---

### Task 0: Repo scaffolding and offline test harness

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/__init__.py` (empty)
- Create: `requirements-dev.txt`, `pytest.ini`
- Create: `tests/conftest.py`
- Create: `tests/cmk_stubs/cmk/__init__.py`, `tests/cmk_stubs/cmk/agent_based/__init__.py`, `tests/cmk_stubs/cmk/agent_based/v2.py`
- Create: `tests/cmk_stubs/cmk/server_side_calls/__init__.py`, `tests/cmk_stubs/cmk/server_side_calls/v1.py`
- Create: `tests/cmk_stubs/cmk/rulesets/__init__.py`, `tests/cmk_stubs/cmk/rulesets/v1/__init__.py`, `.../v1/form_specs.py`, `.../v1/rule_specs.py`
- Create: `tests/cmk_stubs/cmk/graphing/__init__.py`, `.../v1/__init__.py`, `.../v1/metrics.py`, `.../v1/graphs.py`, `.../v1/perfometers.py`
- Create: the symlink `local/lib/check_mk -> python3/cmk`

**Interfaces:**
- Produces: `tests/conftest.py` fixtures `load_module` (callable) and path setup; stub classes `Result, State, Metric, Service, ServiceLabel, AgentSection, CheckPlugin, check_levels, render` in `cmk.agent_based.v2`.

- [ ] **Step 1: Create the plugin package dir, symlink, and dev deps**

```bash
mkdir -p local/lib/python3/cmk_addons/plugins/oposs_pbs/{libexec,server_side_calls,rulesets,agent_based,graphing,checkman}
: > local/lib/python3/cmk_addons/plugins/oposs_pbs/__init__.py
mkdir -p local/lib/python3/cmk
ln -sfn python3/cmk local/lib/check_mk
mkdir -p tests/cmk_stubs tests/fixtures
```

`requirements-dev.txt`:
```
pytest>=8
requests>=2.31
responses>=0.25
pydantic>=2
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

- [ ] **Step 2: Write the cmk stub for `cmk.agent_based.v2`**

`tests/cmk_stubs/cmk/agent_based/v2.py`:
```python
"""Minimal stand-ins for the Checkmk agent_based v2 API used in offline tests."""
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


class State(enum.Enum):
    OK = 0
    WARN = 1
    CRIT = 2
    UNKNOWN = 3


@dataclass
class Result:
    state: State
    summary: str | None = None
    notice: str | None = None
    details: str | None = None


@dataclass
class Metric:
    name: str
    value: float
    levels: tuple[float, float] | None = None
    boundaries: tuple[float | None, float | None] | None = None


@dataclass
class Service:
    item: str | None = None
    labels: list = field(default_factory=list)


@dataclass
class ServiceLabel:
    name: str
    value: str


@dataclass
class HostLabel:
    name: str
    value: str


class AgentSection:
    def __init__(self, *, name, parse_function, **kw):
        self.name = name
        self.parse_function = parse_function


class CheckPlugin:
    def __init__(self, *, name, service_name, discovery_function, check_function,
                 sections=None, check_ruleset_name=None, check_default_parameters=None, **kw):
        self.name = name
        self.service_name = service_name
        self.discovery_function = discovery_function
        self.check_function = check_function
        self.sections = sections
        self.check_ruleset_name = check_ruleset_name
        self.check_default_parameters = check_default_parameters


def _fixed(levels) -> tuple[float, float] | None:
    if not levels or levels[0] in (None, "no_levels"):
        return None
    if levels[0] == "fixed":
        return levels[1]
    return None


def check_levels(value, *, levels_upper=None, levels_lower=None, metric_name=None,
                 render_func=None, label=None, boundaries=None, notice_only=False
                 ) -> Iterable[Result | Metric]:
    rf: Callable[[float], str] = render_func or (lambda v: str(v))
    state = State.OK
    up = _fixed(levels_upper)
    if up is not None:
        warn, crit = up
        if value >= crit:
            state = State.CRIT
        elif value >= warn:
            state = State.WARN
    low = _fixed(levels_lower)
    if low is not None:
        warn, crit = low
        if value < crit:
            state = State.CRIT
        elif value < warn and state is State.OK:
            state = State.WARN
    text = f"{label}: {rf(value)}" if label else rf(value)
    if notice_only and state is State.OK:
        yield Result(state=state, notice=text)
    else:
        yield Result(state=state, summary=text)
    if metric_name:
        yield Metric(metric_name, float(value), levels=up, boundaries=boundaries)


class render:  # noqa: N801  (mirror real API's lowercase module-like name)
    @staticmethod
    def percent(v): return f"{v:.2f}%"
    @staticmethod
    def bytes(v): return f"{v:.0f}B"
    @staticmethod
    def timespan(v): return f"{v:.0f}s"
    @staticmethod
    def datetime(v): return f"@{int(v)}"
```

- [ ] **Step 3: Write the remaining cmk stubs (generic recorder classes)**

The server_side_calls, rulesets, and graphing stubs only need to *construct without error* and expose the kwargs. Use one generic recorder.

`tests/cmk_stubs/cmk/server_side_calls/v1.py`:
```python
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple, Sequence


class Secret(NamedTuple):
    id: int = 0
    format: str = "%s"
    pass_safely: bool = True
    def unsafe(self, template: str = "%s") -> "Secret":
        return self._replace(pass_safely=False, format=template)


@dataclass
class IPv4Config:
    address: str = "10.0.0.1"


@dataclass
class HostConfig:
    name: str = "pbs-host"
    @property
    def primary_ip_config(self):
        return IPv4Config()


@dataclass(frozen=True, kw_only=True)
class SpecialAgentCommand:
    command_arguments: Sequence[Any]
    stdin: str | None = None


class SpecialAgentConfig:
    def __init__(self, *, name, parameter_parser, commands_function):
        self.name = name
        self.parameter_parser = parameter_parser
        self.commands_function = commands_function
```

`tests/cmk_stubs/cmk/rulesets/v1/__init__.py`:
```python
class _Str(str):
    def __new__(cls, s=""): return super().__new__(cls, s)


def Title(s=""): return _Str(s)
def Help(s=""): return _Str(s)
def Label(s=""): return _Str(s)
def Message(s=""): return _Str(s)
```

`tests/cmk_stubs/cmk/rulesets/v1/form_specs.py` and `.../rule_specs.py` and all three `cmk/graphing/v1/*.py`: one recorder each. Example recorder (put a copy in each module, exporting the names that file imports):
```python
class _Rec:
    def __init__(self, *a, **k):
        self.args = a
        self.kwargs = k

# form_specs.py exports:
Dictionary = DictElement = Integer = Float = String = BooleanChoice = _Rec
SimpleLevels = LevelDirection = DefaultValue = Password = _Rec
CascadingSingleChoice = CascadingSingleChoiceElement = _Rec
SingleChoice = SingleChoiceElement = List = TimeSpan = TimeMagnitude = _Rec
RegularExpression = validators = _Rec
class _V:  # validators namespace
    LengthInRange = NetworkPort = NumberInRange = _Rec
validators = _V()
```
(Provide the analogous one-liners for `rule_specs.py`: `CheckParameters = SpecialAgent = HostCondition = HostAndItemCondition = _Rec`, and a `Topic` object with attributes `STORAGE`/`GENERAL` = `_Rec()`; and for graphing `metrics.py`/`graphs.py`/`perfometers.py`: `Metric = Unit = DecimalNotation = IECNotation = TimeNotation = Color = Graph = MinimalRange = Perfometer = FocusRange = Closed = _Rec`, with `Color` also exposing attribute access — make `Color = type("Color",(),{n:i for i,n in enumerate(["LIGHT_BLUE","LIGHT_PURPLE","BLUE","GREEN","ORANGE","RED","CYAN","PURPLE","GRAY"])})`.)

- [ ] **Step 4: Write `tests/conftest.py`**

```python
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUBS = Path(__file__).resolve().parent / "cmk_stubs"
PLUGIN = ROOT / "local/lib/python3/cmk_addons/plugins/oposs_pbs"

# Offline cmk stubs must precede any real cmk on the path.
sys.path.insert(0, str(STUBS))
# libexec helper modules import each other by bare name.
sys.path.insert(0, str(PLUGIN / "libexec"))


def load_module(relpath: str, name: str):
    """Load a plugin .py file by path with cmk stubs already on sys.path."""
    path = PLUGIN / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


import pytest


@pytest.fixture
def load():
    return load_module
```

- [ ] **Step 5: Add a smoke test and verify pytest runs**

`tests/test_smoke.py`:
```python
def test_stub_imports():
    from cmk.agent_based.v2 import State, Result, check_levels
    results = list(check_levels(95.0, levels_upper=("fixed", (80.0, 90.0)),
                               metric_name="x", label="CPU"))
    assert results[0].state is State.CRIT
    assert results[1].name == "x" and results[1].value == 95.0
```

Run: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt && pytest -q`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: scaffold oposs_pbs plugin layout and offline test harness

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1: PBS REST client

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/oposs_pbs_client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Produces:
  - `class PbsError(Exception)`
  - `class PbsClient` with `__init__(self, host, port, token_id, token_secret, *, verify=True, cafile=None, timeout=30)` and `get(self, path, params=None) -> Any` (returns the `data` field of the JSON envelope). Auth header `Authorization: PBSAPIToken {token_id}:{token_secret}`. `verify` maps to `requests` `verify=` (`True`/`False`/`cafile` path). Raises `PbsError` on transport error or non-2xx.

- [ ] **Step 1: Write failing tests**

`tests/test_client.py`:
```python
import pytest
import responses
from conftest import load_module

client = load_module("libexec/oposs_pbs_client.py", "oposs_pbs_client")


@responses.activate
def test_get_sends_token_header_and_unwraps_data():
    responses.add(responses.GET, "https://pbs.example:8007/api2/json/version",
                  json={"data": {"version": "3.2.7"}}, status=200)
    c = client.PbsClient("pbs.example", 8007, "root@pam!mon", "s3cr3t", verify=False)
    assert c.get("/version") == {"version": "3.2.7"}
    sent = responses.calls[0].request.headers["Authorization"]
    assert sent == "PBSAPIToken root@pam!mon:s3cr3t"


@responses.activate
def test_get_raises_pbserror_on_http_500():
    responses.add(responses.GET, "https://pbs.example:8007/api2/json/nodes",
                  status=500)
    c = client.PbsClient("pbs.example", 8007, "root@pam!mon", "x", verify=False)
    with pytest.raises(client.PbsError):
        c.get("/nodes")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_client.py -q`
Expected: FAIL (module has no `PbsClient`).

- [ ] **Step 3: Implement the client**

`oposs_pbs_client.py`:
```python
"""Thin Proxmox Backup Server REST client (API-token auth)."""
from __future__ import annotations
from typing import Any
import requests


class PbsError(Exception):
    """Any failure talking to the PBS API (transport or HTTP status)."""


class PbsClient:
    def __init__(self, host: str, port: int, token_id: str, token_secret: str,
                 *, verify: bool | str = True, cafile: str | None = None,
                 timeout: int = 30) -> None:
        self._base = f"https://{host}:{port}/api2/json"
        self._timeout = timeout
        self._verify: bool | str = cafile if cafile else verify
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"PBSAPIToken {token_id}:{token_secret}"

    def get(self, path: str, params: dict | None = None) -> Any:
        url = self._base + path
        try:
            resp = self._session.get(url, params=params, verify=self._verify,
                                     timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise PbsError(f"GET {path} failed: {exc}") from exc
        try:
            return resp.json().get("data")
        except ValueError as exc:
            raise PbsError(f"GET {path}: invalid JSON") from exc
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_client.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: PBS REST client with API-token auth

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Pure collection helpers

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/oposs_pbs_util.py`
- Test: `tests/test_util.py`

**Interfaces:**
- Produces:
  - `median_interval(times: list[int]) -> int | None` — median gap between sorted timestamps; `None` if fewer than 2.
  - `dedup_factor(index_data_bytes: float | None, disk_bytes: float | None) -> float | None` — `index/disk`, `None` if disk falsy/absent.
  - `piggyback_host(template: str, group: dict, regex: tuple[str, str] | None) -> str` — expand `{id}`/`{type}`/`{comment}` from a group dict (`backup-type`,`backup-id`,`comment`), then apply optional `(pattern, replacement)` `re.sub`.
  - `latest_task(tasks: list[dict], worker_type: str, match: Callable[[str], bool]) -> dict | None` — most recent *finished* task (has `endtime` and `status`) of that type whose `worker_id` matches.
  - `task_running(tasks, worker_type, match) -> bool`
  - `latest_verify_activity(tasks, store: str) -> int` — max `endtime` among finished tasks whose `worker_type` in `{verificationjob, verify, verify_group, verify_snapshot}` and `worker_id` starts with `store`; `0` if none.

- [ ] **Step 1: Write failing tests**

`tests/test_util.py`:
```python
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


def test_latest_task_picks_most_recent_finished():
    tasks = [
        {"worker_type": "syncjob", "worker_id": "r:s:d:ns:job1",
         "starttime": 10, "endtime": 20, "status": "OK"},
        {"worker_type": "syncjob", "worker_id": "r:s:d:ns:job1",
         "starttime": 30, "endtime": 40, "status": "some error"},
        {"worker_type": "syncjob", "worker_id": "r:s:d:ns:job1",
         "starttime": 50, "endtime": None, "status": None},  # running, ignored
    ]
    got = u.latest_task(tasks, "syncjob", lambda wid: wid.rsplit(":", 1)[-1] == "job1")
    assert got["starttime"] == 30 and got["status"] == "some error"
    assert u.task_running(tasks, "syncjob", lambda wid: wid.endswith("job1")) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_util.py -q`
Expected: FAIL (no module attributes).

- [ ] **Step 3: Implement helpers**

`oposs_pbs_util.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_util.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: pure helpers for intervals, dedup, task matching

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Per-host state cache

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/oposs_pbs_cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Produces:
  - `group_key(ds, ns, btype, bid) -> str` → `f"{ds}|{ns}|{btype}|{bid}"`
  - `class StateCache`:
    - `StateCache.load(path: str) -> StateCache` (missing/corrupt file → empty cache)
    - `.get(key) -> dict | None`
    - `.put(key, entry: dict) -> None`
    - `.save(path: str) -> None` (atomic write; creates parent dirs)
    - `.needs_refresh(key, last_backup: int, verify_activity: int) -> bool` — True if no entry, or entry `last_backup` differs, or entry `verify_checked_at` < `verify_activity`.

- [ ] **Step 1: Write failing tests**

`tests/test_cache.py`:
```python
from conftest import load_module
cache = load_module("libexec/oposs_pbs_cache.py", "oposs_pbs_cache")


def test_refresh_rules(tmp_path):
    c = cache.StateCache.load(str(tmp_path / "missing.json"))
    k = cache.group_key("store1", "", "vm", "100")
    assert c.needs_refresh(k, last_backup=10, verify_activity=0) is True  # new
    c.put(k, {"last_backup": 10, "verify_checked_at": 5,
              "interval": 86400, "interval_known": True,
              "verify_state": "ok", "data_size": 42})
    assert c.needs_refresh(k, last_backup=10, verify_activity=5) is False  # unchanged
    assert c.needs_refresh(k, last_backup=20, verify_activity=5) is True   # new backup
    assert c.needs_refresh(k, last_backup=10, verify_activity=9) is True   # verify ran


def test_roundtrip(tmp_path):
    p = str(tmp_path / "sub" / "host.json")
    c = cache.StateCache.load(p)
    c.put("k", {"last_backup": 1})
    c.save(p)
    again = cache.StateCache.load(p)
    assert again.get("k") == {"last_backup": 1}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_cache.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the cache**

`oposs_pbs_cache.py`:
```python
"""Per-host JSON state cache gating expensive /snapshots calls."""
from __future__ import annotations
import json
import os
import tempfile


def group_key(ds: str, ns: str, btype: str, bid: str) -> str:
    return f"{ds}|{ns}|{btype}|{bid}"


class StateCache:
    def __init__(self, data: dict | None = None) -> None:
        self._d: dict = data or {}

    @classmethod
    def load(cls, path: str) -> "StateCache":
        try:
            with open(path, encoding="utf-8") as fh:
                return cls(json.load(fh))
        except (OSError, ValueError):
            return cls({})

    def get(self, key: str):
        return self._d.get(key)

    def put(self, key: str, entry: dict) -> None:
        self._d[key] = entry

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._d, fh)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise

    def needs_refresh(self, key: str, last_backup: int, verify_activity: int) -> bool:
        entry = self._d.get(key)
        if entry is None:
            return True
        if entry.get("last_backup") != last_backup:
            return True
        if entry.get("verify_checked_at", 0) < verify_activity:
            return True
        return False
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_cache.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: per-host state cache with refresh gating

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Collection orchestrator

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/oposs_pbs_collect.py`
- Create: `tests/fixtures/fake_pbs.py` (a fake client returning canned API data)
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `PbsClient.get` (Task 1), helpers (Task 2), `StateCache` (Task 3).
- Produces:
  - `class Options` dataclass: `include: list[str]`, `exclude: list[str]`, `task_limit: int`, `piggyback_template: str`, `piggyback_regex: tuple[str,str] | None`, `no_piggyback: set[str]`.
  - `node_name(client) -> str` — first node's `node`, fallback `"localhost"`.
  - `select_datastores(all_stores, opts) -> list[str]`
  - `collect(client, opts, cache, now: int) -> tuple[dict, list[tuple[str, dict]]]` returning `(host_sections, piggyback)` where `host_sections` has keys `oposs_pbs_server`, `oposs_pbs_datastore`, `oposs_pbs_jobs`, and `piggyback` is a list of `(piggyback_host, backup_record)`. Mutates and is expected to `cache.save()` by the caller.
    - `backup_record` keys: `datastore, ns, backup_type, backup_id, last_backup, backup_count, interval, interval_known, verify_state, data_size`.

- [ ] **Step 1: Write the fake client fixture**

`tests/fixtures/fake_pbs.py`:
```python
"""A fake PbsClient.get() keyed by (path, frozenset(params))."""


class FakePbs:
    def __init__(self, routes: dict):
        # routes: path -> value, OR path -> callable(params)->value
        self.routes = routes
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        v = self.routes[path]
        return v(params or {}) if callable(v) else v


DAY = 86400


def sample_routes(now):
    return {
        "/nodes": [{"node": "pbs01"}],
        "/version": {"version": "3.2.7"},
        "/admin/datastore": [{"store": "main", "comment": "primary"}],
        "/admin/datastore/main/status": {
            "total": 1000, "used": 250, "avail": 750,
            "gc-status": {"index-data-bytes": 4000, "disk-bytes": 1000,
                          "upid": "UPID:pbs01:GC"},
        },
        "/admin/datastore/main/namespace": [{"ns": ""}],
        "/admin/datastore/main/groups": [
            {"backup-type": "vm", "backup-id": "100", "last-backup": now - 100,
             "backup-count": 7, "comment": "web01"},
        ],
        "/config/sync": [{"id": "s1", "store": "main", "remote": "r1",
                          "remote-store": "rs", "ns": "", "schedule": "daily"}],
        "/config/verify": [{"id": "v1", "store": "main", "schedule": "weekly"}],
        "/config/prune": [{"id": "p1", "store": "main", "schedule": "daily"}],
        "/nodes/pbs01/tasks": [
            {"worker_type": "garbage_collection", "worker_id": "main",
             "starttime": now - 3600, "endtime": now - 3500, "status": "OK"},
            {"worker_type": "syncjob", "worker_id": "r1:rs:main::s1",
             "starttime": now - 200, "endtime": now - 100, "status": "OK"},
            {"worker_type": "verificationjob", "worker_id": "main:v1",
             "starttime": now - 400, "endtime": now - 300, "status": "OK"},
            {"worker_type": "prunejob", "worker_id": "main",
             "starttime": now - 500, "endtime": now - 450, "status": "OK"},
        ],
        "/admin/datastore/main/snapshots": [
            {"backup-type": "vm", "backup-id": "100", "backup-time": now - 100 - DAY,
             "size": 40_000_000_000},
            {"backup-type": "vm", "backup-id": "100", "backup-time": now - 100,
             "size": 41_000_000_000, "verification": {"state": "ok", "upid": "x"}},
        ],
    }
```

- [ ] **Step 2: Write failing tests**

`tests/test_collect.py`:
```python
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
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_collect.py -q`
Expected: FAIL.

- [ ] **Step 4: Implement the orchestrator**

`oposs_pbs_collect.py`:
```python
"""Collect PBS state via REST and shape it into Checkmk sections + piggyback."""
from __future__ import annotations
import re
from dataclasses import dataclass

import oposs_pbs_util as u
from oposs_pbs_cache import StateCache, group_key


@dataclass
class Options:
    include: list
    exclude: list
    task_limit: int
    piggyback_template: str
    piggyback_regex: tuple | None
    no_piggyback: set


def node_name(client) -> str:
    try:
        nodes = client.get("/nodes") or []
        if nodes and nodes[0].get("node"):
            return nodes[0]["node"]
    except Exception:
        pass
    return "localhost"


def select_datastores(stores: list[str], opts: Options) -> list[str]:
    def ok(name: str) -> bool:
        if opts.include and not any(re.search(p, name) for p in opts.include):
            return False
        if any(re.search(p, name) for p in opts.exclude):
            return False
        return True
    return [s for s in stores if ok(s)]


def _gc_state(tasks, store):
    running = u.task_running(tasks, "garbage_collection", lambda w: w == store)
    latest = u.latest_task(tasks, "garbage_collection", lambda w: w == store)
    return {
        "status": latest["status"] if latest else None,
        "endtime": latest["endtime"] if latest else None,
        "running": running,
    }


def _job_last_run(tasks, worker_type, match):
    latest = u.latest_task(tasks, worker_type, match)
    running = u.task_running(tasks, worker_type, match)
    return ({"status": latest["status"], "endtime": latest["endtime"]} if latest
            else None), running


def _collect_jobs(client, tasks):
    sync = []
    for j in client.get("/config/sync") or []:
        if not j.get("id"):
            continue
        lr, run = _job_last_run(tasks, "syncjob",
                                lambda w, i=j["id"]: w.rsplit(":", 1)[-1] == i)
        sync.append({**j, "last_run": lr, "running": run})
    verify = []
    for j in client.get("/config/verify") or []:
        if not j.get("id"):
            continue
        lr, run = _job_last_run(tasks, "verificationjob",
                                lambda w, i=j["id"]: w.rsplit(":", 1)[-1] == i)
        verify.append({**j, "last_run": lr, "running": run})
    prune = []
    for j in client.get("/config/prune") or []:
        if not j.get("id"):
            continue
        store, ns = j.get("store", ""), j.get("ns", "") or ""
        wid = f"{store}:{ns}" if ns else store
        lr, run = _job_last_run(tasks, "prunejob", lambda w, x=wid: w == x)
        prune.append({**j, "last_run": lr, "running": run})
    return {"sync": sync, "verify": verify, "prune": prune}


def _namespaces(client, store):
    seen = {""}
    out = [""]
    for entry in client.get(f"/admin/datastore/{store}/namespace") or []:
        ns = entry.get("ns", "")
        if ns not in seen:
            seen.add(ns)
            out.append(ns)
    return out


def _refresh_group(client, store, ns, group, now):
    """Fetch this group's snapshots; return (interval, known, verify_state, size)."""
    snaps = client.get(f"/admin/datastore/{store}/snapshots", params={
        "ns": ns, "backup-type": group["backup-type"],
        "backup-id": group["backup-id"],
    }) or []
    times = [int(s["backup-time"]) for s in snaps if s.get("backup-time") is not None]
    interval = u.median_interval(times)
    newest = max(snaps, key=lambda s: s.get("backup-time", 0)) if snaps else {}
    vstate = (newest.get("verification") or {}).get("state") or "none"
    size = int(newest.get("size", 0) or 0)
    return interval, interval is not None, vstate, size


def collect(client, opts: Options, cache: StateCache, now: int):
    host: dict = {}
    try:
        version = (client.get("/version") or {}).get("version")
        node = node_name(client)
        stores_raw = [d["store"] for d in (client.get("/admin/datastore") or [])]
    except Exception as exc:  # unreachable / auth failure
        host["oposs_pbs_server"] = {"reachable": False, "error": str(exc)}
        return host, []

    stores = select_datastores(stores_raw, opts)
    tasks = client.get(f"/nodes/{node}/tasks",
                       params={"limit": opts.task_limit}) or []

    host["oposs_pbs_server"] = {"reachable": True, "version": version,
                               "node": node, "datastore_count": len(stores)}
    host["oposs_pbs_jobs"] = _collect_jobs(client, tasks)

    datastores: dict = {}
    piggyback: list = []
    for store in stores:
        status = client.get(f"/admin/datastore/{store}/status") or {}
        gcs = status.get("gc-status") or {}
        group_count = backup_count = 0
        for ns in _namespaces(client, store):
            groups = client.get(f"/admin/datastore/{store}/groups",
                                params={"ns": ns}) or []
            group_count += len(groups)
            backup_count += sum(int(g.get("backup-count", 0)) for g in groups)
            if store in opts.no_piggyback:
                continue
            verify_activity = u.latest_verify_activity(tasks, store)
            for g in groups:
                last_backup = int(g.get("last-backup", 0) or 0)
                key = group_key(store, ns, g["backup-type"], g["backup-id"])
                if cache.needs_refresh(key, last_backup, verify_activity):
                    interval, known, vstate, size = _refresh_group(
                        client, store, ns, g, now)
                    cache.put(key, {"last_backup": last_backup,
                                    "verify_checked_at": verify_activity,
                                    "interval": interval, "interval_known": known,
                                    "verify_state": vstate, "data_size": size})
                e = cache.get(key)
                host_name = u.piggyback_host(opts.piggyback_template, g,
                                             opts.piggyback_regex)
                piggyback.append((host_name, {
                    "datastore": store, "ns": ns,
                    "backup_type": g["backup-type"], "backup_id": g["backup-id"],
                    "last_backup": last_backup, "backup_count": int(g.get("backup-count", 0)),
                    "interval": e["interval"], "interval_known": e["interval_known"],
                    "verify_state": e["verify_state"], "data_size": e["data_size"],
                }))
        datastores[store] = {
            "total": status.get("total"), "used": status.get("used"),
            "avail": status.get("avail"),
            "group_count": group_count, "backup_count": backup_count,
            "gc": {**_gc_state(tasks, store),
                   "index_data_bytes": gcs.get("index-data-bytes"),
                   "disk_bytes": gcs.get("disk-bytes")},
        }
    host["oposs_pbs_datastore"] = datastores
    return host, piggyback
```

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/test_collect.py -q`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: PBS collection orchestrator (sections + piggyback + cache gating)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Agent entry script

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/agent_oposs_pbs` (executable, no `.py`)
- Test: `tests/test_agent_cli.py`

**Interfaces:**
- Consumes: `PbsClient` (Task 1), `Options`/`collect` (Task 4), `StateCache` (Task 3).
- Produces: a CLI. Args: positional `hostaddress`; `--port` (8007), `--token-id`, `--token-secret`, `--no-verify-tls`, `--cacert`, `--include-datastore` (append), `--exclude-datastore` (append), `--task-limit` (1000), `--piggyback-template` (`{id}`), `--piggyback-regex` (`PATTERN=REPLACEMENT`), `--no-piggyback-datastore` (append), `--cache-dir`, `--test-file` (offline JSON routes). Prints host sections then piggyback blocks. `main(argv) -> int`.
- Output contract: host sections `<<<oposs_pbs_server:sep(0)>>>`, `<<<oposs_pbs_datastore:sep(0)>>>`, `<<<oposs_pbs_jobs:sep(0)>>>` (one compact JSON line each), then per guest `<<<<HOST>>>>` / `<<<oposs_pbs_backup:sep(0)>>>` / JSON / `<<<<>>>>`.

- [ ] **Step 1: Write failing test (offline via `--test-file`)**

`tests/test_agent_cli.py`:
```python
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / \
    "local/lib/python3/cmk_addons/plugins/oposs_pbs"
AGENT = PLUGIN / "libexec/agent_oposs_pbs"


def _routes(now):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
    from fake_pbs import sample_routes
    # Only static routes survive JSON; callables aren't used in sample_routes.
    return sample_routes(now)


def test_agent_test_file_mode(tmp_path):
    now = 1_000_000
    routes_file = tmp_path / "routes.json"
    routes_file.write_text(json.dumps(_routes(now)))
    out = subprocess.check_output(
        [sys.executable, str(AGENT), "pbs.example",
         "--token-id", "root@pam!mon", "--token-secret", "x",
         "--test-file", str(routes_file), "--cache-dir", str(tmp_path),
         "--now", str(now)],
        text=True)
    assert "<<<oposs_pbs_server:sep(0)>>>" in out
    assert "<<<oposs_pbs_datastore:sep(0)>>>" in out
    assert "<<<<100>>>>" in out
    assert "<<<oposs_pbs_backup:sep(0)>>>" in out
    # server section parses and is reachable
    line = out.split("<<<oposs_pbs_server:sep(0)>>>\n", 1)[1].splitlines()[0]
    assert json.loads(line)["reachable"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_agent_cli.py -q`
Expected: FAIL (agent missing).

- [ ] **Step 3: Implement the agent**

`agent_oposs_pbs`:
```python
#!/usr/bin/env python3
"""Checkmk special agent for Proxmox Backup Server (REST, API-token auth)."""
from __future__ import annotations
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oposs_pbs_collect as collect_mod
from oposs_pbs_cache import StateCache
from oposs_pbs_client import PbsClient

try:  # cmk.utils.password_store is not a stable API path; guard for offline use
    from cmk.utils.password_store import replace_passwords
except ImportError:
    def replace_passwords():
        return None


def parse_args(argv):
    p = argparse.ArgumentParser(description="Proxmox Backup Server special agent")
    p.add_argument("hostaddress")
    p.add_argument("--port", type=int, default=8007)
    p.add_argument("--token-id", required=True)
    p.add_argument("--token-secret", required=True)
    p.add_argument("--no-verify-tls", action="store_true")
    p.add_argument("--cacert")
    p.add_argument("--include-datastore", action="append", default=[])
    p.add_argument("--exclude-datastore", action="append", default=[])
    p.add_argument("--task-limit", type=int, default=1000)
    p.add_argument("--piggyback-template", default="{id}")
    p.add_argument("--piggyback-regex")  # "PATTERN=REPLACEMENT"
    p.add_argument("--no-piggyback-datastore", action="append", default=[])
    p.add_argument("--cache-dir")
    p.add_argument("--test-file")
    p.add_argument("--now", type=int)  # test hook; real runs use time.time()
    return p.parse_args(argv)


class _FileClient:
    def __init__(self, routes):
        self._r = routes
    def get(self, path, params=None):
        return self._r.get(path)


def _make_client(args):
    if args.test_file:
        with open(args.test_file, encoding="utf-8") as fh:
            return _FileClient(json.load(fh))
    return PbsClient(args.hostaddress, args.port, args.token_id, args.token_secret,
                     verify=not args.no_verify_tls, cafile=args.cacert)


def _cache_path(args):
    base = args.cache_dir or os.path.join(
        os.environ.get("OMD_ROOT", "/tmp"), "tmp", "check_mk", "oposs_pbs")
    return os.path.join(base, f"{args.hostaddress}.json")


def _print_section(name, payload):
    print(f"<<<{name}:sep(0)>>>")
    print(json.dumps(payload, separators=(",", ":")))


def main(argv=None):
    replace_passwords()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    regex = None
    if args.piggyback_regex and "=" in args.piggyback_regex:
        pat, repl = args.piggyback_regex.split("=", 1)
        regex = (pat, repl)
    opts = collect_mod.Options(
        include=args.include_datastore, exclude=args.exclude_datastore,
        task_limit=args.task_limit, piggyback_template=args.piggyback_template,
        piggyback_regex=regex, no_piggyback=set(args.no_piggyback_datastore))

    import time
    now = args.now if args.now is not None else int(time.time())
    cache_path = _cache_path(args)
    cache = StateCache.load(cache_path)
    client = _make_client(args)

    host, piggyback = collect_mod.collect(client, opts, cache, now)

    _print_section("oposs_pbs_server", host.get("oposs_pbs_server", {}))
    if "oposs_pbs_datastore" in host:
        _print_section("oposs_pbs_datastore", host["oposs_pbs_datastore"])
    if "oposs_pbs_jobs" in host:
        _print_section("oposs_pbs_jobs", host["oposs_pbs_jobs"])

    for host_name, record in piggyback:
        if not host_name:
            continue
        print(f"<<<<{host_name}>>>>")
        _print_section("oposs_pbs_backup", record)
        print("<<<<>>>>")

    try:
        cache.save(cache_path)
    except OSError:
        pass
    return 0 if host.get("oposs_pbs_server", {}).get("reachable") else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Make executable and run the test**

```bash
chmod +x local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/agent_oposs_pbs
pytest tests/test_agent_cli.py -q
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: agent entry script with offline test-file mode and piggyback output

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Server-side calls

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/server_side_calls/oposs_pbs.py`
- Test: `tests/test_server_side_calls.py`

**Interfaces:**
- Produces: `special_agent_oposs_pbs = SpecialAgentConfig(name="oposs_pbs", ...)`. Params model fields: `token_id: str`, `token_secret: Secret`, `port: int | None`, `verify_tls: bool = True`, `cacert: str | None`, `datastore_include: list[str]`, `datastore_exclude: list[str]`, `task_limit: int = 1000`, `piggyback_template: str = "{id}"`, `piggyback_regex: str | None`, `no_piggyback: list[str]`. `commands_function` builds argv with the **bare** `token_secret` Secret (password-store reference) and the host address last.

- [ ] **Step 1: Write failing test**

`tests/test_server_side_calls.py`:
```python
from conftest import load_module
from cmk.server_side_calls.v1 import HostConfig, Secret
ssc = load_module("server_side_calls/oposs_pbs.py", "oposs_pbs_ssc")


def test_command_arguments_use_bare_secret_and_host_last():
    params = ssc.Params(token_id="root@pam!mon", token_secret=Secret(3),
                        verify_tls=True, task_limit=500,
                        datastore_exclude=["^tmp"], piggyback_template="{type}-{id}")
    cmds = list(ssc.special_agent_oposs_pbs.commands_function(
        params, HostConfig(name="pbs01")))
    args = cmds[0].command_arguments
    assert args[-1] == "10.0.0.1"                       # host address last
    assert "--token-id" in args and "root@pam!mon" in args
    # bare Secret (pass_safely True) -> password-store reference, not plaintext
    sec = args[args.index("--token-secret") + 1]
    assert isinstance(sec, Secret) and sec.pass_safely is True
    assert "--exclude-datastore" in args and "^tmp" in args
    assert "--task-limit" in args and "500" in args
    assert "--piggyback-template" in args and "{type}-{id}" in args
    assert "--no-verify-tls" not in args                # verify default on
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_server_side_calls.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement server-side calls**

`server_side_calls/oposs_pbs.py`:
```python
"""Translate ruleset params into agent_oposs_pbs command-line arguments."""
from collections.abc import Iterator

from pydantic import BaseModel
from cmk.server_side_calls.v1 import (
    HostConfig, Secret, SpecialAgentCommand, SpecialAgentConfig,
)


class Params(BaseModel):
    token_id: str
    token_secret: Secret
    port: int | None = None
    verify_tls: bool = True
    cacert: str | None = None
    datastore_include: list[str] = []
    datastore_exclude: list[str] = []
    task_limit: int = 1000
    piggyback_template: str = "{id}"
    piggyback_regex: str | None = None
    no_piggyback: list[str] = []


def _commands(params: Params, host_config: HostConfig) -> Iterator[SpecialAgentCommand]:
    args: list = ["--token-id", params.token_id,
                  "--token-secret", params.token_secret]  # bare Secret => pw-store ref
    if params.port:
        args += ["--port", str(params.port)]
    if not params.verify_tls:
        args.append("--no-verify-tls")
    if params.cacert:
        args += ["--cacert", params.cacert]
    for pat in params.datastore_include:
        args += ["--include-datastore", pat]
    for pat in params.datastore_exclude:
        args += ["--exclude-datastore", pat]
    args += ["--task-limit", str(params.task_limit)]
    args += ["--piggyback-template", params.piggyback_template]
    if params.piggyback_regex:
        args += ["--piggyback-regex", params.piggyback_regex]
    for ds in params.no_piggyback:
        args += ["--no-piggyback-datastore", ds]
    args.append(host_config.primary_ip_config.address or host_config.name)
    yield SpecialAgentCommand(command_arguments=args)


special_agent_oposs_pbs = SpecialAgentConfig(
    name="oposs_pbs",
    parameter_parser=Params.model_validate,
    commands_function=_commands,
)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_server_side_calls.py -q`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: server-side calls with secure password-store secret passing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Rulesets

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/rulesets/oposs_pbs.py`
- Test: `tests/test_rulesets.py`

**Interfaces:**
- Produces:
  - `rule_spec_special_agent_oposs_pbs = SpecialAgent(name="oposs_pbs", topic=Topic.STORAGE, parameter_form=_agent_form)` — form with keys `token_id, token_secret, port, verify_tls, cacert, datastore_include, datastore_exclude, task_limit, piggyback_template, piggyback_regex, no_piggyback`.
  - `rule_spec_oposs_pbs_datastore = CheckParameters(name="oposs_pbs_datastore", ...)` — `usage_levels` (SimpleLevels %, default 80/90), `gc_age_levels`.
  - `rule_spec_oposs_pbs_job = CheckParameters(name="oposs_pbs_job", ...)` — `age_levels` (optional).
  - `rule_spec_oposs_pbs_backup = CheckParameters(name="oposs_pbs_backup", ...)` — `warn_missed` (Integer, 2), `crit_missed` (Integer, 3), `fallback_interval` (TimeSpan, 86400), `unverified_state` (SingleChoice OK/WARN, default OK).
- Note: these `name=` strings are referenced by `check_ruleset_name=` in Tasks 9–11. Check-params rule specs use `HostAndItemCondition` (all four services have items).

- [ ] **Step 1: Write failing smoke tests**

`tests/test_rulesets.py`:
```python
from conftest import load_module
rs = load_module("rulesets/oposs_pbs.py", "oposs_pbs_rulesets")


def test_specs_exist_with_matching_names():
    assert rs.rule_spec_special_agent_oposs_pbs.kwargs["name"] == "oposs_pbs"
    assert rs.rule_spec_oposs_pbs_datastore.kwargs["name"] == "oposs_pbs_datastore"
    assert rs.rule_spec_oposs_pbs_job.kwargs["name"] == "oposs_pbs_job"
    assert rs.rule_spec_oposs_pbs_backup.kwargs["name"] == "oposs_pbs_backup"


def test_agent_form_has_required_elements():
    form = rs._agent_form()  # returns Dictionary recorder
    elements = form.kwargs["elements"]
    for key in ("token_id", "token_secret", "verify_tls", "piggyback_template"):
        assert key in elements
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_rulesets.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement rulesets**

`rulesets/oposs_pbs.py`:
```python
"""GUI configuration: special-agent form and check-parameter forms."""
from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import (
    BooleanChoice, DefaultValue, DictElement, Dictionary, Integer, List,
    Password, RegularExpression, SimpleLevels, SingleChoice, SingleChoiceElement,
    String, TimeSpan, TimeMagnitude, LevelDirection, validators,
)
from cmk.rulesets.v1.rule_specs import (
    CheckParameters, HostAndItemCondition, SpecialAgent, Topic,
)


def _agent_form() -> Dictionary:
    return Dictionary(
        title=Title("Proxmox Backup Server (REST API)"),
        help_text=Help("Monitor a Proxmox Backup Server via its REST API using an "
                       "API token. No software is installed on the PBS host."),
        elements={
            "token_id": DictElement(required=True, parameter_form=String(
                title=Title("API token ID"),
                help_text=Help("Form: user@realm!tokenname"),
                custom_validate=[validators.LengthInRange(min_value=3)])),
            "token_secret": DictElement(required=True, parameter_form=Password(
                title=Title("API token secret"))),
            "port": DictElement(parameter_form=Integer(
                title=Title("TCP port"), prefill=DefaultValue(8007),
                custom_validate=[validators.NetworkPort()])),
            "verify_tls": DictElement(parameter_form=BooleanChoice(
                title=Title("Verify TLS certificate"),
                label=Label("Verify the PBS server certificate"),
                prefill=DefaultValue(True))),
            "cacert": DictElement(parameter_form=String(
                title=Title("CA certificate file (path on the Checkmk server)"))),
            "datastore_include": DictElement(parameter_form=List(
                title=Title("Only these datastores (regex)"),
                element_template=RegularExpression(title=Title("Pattern")))),
            "datastore_exclude": DictElement(parameter_form=List(
                title=Title("Exclude these datastores (regex)"),
                element_template=RegularExpression(title=Title("Pattern")))),
            "task_limit": DictElement(parameter_form=Integer(
                title=Title("Task list fetch limit"), prefill=DefaultValue(1000))),
            "piggyback_template": DictElement(parameter_form=String(
                title=Title("Piggyback host template"),
                help_text=Help("Placeholders: {id} {type} {comment}"),
                prefill=DefaultValue("{id}"))),
            "piggyback_regex": DictElement(parameter_form=String(
                title=Title("Piggyback host rewrite (PATTERN=REPLACEMENT)"))),
            "no_piggyback": DictElement(parameter_form=List(
                title=Title("Datastores without per-guest piggyback"),
                element_template=String(title=Title("Datastore")))),
        },
    )


rule_spec_special_agent_oposs_pbs = SpecialAgent(
    name="oposs_pbs", title=Title("Proxmox Backup Server (REST API)"),
    topic=Topic.STORAGE, parameter_form=_agent_form)


def _datastore_form() -> Dictionary:
    return Dictionary(elements={
        "usage_levels": DictElement(parameter_form=SimpleLevels(
            title=Title("Datastore usage levels"), level_direction=LevelDirection.UPPER,
            form_spec_template=Integer(unit_symbol="%"),
            prefill_fixed_levels=DefaultValue((80.0, 90.0)))),
        "gc_age_levels": DictElement(parameter_form=SimpleLevels(
            title=Title("Maximum age since last garbage collection"),
            level_direction=LevelDirection.UPPER,
            form_spec_template=TimeSpan(displayed_magnitudes=[TimeMagnitude.DAY,
                                                              TimeMagnitude.HOUR]),
            prefill_fixed_levels=DefaultValue((None, None)))),
    })


rule_spec_oposs_pbs_datastore = CheckParameters(
    name="oposs_pbs_datastore", title=Title("PBS datastore"),
    topic=Topic.STORAGE, parameter_form=_datastore_form,
    condition=HostAndItemCondition(item_title=Title("Datastore")))


def _job_form() -> Dictionary:
    return Dictionary(elements={
        "age_levels": DictElement(parameter_form=SimpleLevels(
            title=Title("Maximum age since last successful run"),
            level_direction=LevelDirection.UPPER,
            form_spec_template=TimeSpan(displayed_magnitudes=[TimeMagnitude.DAY,
                                                              TimeMagnitude.HOUR]),
            prefill_fixed_levels=DefaultValue((None, None)))),
    })


rule_spec_oposs_pbs_job = CheckParameters(
    name="oposs_pbs_job", title=Title("PBS job (sync/verify/prune)"),
    topic=Topic.STORAGE, parameter_form=_job_form,
    condition=HostAndItemCondition(item_title=Title("Job")))


def _backup_form() -> Dictionary:
    return Dictionary(elements={
        "warn_missed": DictElement(parameter_form=Integer(
            title=Title("WARN after N missed backups"), prefill=DefaultValue(2))),
        "crit_missed": DictElement(parameter_form=Integer(
            title=Title("CRIT after N missed backups"), prefill=DefaultValue(3))),
        "fallback_interval": DictElement(parameter_form=TimeSpan(
            title=Title("Fallback interval when cadence is unknown"),
            displayed_magnitudes=[TimeMagnitude.DAY, TimeMagnitude.HOUR],
            prefill=DefaultValue(86400.0))),
        "unverified_state": DictElement(parameter_form=SingleChoice(
            title=Title("State when newest snapshot is unverified"),
            elements=[SingleChoiceElement(name="ok", title=Title("OK")),
                      SingleChoiceElement(name="warn", title=Title("WARN"))],
            prefill=DefaultValue("ok"))),
    })


rule_spec_oposs_pbs_backup = CheckParameters(
    name="oposs_pbs_backup", title=Title("PBS backup freshness (piggyback)"),
    topic=Topic.STORAGE, parameter_form=_backup_form,
    condition=HostAndItemCondition(item_title=Title("Datastore/namespace")))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_rulesets.py -q`
Expected: 2 passed.

> Note: the stub `_Rec` records positional/keyword args; real Checkmk form specs use these exact keyword names (`form_spec_template`, `level_direction`, `prefill_fixed_levels`, `element_template`, `displayed_magnitudes`, `custom_validate`). These are verified against `cmk.rulesets.v1` 2.3. On-site validation happens in Task 15.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: special-agent and check-parameter rulesets

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Check plugins — parsers and PBS Server

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/agent_based/oposs_pbs.py`
- Test: `tests/test_check_server.py`

**Interfaces:**
- Produces (in `agent_based/oposs_pbs.py`, this task adds the first slice):
  - `parse_json(string_table)` → `json.loads(string_table[0][0])` or `{}` if empty.
  - `agent_section_oposs_pbs_server`, `_datastore`, `_jobs`, `_backup` (all using `parse_json`).
  - `check_plugin_oposs_pbs_server` — service `"PBS Server"`, no item.

- [ ] **Step 1: Write failing test**

`tests/test_check_server.py`:
```python
import json
from conftest import load_module
from cmk.agent_based.v2 import State
m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")


def _sec(d):
    return m.parse_json([[json.dumps(d)]])


def test_parse_json_empty():
    assert m.parse_json([]) == {}


def test_server_ok_and_unreachable():
    ok = list(m.check_oposs_pbs_server(_sec(
        {"reachable": True, "version": "3.2.7", "node": "pbs01",
         "datastore_count": 2})))
    assert ok[0].state is State.OK and "3.2.7" in ok[0].summary

    bad = list(m.check_oposs_pbs_server(_sec(
        {"reachable": False, "error": "timeout"})))
    assert bad[0].state is State.CRIT and "timeout" in bad[0].summary


def test_server_discovery():
    assert len(list(m.discover_oposs_pbs_server(_sec({"reachable": True})))) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_check_server.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement parsers + server check**

Create `agent_based/oposs_pbs.py` with the shared header and the server check:
```python
"""Check plugins for the oposs_pbs special agent."""
from __future__ import annotations
import json
import time

from cmk.agent_based.v2 import (
    AgentSection, CheckPlugin, CheckResult, DiscoveryResult, Metric, Result,
    Service, ServiceLabel, State, check_levels, render,
)


def parse_json(string_table):
    if not string_table or not string_table[0]:
        return {}
    try:
        return json.loads(string_table[0][0])
    except (ValueError, IndexError):
        return {}


agent_section_oposs_pbs_server = AgentSection(name="oposs_pbs_server", parse_function=parse_json)
agent_section_oposs_pbs_datastore = AgentSection(name="oposs_pbs_datastore", parse_function=parse_json)
agent_section_oposs_pbs_jobs = AgentSection(name="oposs_pbs_jobs", parse_function=parse_json)
agent_section_oposs_pbs_backup = AgentSection(name="oposs_pbs_backup", parse_function=parse_json)


# --- PBS Server -------------------------------------------------------------

def discover_oposs_pbs_server(section) -> DiscoveryResult:
    if section:
        yield Service()


def check_oposs_pbs_server(section) -> CheckResult:
    if not section:
        yield Result(state=State.UNKNOWN, summary="No data from agent")
        return
    if not section.get("reachable"):
        yield Result(state=State.CRIT,
                     summary=f"PBS API unreachable: {section.get('error', 'unknown error')}")
        return
    yield Result(state=State.OK, summary=(
        f"Version {section.get('version', '?')}, node {section.get('node', '?')}, "
        f"{section.get('datastore_count', 0)} datastore(s)"))


check_plugin_oposs_pbs_server = CheckPlugin(
    name="oposs_pbs_server", service_name="PBS Server",
    sections=["oposs_pbs_server"],
    discovery_function=discover_oposs_pbs_server,
    check_function=check_oposs_pbs_server)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_check_server.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: section parsers and PBS Server check

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Check plugin — PBS Datastore

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/agent_based/oposs_pbs.py` (append)
- Test: `tests/test_check_datastore.py`

**Interfaces:**
- Consumes: `parse_json`, `check_levels`, `render` (Task 8); helper `_dedup_factor` (define here, mirrors util).
- Produces: `discover_oposs_pbs_datastore`, `check_oposs_pbs_datastore(item, params, section)`, `check_plugin_oposs_pbs_datastore` — service `"PBS Datastore %s"`, `check_ruleset_name="oposs_pbs_datastore"`, defaults `{"usage_levels": ("fixed", (80.0, 90.0)), "gc_age_levels": ("no_levels", None)}`. Metrics: `oposs_pbs_datastore_size/used/avail/used_pct/group_count/backup_count/gc_age/dedup_factor`.

- [ ] **Step 1: Write failing test**

`tests/test_check_datastore.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_check_datastore.py -q`
Expected: FAIL.

- [ ] **Step 3: Append the datastore check**

Append to `agent_based/oposs_pbs.py`:
```python
# --- PBS Datastore ----------------------------------------------------------

def _dedup_factor(index_data_bytes, disk_bytes):
    try:
        if not disk_bytes or index_data_bytes is None:
            return None
        return float(index_data_bytes) / float(disk_bytes)
    except (TypeError, ZeroDivisionError):
        return None


def discover_oposs_pbs_datastore(section) -> DiscoveryResult:
    for store in section or {}:
        yield Service(item=store, labels=[ServiceLabel("oposs_pbs/datastore", "yes")])


def check_oposs_pbs_datastore(item, params, section) -> CheckResult:
    ds = (section or {}).get(item)
    if ds is None:
        return
    total = ds.get("total") or 0
    used = ds.get("used") or 0
    avail = ds.get("avail") or 0
    used_pct = (used / total * 100.0) if total else 0.0

    yield from check_levels(
        used_pct, levels_upper=params.get("usage_levels"),
        metric_name="oposs_pbs_datastore_used_pct", label="Usage",
        render_func=render.percent, boundaries=(0.0, 100.0))
    yield Metric("oposs_pbs_datastore_size", float(total))
    yield Metric("oposs_pbs_datastore_used", float(used))
    yield Metric("oposs_pbs_datastore_avail", float(avail))
    yield Result(state=State.OK, notice=(
        f"Size {render.bytes(total)}, used {render.bytes(used)}, "
        f"free {render.bytes(avail)}"))

    yield Metric("oposs_pbs_group_count", float(ds.get("group_count", 0)))
    yield Metric("oposs_pbs_backup_count", float(ds.get("backup_count", 0)))
    yield Result(state=State.OK, notice=(
        f"{ds.get('backup_count', 0)} backups in {ds.get('group_count', 0)} groups"))

    gc = ds.get("gc") or {}
    factor = _dedup_factor(gc.get("index_data_bytes"), gc.get("disk_bytes"))
    if factor is not None:
        yield Metric("oposs_pbs_dedup_factor", factor)
        yield Result(state=State.OK, notice=f"Deduplication factor {factor:.2f}")

    if gc.get("running"):
        yield Result(state=State.OK, summary="GC running")
    elif gc.get("status") is None:
        yield Result(state=State.UNKNOWN, summary="GC not run yet")
    elif gc.get("status") == "OK":
        end = gc.get("endtime")
        if end:
            age = max(0.0, time.time() - end)
            yield from check_levels(
                age, levels_upper=params.get("gc_age_levels"),
                metric_name="oposs_pbs_gc_age", label="Last GC",
                render_func=render.timespan)
        else:
            yield Result(state=State.OK, summary="GC ok")
    else:
        yield Result(state=State.WARN, summary=f"GC failed: {gc.get('status')}")


check_plugin_oposs_pbs_datastore = CheckPlugin(
    name="oposs_pbs_datastore", service_name="PBS Datastore %s",
    sections=["oposs_pbs_datastore"],
    discovery_function=discover_oposs_pbs_datastore,
    check_function=check_oposs_pbs_datastore,
    check_ruleset_name="oposs_pbs_datastore",
    check_default_parameters={"usage_levels": ("fixed", (80.0, 90.0)),
                              "gc_age_levels": ("no_levels", None)})
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_check_datastore.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: PBS Datastore check (usage, GC, dedup factor)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Check plugins — Sync / Verify / Prune jobs

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/agent_based/oposs_pbs.py` (append)
- Test: `tests/test_check_jobs.py`

**Interfaces:**
- Produces: item builders `_sync_item`, `_verify_item`, `_prune_item`; a shared `_check_job(job, params, kind, metric)`; three discovery + three check functions; `check_plugin_oposs_pbs_sync/_verify/_prune`. Services `"PBS Sync Job %s"`, `"PBS Verify Job %s"`, `"PBS Prune Job %s"`, all `check_ruleset_name="oposs_pbs_job"`, defaults `{"age_levels": ("no_levels", None)}`. Metrics `oposs_pbs_sync_age/verify_age/prune_age`.
- Item formats: sync `"{remote}:{remote-store} -> {ns}"` (or without `-> ns` when ns empty); verify `"{store}/{ns}"` or `"{store}"`; prune `"{store}/{ns}"` or `"{store}"`.

- [ ] **Step 1: Write failing test**

`tests/test_check_jobs.py`:
```python
from conftest import load_module
from cmk.agent_based.v2 import State, Metric
m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")

NOW = 1_000_000
JOBS = {
    "sync": [{"id": "s1", "store": "main", "remote": "r1", "remote-store": "rs",
              "ns": "", "schedule": "daily",
              "last_run": {"status": "OK", "endtime": NOW - 100}, "running": False}],
    "verify": [{"id": "v1", "store": "main", "schedule": "weekly",
                "last_run": {"status": "bad chunks"}, "running": False}],
    "prune": [{"id": "p1", "store": "main", "schedule": "daily",
               "last_run": None, "running": False}],
}


def test_sync_item_and_ok(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    items = [s.item for s in m.discover_oposs_pbs_sync(JOBS)]
    assert items == ["r1:rs"]
    res = list(m.check_oposs_pbs_sync("r1:rs", {"age_levels": ("no_levels", None)}, JOBS))
    assert res[0].state is State.OK
    assert any(isinstance(r, Metric) and r.name == "oposs_pbs_sync_age" for r in res)


def test_verify_failure_is_crit():
    res = list(m.check_oposs_pbs_verify("main", {"age_levels": ("no_levels", None)}, JOBS))
    assert res[0].state is State.CRIT and "bad chunks" in res[0].summary


def test_prune_never_run_is_ok():
    res = list(m.check_oposs_pbs_prune("main", {"age_levels": ("no_levels", None)}, JOBS))
    assert res[0].state is State.OK and "No completed" in res[0].summary
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_check_jobs.py -q`
Expected: FAIL.

- [ ] **Step 3: Append job checks**

Append to `agent_based/oposs_pbs.py`:
```python
# --- Jobs: sync / verify / prune --------------------------------------------

def _sync_item(job) -> str:
    base = f"{job.get('remote', '?')}:{job.get('remote-store', '?')}"
    ns = job.get("ns")
    return f"{base} -> {ns}" if ns else base


def _store_ns_item(job) -> str:
    store = job.get("store", "?")
    ns = job.get("ns")
    return f"{store}/{ns}" if ns else store


def _check_job(job, params, kind: str, metric: str) -> CheckResult:
    if job is None:
        return
    if job.get("running"):
        yield Result(state=State.OK, summary=f"{kind} running")
        return
    last = job.get("last_run")
    if not last:
        yield Result(state=State.OK, summary=f"No completed {kind} run yet")
        return
    status = last.get("status")
    end = last.get("endtime")
    if status == "OK":
        if end:
            age = max(0.0, time.time() - end)
            yield from check_levels(age, levels_upper=params.get("age_levels"),
                                    metric_name=metric, label=f"Last {kind}",
                                    render_func=render.timespan)
        else:
            yield Result(state=State.OK, summary=f"Last {kind} OK")
    else:
        when = f" at {render.datetime(end)}" if end else ""
        yield Result(state=State.CRIT, summary=f"Last {kind} failed{when}: {status}")


def discover_oposs_pbs_sync(section) -> DiscoveryResult:
    for j in (section or {}).get("sync", []):
        if j.get("id"):
            yield Service(item=_sync_item(j))


def check_oposs_pbs_sync(item, params, section) -> CheckResult:
    job = {(_sync_item(j)): j for j in (section or {}).get("sync", []) if j.get("id")}.get(item)
    yield from _check_job(job, params, "sync", "oposs_pbs_sync_age")


def discover_oposs_pbs_verify(section) -> DiscoveryResult:
    for j in (section or {}).get("verify", []):
        if j.get("id"):
            yield Service(item=_store_ns_item(j))


def check_oposs_pbs_verify(item, params, section) -> CheckResult:
    job = {(_store_ns_item(j)): j for j in (section or {}).get("verify", []) if j.get("id")}.get(item)
    yield from _check_job(job, params, "verification", "oposs_pbs_verify_age")


def discover_oposs_pbs_prune(section) -> DiscoveryResult:
    for j in (section or {}).get("prune", []):
        if j.get("id"):
            yield Service(item=_store_ns_item(j))


def check_oposs_pbs_prune(item, params, section) -> CheckResult:
    job = {(_store_ns_item(j)): j for j in (section or {}).get("prune", []) if j.get("id")}.get(item)
    yield from _check_job(job, params, "prune", "oposs_pbs_prune_age")


_JOB_DEFAULTS = {"age_levels": ("no_levels", None)}

check_plugin_oposs_pbs_sync = CheckPlugin(
    name="oposs_pbs_sync", service_name="PBS Sync Job %s", sections=["oposs_pbs_jobs"],
    discovery_function=discover_oposs_pbs_sync, check_function=check_oposs_pbs_sync,
    check_ruleset_name="oposs_pbs_job", check_default_parameters=_JOB_DEFAULTS)

check_plugin_oposs_pbs_verify = CheckPlugin(
    name="oposs_pbs_verify", service_name="PBS Verify Job %s", sections=["oposs_pbs_jobs"],
    discovery_function=discover_oposs_pbs_verify, check_function=check_oposs_pbs_verify,
    check_ruleset_name="oposs_pbs_job", check_default_parameters=_JOB_DEFAULTS)

check_plugin_oposs_pbs_prune = CheckPlugin(
    name="oposs_pbs_prune", service_name="PBS Prune Job %s", sections=["oposs_pbs_jobs"],
    discovery_function=discover_oposs_pbs_prune, check_function=check_oposs_pbs_prune,
    check_ruleset_name="oposs_pbs_job", check_default_parameters=_JOB_DEFAULTS)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_check_jobs.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: PBS sync/verify/prune job checks

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Check plugin — PBS Backup (piggyback freshness)

**Files:**
- Modify: `local/lib/python3/cmk_addons/plugins/oposs_pbs/agent_based/oposs_pbs.py` (append)
- Test: `tests/test_check_backup.py`

**Interfaces:**
- Produces: `_backup_item(rec)` = `datastore[/ns]`; `discover_oposs_pbs_backup`; `check_oposs_pbs_backup(item, params, section)`; `check_plugin_oposs_pbs_backup` — service `"PBS Backup %s"`, `check_ruleset_name="oposs_pbs_backup"`, defaults `{"warn_missed": 2, "crit_missed": 3, "fallback_interval": 86400.0, "unverified_state": "ok"}`. Metrics `oposs_pbs_backup_age`, `oposs_pbs_backup_size`.
- The section is a *single* backup record (piggyback host → one datastore/ns per record); discovery yields one Service per record. (If a guest has multiple datastore/ns records they land on the same piggyback host as distinct items.)

- [ ] **Step 1: Write failing test**

`tests/test_check_backup.py`:
```python
from conftest import load_module
from cmk.agent_based.v2 import State, Metric
m = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks")

NOW = 1_000_000
DAY = 86400
DEFAULTS = {"warn_missed": 2, "crit_missed": 3,
            "fallback_interval": 86400.0, "unverified_state": "ok"}


def rec(**kw):
    base = {"datastore": "main", "ns": "", "backup_type": "vm", "backup_id": "100",
            "last_backup": NOW - 3600, "backup_count": 7, "interval": DAY,
            "interval_known": True, "verify_state": "ok", "data_size": 41_000_000_000}
    base.update(kw)
    return base


def _states(res):
    return [r.state for r in res if hasattr(r, "state")]


def test_fresh_backup_ok(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS, rec()))
    assert State.WARN not in _states(res) and State.CRIT not in _states(res)
    mt = {r.name: r.value for r in res if isinstance(r, Metric)}
    assert mt["oposs_pbs_backup_size"] == 41_000_000_000
    assert mt["oposs_pbs_backup_age"] == 3600


def test_missed_two_intervals_warns(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS,
                                        rec(last_backup=NOW - 2 * DAY - 10)))
    assert State.WARN in _states(res)


def test_missed_three_intervals_crit(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS,
                                        rec(last_backup=NOW - 3 * DAY - 10)))
    assert State.CRIT in _states(res)


def test_verify_failed_is_crit(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS, rec(verify_state="failed")))
    assert State.CRIT in _states(res)


def test_unknown_interval_uses_fallback(monkeypatch):
    monkeypatch.setattr(m.time, "time", lambda: NOW)
    res = list(m.check_oposs_pbs_backup("main", DEFAULTS,
               rec(interval=None, interval_known=False, last_backup=NOW - 3 * DAY)))
    assert State.CRIT in _states(res)  # 3 * fallback(1d) missed
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_check_backup.py -q`
Expected: FAIL.

- [ ] **Step 3: Append the backup check**

Append to `agent_based/oposs_pbs.py`:
```python
# --- PBS Backup freshness (piggyback) ---------------------------------------

def _backup_item(rec) -> str:
    ns = rec.get("ns")
    return f"{rec['datastore']}/{ns}" if ns else rec.get("datastore", "?")


def discover_oposs_pbs_backup(section) -> DiscoveryResult:
    if section and section.get("datastore"):
        yield Service(item=_backup_item(section))


def check_oposs_pbs_backup(item, params, section) -> CheckResult:
    if not section or _backup_item(section) != item:
        return
    now = time.time()
    last = section.get("last_backup") or 0
    age = max(0.0, now - last)
    interval = section.get("interval") if section.get("interval_known") \
        else params.get("fallback_interval", 86400.0)
    if not interval:
        interval = params.get("fallback_interval", 86400.0)

    warn_missed = params.get("warn_missed", 2)
    crit_missed = params.get("crit_missed", 3)
    levels = ("fixed", (warn_missed * interval, crit_missed * interval))
    suffix = "" if section.get("interval_known") else " (assumed cadence)"
    yield from check_levels(
        age, levels_upper=levels, metric_name="oposs_pbs_backup_age",
        label="Last backup age", render_func=render.timespan)
    yield Result(state=State.OK, notice=(
        f"Cadence ~{render.timespan(interval)}{suffix}, "
        f"{section.get('backup_count', 0)} snapshots"))

    size = section.get("data_size") or 0
    yield Metric("oposs_pbs_backup_size", float(size))
    yield Result(state=State.OK, notice=f"Protected data {render.bytes(size)}")

    vstate = section.get("verify_state", "none")
    if vstate == "failed":
        yield Result(state=State.CRIT, summary="Newest snapshot verification failed")
    elif vstate == "ok":
        yield Result(state=State.OK, notice="Newest snapshot verified OK")
    else:  # none / unverified
        unver = State.WARN if params.get("unverified_state") == "warn" else State.OK
        yield Result(state=unver, notice="Newest snapshot not verified")


check_plugin_oposs_pbs_backup = CheckPlugin(
    name="oposs_pbs_backup", service_name="PBS Backup %s",
    sections=["oposs_pbs_backup"],
    discovery_function=discover_oposs_pbs_backup,
    check_function=check_oposs_pbs_backup,
    check_ruleset_name="oposs_pbs_backup",
    check_default_parameters={"warn_missed": 2, "crit_missed": 3,
                              "fallback_interval": 86400.0, "unverified_state": "ok"})
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_check_backup.py -q`
Expected: 5 passed. Then run the full suite: `pytest -q` (all green).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: PBS Backup piggyback check (missed-backup freshness + verification + size)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: Graphing (metrics, graphs, perfometers)

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/graphing/oposs_pbs.py`
- Test: `tests/test_graphing.py`

**Interfaces:**
- Produces `metric_*` for every metric emitted by the checks, plus a few graphs/perfometers. Metric names must exactly match Tasks 9–11.

- [ ] **Step 1: Write failing smoke test**

`tests/test_graphing.py`:
```python
from conftest import load_module
g = load_module("graphing/oposs_pbs.py", "oposs_pbs_graphing")


def test_key_metrics_defined():
    for var in ("metric_oposs_pbs_datastore_used", "metric_oposs_pbs_dedup_factor",
                "metric_oposs_pbs_backup_age", "metric_oposs_pbs_backup_size",
                "metric_oposs_pbs_backup_count"):
        assert hasattr(g, var)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_graphing.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement graphing**

`graphing/oposs_pbs.py`:
```python
"""Metric, graph and perfometer definitions for oposs_pbs."""
from cmk.graphing.v1 import Title
from cmk.graphing.v1.graphs import Graph, MinimalRange
from cmk.graphing.v1.metrics import (
    Color, DecimalNotation, IECNotation, Metric, TimeNotation, Unit,
)
from cmk.graphing.v1.perfometers import Closed, FocusRange, Perfometer

_BYTES = Unit(IECNotation("B"))
_PCT = Unit(DecimalNotation("%"))
_COUNT = Unit(DecimalNotation(""))
_SECONDS = Unit(TimeNotation())
_FACTOR = Unit(DecimalNotation("x"))

metric_oposs_pbs_datastore_size = Metric(name="oposs_pbs_datastore_size",
    title=Title("Datastore size"), unit=_BYTES, color=Color.GRAY)
metric_oposs_pbs_datastore_used = Metric(name="oposs_pbs_datastore_used",
    title=Title("Datastore used"), unit=_BYTES, color=Color.BLUE)
metric_oposs_pbs_datastore_avail = Metric(name="oposs_pbs_datastore_avail",
    title=Title("Datastore available"), unit=_BYTES, color=Color.GREEN)
metric_oposs_pbs_datastore_used_pct = Metric(name="oposs_pbs_datastore_used_pct",
    title=Title("Datastore usage"), unit=_PCT, color=Color.ORANGE)
metric_oposs_pbs_group_count = Metric(name="oposs_pbs_group_count",
    title=Title("Backup groups"), unit=_COUNT, color=Color.LIGHT_PURPLE)
metric_oposs_pbs_backup_count = Metric(name="oposs_pbs_backup_count",
    title=Title("Backups"), unit=_COUNT, color=Color.LIGHT_BLUE)
metric_oposs_pbs_dedup_factor = Metric(name="oposs_pbs_dedup_factor",
    title=Title("Deduplication factor"), unit=_FACTOR, color=Color.PURPLE)
metric_oposs_pbs_gc_age = Metric(name="oposs_pbs_gc_age",
    title=Title("Time since last GC"), unit=_SECONDS, color=Color.CYAN)
metric_oposs_pbs_sync_age = Metric(name="oposs_pbs_sync_age",
    title=Title("Time since last sync"), unit=_SECONDS, color=Color.CYAN)
metric_oposs_pbs_verify_age = Metric(name="oposs_pbs_verify_age",
    title=Title("Time since last verification"), unit=_SECONDS, color=Color.CYAN)
metric_oposs_pbs_prune_age = Metric(name="oposs_pbs_prune_age",
    title=Title("Time since last prune"), unit=_SECONDS, color=Color.CYAN)
metric_oposs_pbs_backup_age = Metric(name="oposs_pbs_backup_age",
    title=Title("Backup age"), unit=_SECONDS, color=Color.ORANGE)
metric_oposs_pbs_backup_size = Metric(name="oposs_pbs_backup_size",
    title=Title("Protected data size"), unit=_BYTES, color=Color.BLUE)

graph_oposs_pbs_datastore = Graph(
    name="oposs_pbs_datastore", title=Title("Datastore usage"),
    simple_lines=["oposs_pbs_datastore_used", "oposs_pbs_datastore_avail",
                  "oposs_pbs_datastore_size"],
    optional=["oposs_pbs_datastore_avail", "oposs_pbs_datastore_size"])

graph_oposs_pbs_backups = Graph(
    name="oposs_pbs_backups", title=Title("Backups"),
    simple_lines=["oposs_pbs_backup_count", "oposs_pbs_group_count"],
    optional=["oposs_pbs_group_count"])

perfometer_oposs_pbs_usage = Perfometer(
    name="oposs_pbs_datastore_used_pct",
    focus_range=FocusRange(Closed(0), Closed(100)),
    segments=["oposs_pbs_datastore_used_pct"])
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_graphing.py -q`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: metrics, graphs and perfometer for oposs_pbs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: Checkman documentation

**Files:**
- Create: `local/lib/python3/cmk_addons/plugins/oposs_pbs/checkman/oposs_pbs`

**Interfaces:** none (documentation).

- [ ] **Step 1: Write the checkman file**

`checkman/oposs_pbs`:
```
title: Proxmox Backup Server (REST API)
agents: oposs_pbs
catalog: os/storage
license: GPLv2
distribution: check_mk

description:
 Monitors a Proxmox Backup Server (PBS) via its REST API using an API token,
 from the Checkmk server (no software installed on the PBS host).

 Services:
 - {PBS Server}: API reachability, version and node.
 - {PBS Datastore <name>}: usage levels, backup/group counts, garbage-collection
   state, and the datastore-wide deduplication factor (index-data-bytes /
   disk-bytes from gc-status).
 - {PBS Sync Job}, {PBS Verify Job}, {PBS Prune Job}: last scheduled-run state
   with optional age levels.
 - {PBS Backup <datastore>} (piggyback, on the guest's host): backup freshness as
   "missed backups" against the observed snapshot interval, newest-snapshot
   verification state, and the logical protected-data size.

 Note on per-guest disk usage: PBS deduplicates chunks datastore-wide, so the
 real on-disk footprint of a single guest is not available from the REST API.
 The reported backup size is the logical (pre-dedup) protected data size. True
 per-group usage requires a host-side index-walk (e.g. PBS_Chunk_Checker) and is
 out of scope; native support is tracked upstream in Proxmox Bugzilla #5799.

item:
 The datastore name, job identifier, or datastore/namespace, depending on the
 service.

discovery:
 One {PBS Server} service per PBS host; one service per datastore, per configured
 job, and (piggyback) per backed-up guest.
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "docs: checkman page for oposs_pbs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 14: MKP packaging and CI

**Files:**
- Create: `.mkp-builder.ini`
- Create: `.github/workflows/build.yml`
- Modify: `README.md` (create if absent)

**Interfaces:** none (build config).

- [ ] **Step 1: Write `.mkp-builder.ini`**

```ini
[package]
name = oposs_pbs
title = Proxmox Backup Server (REST API)
author = Tobias Oetiker <oetiker@gmail.com>
description = Monitors Proxmox Backup Server via its REST API (datastores, jobs, per-guest backup freshness via piggyback)
version.min_required = 2.3.0p1
version.packaged = 2.3.0p34
download_url = https://github.com/oposs/cmk-oposs_pbs
validate_python = true
```

- [ ] **Step 2: Write the GitHub workflow**

`.github/workflows/build.yml`:
```yaml
name: Build MKP
on:
  push:
    tags: ['v*']
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Extract version
        id: version
        run: echo "version=${GITHUB_REF#refs/tags/v}" >> "$GITHUB_OUTPUT"
      - name: Build MKP
        id: build
        uses: oposs/mkp-builder@v2
        with:
          version: ${{ steps.version.outputs.version }}
      - name: Create Release
        uses: softprops/action-gh-release@v2
        with:
          files: ${{ steps.build.outputs.package-file }}
```

- [ ] **Step 3: Write a short README**

`README.md` (skip if it already covers this): one paragraph describing the plugin, the API-token requirement (an **Audit**-role token on PBS), and a link to the design spec. Include the `local/lib/check_mk` symlink note for contributors.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "build: MKP builder config and release workflow

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 15: Live validation on a real PBS + Checkmk site

**Files:** none (verification task; may produce small fixups committed separately).

**Interfaces:** validates the whole plugin end-to-end and resolves the spec §10 open items.

- [ ] **Step 1: Run the agent by hand against a real PBS**

On the Checkmk server (or any host with `requests`), create an **Audit**-role API token in the PBS UI (Datastore → Permissions → API Tokens; grant `Datastore.Audit` + `Sys.Audit` on `/`). Then:
```bash
./local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/agent_oposs_pbs \
    <pbs-host> --token-id 'monitor@pbs!checkmk' --token-secret '<secret>' \
    --no-verify-tls --cache-dir /tmp/oposs_pbs_test
```
Expected: `<<<oposs_pbs_server:sep(0)>>>` with `reachable: true`, one `oposs_pbs_datastore` line, `oposs_pbs_jobs`, and `<<<<...>>>>` piggyback blocks. Confirm the spec §10 items:
- node name field from `/nodes` (or `localhost` fallback used);
- `counts`/`gc-status` present in `/admin/datastore/<ds>/status` (add `verbose=1` if `gc-status` is missing);
- `index-data-bytes` / `disk-bytes` present and `index/disk` ≈ the GUI dedup factor (guard div-by-zero before first GC — already handled by `_dedup_factor`).
Fix any field-name mismatches in `oposs_pbs_collect.py` and re-run.

- [ ] **Step 2: Install into the site and discover**

```bash
# copy the local/ tree into the site's ~/local/, or install the MKP
cmk -R
cmk -II <pbs-checkmk-host>
cmk --debug -v <pbs-checkmk-host>
```
Expected: `PBS Server`, `PBS Datastore <name>`, and job services appear and are OK/according to state. Verify piggyback: the guest hosts show a `PBS Backup <datastore>` service (guests must already exist as Checkmk hosts; otherwise the piggyback data waits in the spool).

- [ ] **Step 3: Verify rulesets render in the GUI**

In Setup → Agents / special agents, confirm the "Proxmox Backup Server (REST API)" rule renders (token id + secret, TLS, piggyback template). In Setup → Service monitoring rules, confirm the three check-parameter rules render. This is the real test of the ruleset form-spec keyword arguments the offline stubs could not fully validate.

- [ ] **Step 4: Commit any fixups**

```bash
git add -A && git commit -m "fix: reconcile with live PBS API responses

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage** (spec §6 services and §7 config vs. tasks):
- PBS Server → Task 8. PBS Datastore (usage, GC, dedup) → Task 9. Sync/Verify/Prune jobs → Task 10. PBS Backup piggyback (missed-backup freshness, verification, protected size) → Task 11. Special-agent + check-params rulesets → Task 7. server_side_calls (secure secret) → Task 6. Agent + collection + cache gating + piggyback → Tasks 1–5. Graphing → Task 12. Checkman with dedup/#5799 note → Task 13. MKP/CI → Task 14. Spec §10 live items → Task 15. Dedup factor (datastore-wide) → Task 9. `ondisk_size` #5799 → intentionally *not* implemented (deferred per spec §5.1); documented in Task 13. **No gaps.**

**Placeholder scan:** every code step contains full code; every test step contains real assertions; commands have expected output. No TODO/TBD.

**Type consistency:** `Options` fields (Task 4) match the agent's argparse wiring (Task 5) and the server_side_calls argv (Task 6). Section keys (`oposs_pbs_server/_datastore/_jobs/_backup`) are identical across agent output (Task 5), parsers (Task 8), and checks (Tasks 9–11). `backup_record` keys (Task 4) match `check_oposs_pbs_backup`'s reads (Task 11). Metric names in checks (Tasks 9–11) match `metric_*` definitions (Task 12). Job `last_run` shape `{status, endtime}` is produced in Task 4 and consumed in Task 10. `check_ruleset_name` values match `CheckParameters(name=...)` in Task 7.

**Note on offline stubs:** the cmk stubs let logic be tested without a site, but cannot validate exact form-spec keyword names or the real `check_levels`/`render` behavior — that is why Task 15 (live validation) is mandatory, not optional.
</content>
