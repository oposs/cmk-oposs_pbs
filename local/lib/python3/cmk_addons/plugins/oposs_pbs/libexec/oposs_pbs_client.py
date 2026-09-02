"""Thin Proxmox Backup Server REST client (API-token auth)."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import os
import requests


def resolve_password_ref(value: str, *, _lookup=None) -> str:
    """Resolve a Checkmk password-store reference of the form ``<id>:<file>``
    to the real secret.

    Server-side calls pass a bare ``Secret`` as ``<pw_id>:<pw_store_file>``.
    ``password_store.replace_passwords()`` does NOT rewrite this inline form, so
    the agent must resolve it explicitly via ``password_store.lookup()``.

    Anything that is not a live reference (no ``:``, or the file part does not
    exist) is returned unchanged, so an inline/test secret still works.
    """
    if ":" not in value:
        return value
    pw_id, pw_file = value.split(":", 1)
    if not pw_file or not os.path.exists(pw_file):
        return value
    lookup = _lookup
    if lookup is None:
        try:
            from cmk.utils.password_store import lookup
        except ImportError:
            return value
    return lookup(Path(pw_file), pw_id)


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

    def get(self, path: str, params: dict | None = None,
            timeout: float | None = None) -> Any:
        """GET an API path. `timeout` overrides the client default for this one
        call, so a caller working against a deadline cannot be outlived by its
        own request."""
        url = self._base + path
        try:
            resp = self._session.get(
                url, params=params, verify=self._verify,
                timeout=self._timeout if timeout is None else timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise PbsError(f"GET {path} failed: {exc}") from exc
        try:
            return resp.json().get("data")
        except ValueError as exc:
            raise PbsError(f"GET {path}: invalid JSON") from exc
