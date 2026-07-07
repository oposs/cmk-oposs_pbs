# oposs_pbs — Proxmox Backup Server special agent (design)

Date: 2026-07-07
Status: approved-for-planning

## 1. Goal

Replace the existing agent-based `inett_proxmox_backup` plugin with a **server-side
special agent** that monitors Proxmox Backup Server (PBS) over its REST API, keeping
feature parity with the inett plugin and adding:

- datastore **usage** monitoring (a server-side agent has no local filesystem check to
  lean on, unlike the inett agent which deliberately skipped usage),
- **prune** job monitoring,
- per-guest backup **freshness** delivered via **piggyback** so it appears on the
  guest's own Checkmk host.

This is a **clean break**: new `oposs_pbs_*` names, no metric-history migration from the
inett plugin. The inett plugin is decommissioned separately.

Company/metric prefix: `oposs`. Package/plugin name: `oposs_pbs`.

## 2. Feature-parity baseline (inett_proxmox_backup)

| inett service | Item | Checks | Metrics |
|---|---|---|---|
| `inett PBS Datastore %s` | datastore | backup group count, total backups, GC last-run state | `inett_pbs_group_count`, `inett_pbs_total_backups` |
| `inett PBS Sync Job %s` | `remote:store -> ns` | last-run OK/CRIT | — |
| `inett PBS Verify Job %s` | `store[/ns]` | last-run OK/CRIT | — |

The inett agent collected: `task list --all --limit 1000`, `sync-job list`,
`verify-job list`, and per-datastore `groups` aggregated over all namespaces. GC/sync/
verify last-run state was derived from the task list by matching `worker_type` +
`worker_id`. We reproduce all of this over REST.

## 3. Architecture

Standard Checkmk 2.3 special-agent layout under
`local/lib/python3/cmk_addons/plugins/oposs_pbs/`:

```
__init__.py
libexec/agent_oposs_pbs          # data collector: REST -> agent sections (executable)
server_side_calls/oposs_pbs.py   # ruleset params -> agent CLI args
rulesets/oposs_pbs.py            # GUI: special agent config + check parameters
agent_based/oposs_pbs.py         # section parsers + check plugins
graphing/oposs_pbs.py            # metrics, graphs, perfometers
checkman/                        # documentation
```

Repository extras:
- `.mkp-builder.ini` — MKP packaging config (`oposs/mkp-builder` GitHub Action).
- `.github/workflows/build.yml` — build MKP on tag push.
- Symlink `local/lib/check_mk -> python3/cmk` (production path safety).

## 4. PBS REST API — verified facts

All paths are under the base prefix **`/api2/json`**. Default HTTPS port **8007**.
API-token auth header (exact):

```
Authorization: PBSAPIToken TOKENID:TOKENSECRET
```

where `TOKENID = user@realm!tokenname` and `TOKENSECRET` is the secret.

Endpoints used:

| Purpose | Method + path | Key response fields |
|---|---|---|
| Node name | `GET /nodes` | node name field (use result, fall back to `localhost`) |
| Datastore list | `GET /admin/datastore` | `store`, `comment`, `maintenance` |
| Datastore status | `GET /admin/datastore/{store}/status?verbose=1` | `total`, `used`, `avail` (bytes); `counts.{host,vm,ct,other}.{groups,snapshots}`; `gc-status{…}` |
| Namespaces | `GET /admin/datastore/{store}/namespace` | `ns` |
| Groups | `GET /admin/datastore/{store}/groups?ns={ns}` | `backup-type`, `backup-id`, `last-backup` (epoch int), `backup-count`, `comment`, `owner` |
| Snapshots (per group) | `GET /admin/datastore/{store}/snapshots?ns=&backup-type=&backup-id=` | `backup-time` (epoch int) per snapshot; `verification` object `{state, upid}` (optional) |
| Sync jobs | `GET /config/sync` | `id`, `store`, `remote` (opt), `remote-store`, `ns` (opt), `schedule`, `comment` |
| Verify jobs | `GET /config/verify` | `id`, `store`, `ns` (opt), `schedule`, `comment` |
| Prune jobs | `GET /config/prune` | `id`, `store`, `ns` (opt), `schedule`, `keep-*`, `disable`, `comment` |
| Tasks | `GET /nodes/{node}/tasks?limit=1000&typefilter=…` | `worker_type`, `worker_id`, `starttime`, `endtime`, `status`, `upid`, `user` |

Task `worker_type` / `worker_id` (verified against proxmox-backup source):

| Job | `worker_type` | `worker_id` structure | Match key |
|---|---|---|---|
| Garbage collection | `garbage_collection` | `{store}` | store |
| Sync job | `syncjob` | `{remote|-}:{remote-store}:{store}:{ns}:{jobid}` (ends with jobid) | trailing `:{jobid}` |
| Verify job | `verificationjob` | `{store}:{jobid}` (ends with jobid) | trailing `:{jobid}` |
| Prune job | `prunejob` | `{store}` or `{store}:{ns}` (does **not** end with jobid) | store + ns |

Notes / gotchas baked into the design:

- **No *per-guest* deduplicated disk usage** exists in the PBS API today, and it is not
  obtainable by a REST agent (it needs a host-side index-walk of `.fidx`/`.didx` +
  `.chunks/`; out of scope — see §9). A future PBS will expose per-backup-group referenced
  /unique chunk size, computed during GC (Bugzilla #5799, RFC patches posted, not yet in
  stable as of early 2026); §5.1 treats it as a deferred, non-breaking extension (its
  final field shape/granularity is unsettled — no placeholder committed now).
- A **datastore-wide deduplication factor** *is* derivable from `gc-status`:
  `dedup_factor = index-data-bytes / disk-bytes` (logical referenced bytes ÷ actual
  on-disk chunk bytes — the ratio the PBS GUI shows). Reported on the Datastore service.
  There is no single dedup *field*; we compute it from the two counters.
- Bare `prune` / `verify` / `verify_group` worker types are **manual one-off** operations,
  not scheduled jobs; we filter only the scheduled types above via `typefilter`.
- Group **verification state is not on the group object** — it lives per snapshot via
  `/snapshots`. `SnapshotVerifyState.state` is exactly **`"ok"` or `"failed"`**; a
  never-verified snapshot **omits** the `verification` object (that absence is the
  "unverified/none" case).
- `counts` may require `verbose=1`; confirm on a live box (see §10).

## 5. Agent output (sections)

The agent makes one invocation and prints newline-delimited sections. Each data section
uses `:sep(0)` and emits **one JSON document per line** (parser does `json.loads`).

Host-bound sections:

- `<<<oposs_pbs_server:sep(0)>>>` — one JSON: `{version, node, datastore_count, reachable}`.
- `<<<oposs_pbs_datastore:sep(0)>>>` — one JSON keyed by datastore:
  `{store: {total, used, avail, group_count, backup_count,
  gc: {status, endtime, running, disk_bytes, index_data_bytes}}}`. The two `gc-status`
  byte counters let the check compute the datastore-wide dedup factor.
- `<<<oposs_pbs_jobs:sep(0)>>>` — one JSON: `{sync: [...], verify: [...], prune: [...]}`,
  each job carrying its config fields plus resolved `last_run: {status, endtime}` and
  `running: bool` from the task list.

Piggyback sections (one block per mapped guest host):

```
<<<<{piggyback_host}>>>>
<<<oposs_pbs_backup:sep(0)>>>
{ "datastore": "...", "ns": "...", "backup_type": "...", "backup_id": "...",
  "last_backup": <epoch>, "backup_count": <int>,
  "interval": <seconds|null>, "interval_known": <bool>,
  "verify_state": "ok"|"failed"|"none",
  "data_size": <bytes> }
<<<<>>>>
```

A guest backed up in multiple datastores/namespaces yields multiple JSON lines (one
service per datastore/ns via the check item).

### 5.1 Auto-interval + verification refresh (freshness feature)

Absolute-hour freshness thresholds are wrong for PBS: guests *push* backups on their own
cadence, which PBS does not know as a schedule. So freshness is expressed as **missed
backups** against the group's **observed** interval, and the observed interval is derived
from the group's snapshot timestamps.

Fetching every group's snapshots on every run does not scale and is the load pattern the
inett plugin explicitly avoided. Instead the agent keeps a small **per-host state cache**
on the Checkmk server (`$OMD_ROOT/tmp/check_mk/oposs_pbs/<host>.json`) and fetches a
group's `/snapshots` **only when something could have changed**:

1. the group is **new** (no cache entry), or
2. the group's `last-backup` **advanced** since the cache (new backup → recompute
   interval, refresh verify state), or
3. a **verify job covering that store/namespace finished** since the cache timestamp
   (verify state may have flipped) — derived from the task list we already fetch.

Otherwise the agent reuses the cached `interval` and `verify_state`. The cheap per-run
path (datastore status + per-namespace `groups`) still yields every guest's `last_backup`
every run, so the freshness **age** is always current; only the interval/verify refresh is
gated. Recommended deployment: enable datasource caching (as the inett plugin ran hourly)
to further bound API load.

- **Interval** = median of consecutive gaps among the group's retained snapshot
  `backup-time` values. Needs ≥2 snapshots; with fewer, `interval_known=false` and the
  check falls back to a configurable default interval (default 24 h).
- **verify_state** = newest snapshot's `verification.state` (`ok`/`failed`), or `none`
  when the object is absent (never verified).
- **data_size** = newest snapshot's `size` (bytes) = the **logical size of the protected
  data** for that guest. In PBS a snapshot index references the *full* chunk set of the
  backup (not just the incrementally-uploaded delta), so this is the guest's total
  backed-up data size, useful for capacity/growth trending. It is explicitly **not** a
  deduplicated on-disk footprint — per-guest real disk usage is not available from PBS
  (chunks are shared datastore-wide). Cached and re-emitted every run; refreshes when a
  new backup arrives (i.e. when the value can change).
- **Real on-disk footprint** is a *deferred* item, **not** a settled field. Bugzilla
  #5799 is RFC-stage and its final API is unsettled in two ways: (a) shape — the
  discussion favours a two-number model, *exclusive* (chunks used only by this group) vs
  *shared*, not a single scalar; (b) granularity — currently per-backup-group, with
  per-namespace still an open request. We therefore add **no placeholder field now**. When
  #5799 ships, the agent adds fields mirroring its actual API and the check emits matching
  metrics (e.g. `oposs_pbs_backup_exclusive` / `oposs_pbs_backup_shared`). The section
  format is a plain JSON dict, so adding keys later is non-breaking — that extensibility
  *is* the hook; no guessed field is committed today.
- No check-side value-store learning is needed: the agent owns the interval via its cache.

## 6. Services

On the PBS host:

| Service | Item | State logic | Metrics (`oposs_pbs_*`) |
|---|---|---|---|
| `PBS Server` | — | CRIT if API unreachable; else OK with version/node/datastore count | — |
| `PBS Datastore %s` | datastore | usage `SimpleLevels` (default 80/90 %); GC: OK if last run OK, WARN on GC failure, running noted; UNKNOWN if never run; dedup factor shown | `datastore_size`, `datastore_used`, `datastore_avail`, `datastore_used_pct`, `group_count`, `backup_count`, `gc_age`, `dedup_factor` |
| `PBS Sync Job %s` | `remote:store -> ns` | last-run OK → OK, else CRIT; never-run → OK notice; optional age levels | `sync_age` |
| `PBS Verify Job %s` | `store[/ns]` | as sync | `verify_age` |
| `PBS Prune Job %s` | `store[/ns]:id` | as sync (matched by store+ns) | `prune_age` |

On guest hosts (piggyback):

| Service | Item | State logic | Metrics |
|---|---|---|---|
| `PBS Backup %s` | `datastore[/ns]` | freshness: WARN at `warn_missed × interval` (def 2), CRIT at `crit_missed × interval` (def 3); `<2` snapshots → fallback interval (def 24 h). Verification: `failed`→CRIT, `ok`→OK, `none`→OK notice (param can bump to WARN). Shows age, interval, protected data size, backup count | `backup_age`, `backup_size` (real-footprint metrics deferred to #5799, §5.1) |

GC stays folded into the Datastore service (matches inett and the REST model — GC is a
per-datastore attribute, not a job-list entity).

## 7. Configuration (rulesets)

**Special agent** — `rule_spec_special_agent_oposs_pbs = SpecialAgent(topic=Topic.STORAGE)`:

- API token id (`String`, e.g. `user@realm!tokenname`) — required.
- API token secret (`Password`) — required.
- Port (`Integer`, default 8007).
- TLS: `BooleanChoice` "Verify certificate", **default True**; optional CA-file path /
  fingerprint pin (cascading, best-effort).
- Datastore selection: optional include / exclude (regex list); default all.
- Task fetch limit (`Integer`, default 1000).
- Piggyback host template: `String` with `{id}`, `{type}`, `{comment}` placeholders,
  default `{id}`; plus optional regex rewrite (pattern → replacement).
- Freshness/piggyback: per-datastore opt-out of the piggyback backup service (skips the
  gated `/snapshots` calls for that datastore).

**Check parameters** (`CheckParameters`, `HostAndItemCondition` where item exists):

- Datastore usage levels — `SimpleLevels` (%), default `("fixed", (80.0, 90.0))`.
- GC age levels — optional `SimpleLevels` (seconds).
- Per-job (sync/verify/prune) last-run age levels — optional `SimpleLevels` (seconds).
- Backup freshness (piggyback `PBS Backup`): `warn_missed` (`Integer`, default 2),
  `crit_missed` (`Integer`, default 3), `fallback_interval` seconds (`TimeSpan`, default
  24 h) used when the interval is not yet known, and `unverified_state` (OK/WARN, default
  OK) controlling how a never-verified newest snapshot is graded.

## 8. Naming / entry-point conventions

- Section names & `agent_section_*`: `oposs_pbs_server`, `oposs_pbs_datastore`,
  `oposs_pbs_jobs`, `oposs_pbs_backup`.
- Check plugins: `check_plugin_oposs_pbs_*`; service names as in §6.
- Special agent: `special_agent_oposs_pbs` (server_side_calls), executable
  `libexec/agent_oposs_pbs`, ruleset `name="oposs_pbs"` — all three must match.
- Metrics: all prefixed `oposs_pbs_`, stored in **base SI units** (bytes, seconds).

## 9. Non-goals (YAGNI)

Node OS health (CPU/mem/load), tape jobs, per-snapshot verification, S3 backend stats,
manual (non-scheduled) task monitoring, and metric-history migration from inett.

**Per-guest real (deduplicated) disk footprint** is explicitly out of scope: the only way
to obtain it today is a host-side index-walk (parse a group's `.fidx`/`.didx`, dedupe
chunk digests, sum unique chunk file sizes in `.chunks/` — e.g. `PBS_Chunk_Checker`),
which requires local filesystem access on the PBS host and is minutes-long / I/O-heavy.
That contradicts this plugin's server-side REST architecture. The `checkman` docs will
state this, point users at Bugzilla #5799 for the upcoming native support, and note the
`ondisk_size` forward hook (§5.1) that will light up automatically when PBS ships it.

## 10. Open items to confirm against a live PBS instance

1. Exact JSON field name from `GET /nodes` (schema `returns` is empty); `localhost`
   fallback sidesteps it.
2. Whether `counts` appears in `/admin/datastore/{store}/status` without `verbose=1`.
3. Whether a useful dedup indicator is worth computing from `gc-status` counters later
   (currently out of scope).
4. Special-agent run cadence vs. `/snapshots` refresh load on large datastores — validate
   the state-cache gating and recommend a datasource cache age on a live box (§5.1).
5. `/nodes/{node}/tasks` `typefilter` accepts a single worker_type; confirm whether one
   call with no filter (then filter client-side) or several filtered calls is cheaper
   live.
6. Confirm `gc-status` exposes `index-data-bytes` and `disk-bytes` on a live box and that
   `index-data-bytes / disk-bytes` matches the GUI's dedup factor; guard against
   division-by-zero before the first GC run.

## 12. References

- PBS API schema (authoritative): https://pbs.proxmox.com/docs/api-viewer/apidoc.js
- proxmox-backup source (task worker types, `SnapshotVerifyState`):
  https://github.com/proxmox/proxmox-backup — `pbs-api-types/src/datastore.rs`
- Per-group dedup size (native support, in progress): Bugzilla #5799
  https://bugzilla.proxmox.com/show_bug.cgi?id=5799
- Host-side footprint tools (out of scope, for docs reference):
  `PBS_Chunk_Checker` https://github.com/VoltKraft/PBS_Chunk_Checker ,
  `PBSEstimator` https://github.com/Micinek/PBSEstimator

## 11. Testing / deployment

- `agent_oposs_pbs --test-file <json>` mode for offline parser tests.
- `cmk -d <host>` to inspect raw sections; `cmk -II <host>` to discover; `cmk --debug -v
  <host>` to run checks.
- MKP built via `oposs/mkp-builder@v2` on `v*` tag push.
</content>
</invoke>
