"""Audit log: one JSON line per event. Thread-safe, and every record is redacted before it is written."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .redaction import redact_data


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, event: str, **data) -> None:
        line = json.dumps(_record(event, data), ensure_ascii=False, default=str)
        with self._lock, self.path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")


def _record(event: str, data: dict) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    present = {key: value for key, value in data.items() if value is not None}
    return {"ts": timestamp, "event": event, **redact_data(present)}
