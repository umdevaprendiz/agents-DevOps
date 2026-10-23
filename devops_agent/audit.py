"""Log de auditoria: uma linha JSON por evento (tarefa, ferramenta, aprovação, resposta)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **data) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
