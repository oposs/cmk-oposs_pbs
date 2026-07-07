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
