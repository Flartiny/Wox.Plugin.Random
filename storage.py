"""Persistent store of already-generated values (for the no-repeat feature).

Data lives in ``<plugin dir>/data/used_values.json`` so it survives Wox
restarts and plugin reloads. Entries are kept per profile key, newest last.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

MAX_ENTRIES_PER_KEY = 5000


class UsedStore:
    def __init__(self, file_path: str):
        self._path = file_path
        self._lock = threading.Lock()
        self._data: dict[str, list[dict]] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._data = {
                    str(key): [e for e in entries if isinstance(e, dict) and "v" in e]
                    for key, entries in raw.items()
                    if isinstance(entries, list)
                }
        except (OSError, ValueError):
            self._data = {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)
        os.replace(tmp, self._path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def used_values(self, key: str) -> frozenset[str]:
        with self._lock:
            return frozenset(entry["v"] for entry in self._data.get(key, []))

    def record(self, key: str, value: str) -> None:
        with self._lock:
            entries = self._data.setdefault(key, [])
            if any(entry["v"] == value for entry in entries):
                return
            entries.append({"v": value, "t": self._now()})
            if len(entries) > MAX_ENTRIES_PER_KEY:
                del entries[: len(entries) - MAX_ENTRIES_PER_KEY]
            self._save()

    def entries(self, key: str) -> list[dict]:
        """All entries for the key, newest first."""
        with self._lock:
            return list(reversed(self._data.get(key, [])))

    def count(self, key: str) -> int:
        with self._lock:
            return len(self._data.get(key, []))

    def clear(self, key: str) -> None:
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._save()
