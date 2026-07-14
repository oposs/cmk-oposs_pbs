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
        if "guest" not in entry:
            return True  # pre-guest-mapping cache: refresh once to learn the name
        if entry.get("last_backup") != last_backup:
            return True
        if entry.get("verify_checked_at", 0) < verify_activity:
            return True
        return False
