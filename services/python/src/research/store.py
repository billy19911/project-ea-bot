from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _default_path() -> Path:
    """Store path: RESEARCH_STATE_PATH env, else next to runtime_settings.json."""
    env = os.environ.get("RESEARCH_STATE_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "research_state.jsonl"


class ResearchStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_path()
        self.persisted = True
        self.records: list[dict[str, Any]] = []
        try:
            if self.path.exists():
                with self.path.open(encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            record = json.loads(line)
                            if isinstance(record, dict) and isinstance(record.get("type"), str):
                                self.records.append(record)
                        except (json.JSONDecodeError, OSError):
                            continue
        except OSError:
            self.persisted = False

    def append(self, record_type: str, data: dict[str, Any]) -> None:
        if not self.persisted:
            return
        record = {"type": record_type, "data": data}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=str) + "\n")
            self.records.append(record)
        except (OSError, TypeError, ValueError):
            self.persisted = False

    def replay(self) -> list[dict[str, Any]]:
        return list(self.records)
