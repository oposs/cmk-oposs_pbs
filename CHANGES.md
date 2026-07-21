# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### New

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
  per-item `PBS backup freshness (piggyback)` rules to the new item names.

### Fixed

## 0.4.0 - 2026-07-14
### New
- **PBS Backups roll-up service.** A single `PBS Backups` service on the PBS host
  summarizes the health of *every* backup group (vm/ct/host). It goes WARN/CRIT
  if any backup is stale (missed cadence) or its newest snapshot failed
  verification, and lists exactly which ones in the service details (guest host,
  datastore/namespace, backup, reason) so you can see what went bad without
  visiting each piggyback host. Metrics `oposs_pbs_backups_total` and
  `oposs_pbs_backups_unhealthy` are emitted. Thresholds are configurable via the
  new *PBS backups roll-up* check ruleset (same knobs as the per-guest backup
  check). Additive: the per-guest `PBS Backup` services are unchanged.

## 0.3.0 - 2026-07-14
### New
- **Guest-name piggyback mapping.** The PBS Backup piggyback host now defaults to
  the PVE guest name (read from each backup's snapshot comment) instead of the
  numeric VMID. This is the same host name the built-in Checkmk Proxmox VE agent
  piggybacks under (`vm["name"]`), so the PBS Backup service attaches to the
  *same* Checkmk host as the VM's Proxmox VE data, honouring any piggyback
  hostname-translation rule identically. A new `{guest}` placeholder is available
  for custom templates and is the new default; it falls back to the backup-id
  when a backup has no guest name (e.g. `host/` backups, whose id already is the
  hostname).
- The **PBS Server** service now reports vm/ct backups that have no guest name
  (and therefore land on their VMID) with a configurable state (new *PBS server*
  check ruleset, default WARN), so the gap can be fixed at the PVE backup
  `notes-template` (set it to `{{guestname}}`).
- PBS Backup piggyback hosts now get discovered host labels `oposs_pbs/backup:yes`
  and `oposs_pbs/datastore:<datastore>` for filtering and alerting on "has a PBS
  backup".

### Changed
- The default piggyback host template changed from `{id}` to `{guest}` (see
  above). **Migration:** existing piggyback services under numeric VMIDs go stale
  after the upgrade and can be deleted; the same backup data reappears under the
  guest hostname. An existing state cache refreshes each group once (bounded by
  the refresh budget) to learn the guest name.

## 0.2.2 - 2026-07-13
### Fixed
- The agent no longer probes the PBS `/nodes` index. That endpoint requires more
  than the `Audit` privilege a least-privilege monitoring token holds, so every
  run logged a `403 ... permission check failed` on the PBS host. The local node
  is always reachable via the `localhost` alias (`/nodes/localhost/tasks` etc.),
  which we now use directly — collection was already unaffected (it fell back to
  `localhost`), but the recurring server-side 403 log entry is now gone.

## 0.2.1 - 2026-07-12
### Fixed
- The API-token secret is now resolved correctly when passed from the GUI via the
  Checkmk password store. `replace_passwords()` does not rewrite the inline
  `<id>:<file>` reference produced for a bare `Secret`, so the agent was sending
  the raw reference as the secret and every request failed with `401
  Unauthorized`; the reference is now resolved explicitly via
  `password_store.lookup()`.

## 0.2.0 - 2026-07-10
### Changed
- The special agent now **degrades gracefully** instead of aborting: a slow or
  failing datastore, task-list, job-config, or per-group `/snapshots` call is
  logged to stderr and skipped, and the remaining sections are still emitted.
  A group whose snapshot refresh fails reuses its last cached value (or a neutral
  placeholder) rather than crashing the whole run.
- Expensive `/snapshots` refreshes are now bounded by a per-run **refresh budget**
  (`--refresh-budget`, default 120 s). Once exceeded, remaining groups report their
  cached values and are refreshed on a later run, so a large datastore on slow
  (e.g. USB) storage warms up gradually without exceeding the datasource timeout.
- The state cache is now **persisted incrementally** (throttled during collection,
  after each datastore, and on `SIGTERM`/`SIGINT`), so a run killed mid-collect
  keeps its forward progress instead of restarting cold.
- Backup **cadence** is now also derived from `last-backup` timestamps observed
  across runs, so a group reports a usable interval even before a full `/snapshots`
  enumeration succeeds.
- New `--timeout` option (default 60 s, was a fixed 30 s) for the per-request HTTP
  read timeout; both it and the refresh budget are exposed in the agent ruleset.

### Fixed
- A single slow backup group no longer produces a traceback and zero output; this
  previously broke all monitoring for a PBS host whose datastore held large backup
  groups on slow storage.

## 0.1.0 - 2026-07-09
### New
- Initial release. Server-side **special agent** monitoring Proxmox Backup Server
  (PBS) via its REST API with an API token — no software installed on the PBS host.
- **PBS Server** service: API reachability, version and node.
- **PBS Datastore** service (per datastore): usage levels, backup/group counts,
  garbage-collection state, and the datastore-wide deduplication factor
  (`index-data-bytes / disk-bytes` from `gc-status`).
- **PBS Sync Job / Verify Job / Prune Job** services: last scheduled-run state with
  optional age levels.
- **PBS Backup** service (piggyback, on each backed-up guest's host): backup
  freshness expressed as "missed backups" against the observed snapshot interval,
  newest-snapshot verification state, and the logical protected-data size. The
  observed interval is learned from snapshot history; per-group `/snapshots` calls
  are gated by a per-host state cache to keep API load low.
- Configurable piggyback host mapping (`{id}` / `{type}` / `{comment}` template plus
  optional regex rewrite), datastore include/exclude, and TLS verification
  (default on, optional CA file).
- Rulesets for the special agent and for datastore-usage, job-age, and
  backup-freshness check parameters.
