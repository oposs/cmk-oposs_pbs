# Proxmox Backup Server Monitoring Plugin

This Checkmk plugin monitors Proxmox Backup Server (PBS) via its REST API, providing comprehensive monitoring of datastores, backup jobs, and per-guest backup freshness through piggyback integration. To use this plugin, you need an **Audit**-role API token configured on your PBS instance. For detailed design information and implementation notes, see the [design specification](docs/superpowers/specs/2026-07-07-oposs-pbs-special-agent-design.md).

## Development

For contributor setup, create a symlink from your Checkmk's `local/lib/check_mk` directory to this repository's `local/lib/check_mk` directory to enable live testing of changes.
