# -*- coding: utf-8 -*-
"""Runtime settings store (UI/UX ide #7).

Stores the small set of operator-tunable knobs that are **actually consumed**
by the running system. Anything not wired to real behaviour is deliberately
NOT stored here — the dashboard must not present editable fields that do
nothing (that is the "settings theatre" anti-pattern this project bans).

Wired knobs
-----------
* ``supervisor_token_budget`` — :class:`agents.supervisor.SupervisorAgent`
  refuses to start an agent once the committed estimate would exceed this
  budget (``check_token_budget``). Lowering it is strictly *more* restrictive.
* ``scheduler_poll_interval`` — seconds between scheduler polls
  (``orchestration.scheduler``). Must stay >= 0.1s so the loop cannot spin.

Deliberately NOT here
---------------------
* Risk limits (max daily loss, drawdown, exposure) live in ``RiskGate`` and
  are safety logic. The dashboard shows them **read-only** with the real
  values the gate is constructed with; they are never edited from the UI.
* Kill switch state is safety state owned by ``risk.kill_switch``. Not exposed
  as a form field.

Persistence: a single JSON file next to the Python service (``runtime_settings.json``),
written atomically (tmp + replace). Missing/corrupt file degrades to defaults.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["RuntimeSettings", "RuntimeSettingsStore", "get_settings_store"]


@dataclass(frozen=True)
class Knob:
    """A single tunable knob with its bounds and description."""

    key: str
    kind: str  # "int" | "float"
    minimum: float
    maximum: float
    default: float
    description: str
    applied_to: str

    def coerce(self, raw: Any) -> float:
        """Validate and coerce ``raw``; raises ``ValueError`` when invalid."""
        if isinstance(raw, bool):
            raise ValueError(f"{self.key}: nilai boolean tidak valid")
        if self.kind == "int":
            if isinstance(raw, float) and not raw.is_integer():
                raise ValueError(f"{self.key}: harus bilangan bulat")
            try:
                value = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{self.key}: bukan bilangan bulat") from exc
        else:
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{self.key}: bukan angka") from exc
        if value != value:  # NaN
            raise ValueError(f"{self.key}: bukan angka")
        if value < self.minimum or value > self.maximum:
            raise ValueError(f"{self.key}: di luar rentang {self.minimum}–{self.maximum}")
        return value


# The allowlist. Adding a knob here REQUIRES wiring it to real behaviour —
# see the module docstring.
KNOBS: tuple[Knob, ...] = (
    Knob(
        key="supervisor_token_budget",
        kind="int",
        minimum=1000,
        maximum=2_000_000,
        default=8000,
        description="Batas token per siklus supervisor (agent dilewati bila terlampaui).",
        applied_to="SupervisorAgent.token_budget",
    ),
    Knob(
        key="scheduler_poll_interval",
        kind="float",
        minimum=0.1,
        maximum=60.0,
        default=1.0,
        description="Jeda antar-poll scheduler (detik).",
        applied_to="Scheduler.poll_interval",
    ),
)

_BY_KEY = {k.key: k for k in KNOBS}


@dataclass
class RuntimeSettings:
    """Validated runtime settings snapshot."""

    values: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)


class RuntimeSettingsStore:
    """Thread-safe JSON-backed store for :data:`KNOBS`.

    Only allowlisted keys are accepted. Values are validated on the way in and
    on the way out, so a hand-edited file cannot inject junk into the runtime.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        if path is None:
            base = os.path.dirname(os.path.abspath(__file__))
            path = os.path.normpath(os.path.join(base, "..", "..", "runtime_settings.json"))
        self._path = path
        self._values: dict[str, float] = {k.key: k.default for k in KNOBS}
        self._loaded = False

    # -- persistence -------------------------------------------------------

    def load(self) -> None:
        """Load from disk; invalid entries fall back to defaults (never raise)."""
        with self._lock:
            self._loaded = True
            if not os.path.exists(self._path):
                return
            try:
                with open(self._path, encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (OSError, ValueError) as exc:
                logger.warning("runtime_settings: file tidak terbaca (%s) — pakai default", exc)
                return
            if not isinstance(raw, dict):
                return
            for key, value in raw.items():
                knob = _BY_KEY.get(key)
                if knob is None:
                    continue
                try:
                    self._values[key] = knob.coerce(value)
                except ValueError as exc:
                    logger.warning("runtime_settings: abaikan %s", exc)

    def _write_locked(self) -> None:
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._values, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("runtime_settings: gagal menulis (%s)", exc)

    # -- read --------------------------------------------------------------

    def snapshot(self) -> RuntimeSettings:
        """Return current values (loads from disk on first call)."""
        if not self._loaded:
            self.load()
        with self._lock:
            return RuntimeSettings(values=dict(self._values))

    def describe(self) -> list[dict[str, Any]]:
        """Describe every knob: current value, bounds, what it is wired to."""
        current = self.snapshot().values
        return [
            {
                "key": k.key,
                "value": current.get(k.key, k.default),
                "minimum": k.minimum,
                "maximum": k.maximum,
                "default": k.default,
                "description": k.description,
                "applied_to": k.applied_to,
            }
            for k in KNOBS
        ]

    # -- write -------------------------------------------------------------

    def update(self, patch: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
        """Validate and persist ``patch``.

        Returns ``(applied_values, errors)``. Unknown keys are rejected rather
        than silently ignored, so a typo in the UI is visible immediately.
        """
        if not isinstance(patch, dict):
            return {}, ["body harus objek JSON"]
        errors: list[str] = []
        staged: dict[str, float] = {}
        for key, raw in patch.items():
            knob = _BY_KEY.get(key)
            if knob is None:
                errors.append(f"'{key}' bukan setting yang dapat diubah")
                continue
            try:
                staged[key] = knob.coerce(raw)
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            return {}, errors
        if not staged:
            return {}, ["tidak ada perubahan"]
        if not self._loaded:
            self.load()
        with self._lock:
            self._values.update(staged)
            self._write_locked()
            applied = {k: self._values[k] for k in staged}
        return applied, []


_STORE: Optional[RuntimeSettingsStore] = None
_STORE_LOCK = threading.Lock()


def get_settings_store() -> RuntimeSettingsStore:
    """Return the process-wide settings store (singleton)."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = RuntimeSettingsStore()
        return _STORE
