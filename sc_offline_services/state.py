"""Counters and an in-memory log ring, both read by the admin endpoint."""
from __future__ import annotations

import collections
import logging
import threading
import time


class Stats:
    def __init__(self, recent: int = 200):
        self._lock = threading.Lock()
        self.started = time.time()
        self.counters: dict[str, int] = collections.defaultdict(int)
        self.recent: collections.deque = collections.deque(maxlen=recent)

    def inc(self, key: str, n: int = 1) -> None:
        with self._lock:
            self.counters[key] += n

    def record(self, method: str, kind: str, outcome: str, ms: float | None = None) -> None:
        with self._lock:
            self.counters[f"rpc.{kind}"] += 1
            self.recent.append({"t": time.time(), "method": method, "kind": kind, "outcome": outcome,
                                "ms": None if ms is None else round(ms, 1)})

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "uptime_s": round(time.time() - self.started, 1),
                "counters": dict(self.counters),
                "recent": list(self.recent),
            }


class RingLogHandler(logging.Handler):
    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.lines: collections.deque = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:  # never let logging take the server down
            pass

    def tail(self, n: int) -> list[str]:
        return list(self.lines)[-n:]
