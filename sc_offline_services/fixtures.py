"""JSON fixtures: what the emulator answers locally.

Schema (see fixtures/offline_services.json):
  config:          {"group/key": null | "<string>" | {"value": <str|object>, "version": n, "disabled": bool}}
  instances:       [Instance in proto-JSON; "shard_id": "*" echoes the requested shard]
  push_on_listen:  [{"type": "<message name>", "message": {proto-JSON}}]
Keys beginning with "_" are notes and are stripped everywhere.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("scos.fixtures")


def strip_notes(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_notes(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip_notes(v) for v in obj]
    return obj


class Fixtures:
    def __init__(self, path: str | Path | None = None, data: dict | None = None):
        self.path = Path(path) if path else None
        self.cond = threading.Condition()
        self.generation = 0
        self.data: dict = strip_notes(data or {})
        if self.path:
            self.reload()

    def reload(self) -> int:
        if self.path:
            # utf-8-sig: a BOM from Windows PowerShell must not break the file (rig trap).
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            data = strip_notes(raw)
        else:
            data = self.data
        with self.cond:
            self.data = data
            self.generation += 1
            self.cond.notify_all()
        log.info("fixtures loaded (generation %d): %d config keys, %d instances, %d push_on_listen",
                 self.generation, len(self.data.get("config", {})), len(self.instances()),
                 len(self.push_on_listen()))
        return self.generation

    def replace(self, data: dict) -> int:
        """Swap the fixture data in-process (tests, admin)."""
        with self.cond:
            self.data = strip_notes(data)
            self.generation += 1
            self.cond.notify_all()
        return self.generation

    # ---- config --------------------------------------------------------------------------

    def config_lookup(self, group: str, key: str) -> tuple[str, int] | None:
        """Return (value, version) or None for NOT_FOUND."""
        entries = self.data.get("config") or {}
        entry = entries.get(f"{group}/{key}")
        if entry is None:
            return None
        if isinstance(entry, str):
            return entry, 1
        if isinstance(entry, dict):
            if entry.get("disabled"):
                return None
            if "value" not in entry:
                return None
            value = entry["value"]
            version = int(entry.get("version", 1))
        else:
            value, version = entry, 1
        if not isinstance(value, str):
            value = json.dumps(value, separators=(",", ":"))
        return value, version

    def config_keys(self) -> list[str]:
        return sorted((self.data.get("config") or {}).keys())

    # ---- instances / push ----------------------------------------------------------------

    def instances(self) -> list[dict]:
        return list(self.data.get("instances") or [])

    def push_on_listen(self) -> list[dict]:
        return list(self.data.get("push_on_listen") or [])
