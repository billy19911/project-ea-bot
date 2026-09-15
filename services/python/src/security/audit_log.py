# -*- coding: utf-8 -*-
"""Tamper-evident audit log — EPIC 17.07.

Append-only audit log protected by a SHA-256 hash chain: each entry
commits to the previous entry's hash, so any modification, reorder or
deletion is detectable via :meth:`ProtectedAuditLog.verify`.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


class AuditIntegrityError(RuntimeError):
    """Raised when the audit chain fails verification."""

    def __init__(self, broken_at: int) -> None:
        super().__init__(f"Audit chain integrity broken at entry index {broken_at}")
        self.broken_at = broken_at


@dataclass
class AuditEntry:
    """A single immutable-intent audit entry in the hash chain."""

    index: int
    timestamp: str
    actor: str
    action: str
    target: str
    details: Dict[str, Any] = field(default_factory=dict)
    prev_hash: str = ""
    hash: str = ""

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "index": self.index,
                "timestamp": self.timestamp,
                "actor": self.actor,
                "action": self.action,
                "target": self.target,
                "details": self.details,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProtectedAuditLog:
    """Append-only audit log with tamper-evident hash chaining."""

    GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    @property
    def genesis_hash(self) -> str:
        return self.GENESIS_HASH

    def append(
        self,
        actor: str,
        action: str,
        target: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        prev_hash = self._entries[-1].hash if self._entries else self.GENESIS_HASH
        entry = AuditEntry(
            index=len(self._entries),
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            action=action,
            target=target,
            details=details or {},
            prev_hash=prev_hash,
        )
        entry.hash = entry.compute_hash()
        self._entries.append(entry)
        return entry

    def verify(self) -> Tuple[bool, Optional[int]]:
        """Verify the full chain. Returns ``(ok, broken_index)``."""
        prev_hash = self.GENESIS_HASH
        for i, entry in enumerate(self._entries):
            if entry.index != i or entry.prev_hash != prev_hash:
                return False, i
            if entry.compute_hash() != entry.hash:
                return False, i
            prev_hash = entry.hash
        return True, None

    def verify_or_raise(self) -> None:
        ok, broken_at = self.verify()
        if not ok:
            raise AuditIntegrityError(broken_at if broken_at is not None else -1)

    def entries(self) -> List[Dict[str, Any]]:
        return [
            {
                "index": e.index,
                "timestamp": e.timestamp,
                "actor": e.actor,
                "action": e.action,
                "target": e.target,
                "details": e.details,
                "prev_hash": e.prev_hash,
                "hash": e.hash,
            }
            for e in self._entries
        ]

    def __len__(self) -> int:
        return len(self._entries)

    @classmethod
    def from_entries(cls, exported: List[Dict[str, Any]]) -> "ProtectedAuditLog":
        log = cls()
        for record in exported:
            entry = AuditEntry(
                index=record["index"],
                timestamp=record["timestamp"],
                actor=record["actor"],
                action=record["action"],
                target=record["target"],
                details=record.get("details", {}),
                prev_hash=record["prev_hash"],
                hash=record["hash"],
            )
            log._entries.append(entry)
        return log
