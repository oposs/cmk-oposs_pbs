# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### New

### Changed

### Fixed

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


