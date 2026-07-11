# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### New

### Changed

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
