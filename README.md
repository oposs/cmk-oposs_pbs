# Proxmox Backup Server Monitoring Plugin

This Checkmk plugin monitors Proxmox Backup Server (PBS) via its REST API, providing comprehensive monitoring of datastores, backup jobs, and per-guest backup freshness through piggyback integration. To use this plugin, you need an **Audit**-role API token configured on your PBS instance. For detailed design information and implementation notes, see the [design specification](docs/superpowers/specs/2026-07-07-oposs-pbs-special-agent-design.md).

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

## Development

For contributor setup, create a symlink from your Checkmk's `local/lib/check_mk` directory to this repository's `local/lib/check_mk` directory to enable live testing of changes.
