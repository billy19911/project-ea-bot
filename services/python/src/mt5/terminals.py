# -*- coding: utf-8 -*-
"""Multi-terminal MT5 manager (Run 24).

The MetaTrader5 Python binding can only attach to ONE terminal per process
(verified on a real machine: calling ``initialize()`` twice in one process
stays on the first terminal). This module manages a registry of terminals,
auto-detects which terminals are currently running (psutil process scan),
tracks the selected/attached terminal, and gates real order execution
behind an explicit arm switch.

Safety model (accounts may be LIVE):
1. ``"execution": true`` in the config file marks a terminal as *eligible*
   to receive real orders. Every terminal defaults to ``false``.
2. Even when eligible, execution stays OFF until the operator explicitly
   arms the selected terminal (dashboard -> POST /mt5/terminals/arm).
3. Switching the selected terminal always disarms execution.
4. Auto-detected terminals (running but not in the config file) can be
   selected for data, but can never be armed for execution.
"""

from __future__ import annotations

import json
import logging
import ntpath
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "list_terminals",
    "select_terminal",
    "arm_execution",
    "is_execution_armed",
    "execution_permitted",
    "scan_running_terminals",
    "load_config",
    "sync_selection_from_attached",
    "probe_accounts",
]

# Default config location: services/python/mt5_terminals.json
_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "mt5_terminals.json"

# Manager state (module-level, process-wide).
_selected_id: Optional[str] = None
_execution_armed: bool = False

# Account probe cache (F3): normalized folder -> account summary. Filled ONLY by
# ``probe_accounts()``; ``list_terminals()`` reads it to enrich entries without
# touching the binding. Never contains credentials — summary fields only.
_account_cache: dict[str, dict[str, Any]] = {}
_account_cache_ts: Optional[str] = None
# The MetaTrader5 binding is process-wide (one terminal per process), so any
# operation that MOVES it (select, arm, probe) takes this lock — one binding
# operation at a time, and a probe can never interleave with a switch.
_binding_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Config file
# ---------------------------------------------------------------------------


def _config_path() -> Path:
    """Return the active config path (env override wins)."""
    override = os.environ.get("MT5_TERMINALS_CONFIG", "").strip()
    return Path(override) if override else _DEFAULT_CONFIG


def load_config() -> list[dict[str, Any]]:
    """Load the terminal registry from JSON.

    Missing or malformed files degrade to an empty list — the dashboard
    still shows auto-detected running terminals.
    """
    path = _config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("mt5_terminals config unreadable (%s): %s", path, exc)
        return []

    entries = raw.get("terminals") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []

    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tid = str(entry.get("id") or "").strip()
        tpath = str(entry.get("path") or "").strip()
        if not tid or not tpath:
            continue
        result.append(
            {
                "id": tid,
                "label": str(entry.get("label") or tid),
                "path": tpath,
                "execution": bool(entry.get("execution", False)),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Process / attach detection
# ---------------------------------------------------------------------------


def _norm(path: str) -> str:
    """Normalize a path for case-insensitive comparison on Windows.

    Uses ``ntpath`` explicitly: MT5 terminal paths are always Windows paths,
    and on non-Windows CI runners ``os.path`` (posixpath) does not treat
    backslashes as separators — that silently broke folder matching.
    """
    return ntpath.normcase(ntpath.normpath(path))


def scan_running_terminals() -> list[dict[str, Any]]:
    """Return currently running ``terminal64.exe`` processes (best effort)."""
    try:
        import psutil
    except ImportError:
        return []

    found: list[dict[str, Any]] = []
    try:
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                info = proc.info
                name = str(info.get("name") or "").lower()
                exe = str(info.get("exe") or "")
                if name == "terminal64.exe" and exe:
                    found.append(
                        {
                            "pid": info.get("pid"),
                            "exe": exe,
                            "folder": ntpath.dirname(exe),
                        }
                    )
            except Exception:
                # Process vanished or access denied — skip it.
                continue
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("terminal scan failed: %s", exc)
        return []
    return found


def _detect_attached_path() -> Optional[str]:
    """Return the folder of the terminal the binding is attached to."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None
    try:
        info = mt5.terminal_info()
    except Exception:
        return None
    if info is None:
        return None
    path = getattr(info, "path", None)
    return str(path) if path else None


# ---------------------------------------------------------------------------
# Registry view
# ---------------------------------------------------------------------------


def list_terminals() -> dict[str, Any]:
    """Return the terminal registry merged with live process/attach status."""
    config = load_config()
    running = scan_running_terminals()
    running_by_folder = {_norm(r["folder"]): r for r in running}
    attached_folder = _detect_attached_path()
    attached_norm = _norm(attached_folder) if attached_folder else None

    entries: list[dict[str, Any]] = []
    matched_running: set[str] = set()
    for t in config:
        folder = ntpath.dirname(t["path"])
        key = _norm(folder)
        proc = running_by_folder.get(key)
        if proc:
            matched_running.add(key)
        entries.append(
            {
                "id": t["id"],
                "label": t["label"],
                "path": t["path"],
                "folder": folder,
                "execution_allowed": t["execution"],
                "source": "config",
                "running": proc is not None,
                "pid": proc["pid"] if proc else None,
                "attached": bool(attached_norm and attached_norm == key),
                "selected": t["id"] == _selected_id,
                "account": _account_cache.get(key),
            }
        )

    # Running terminals that are not in the config file (data-only).
    for r in running:
        key = _norm(r["folder"])
        if key in matched_running:
            continue
        auto_id = f"auto-{r['pid']}"
        entries.append(
            {
                "id": auto_id,
                "label": ntpath.basename(r["folder"]) or r["exe"],
                "path": r["exe"],
                "folder": r["folder"],
                "execution_allowed": False,
                "source": "auto",
                "running": True,
                "pid": r["pid"],
                "attached": bool(attached_norm and attached_norm == key),
                "selected": auto_id == _selected_id,
                "account": _account_cache.get(key),
            }
        )

    return {
        "terminals": entries,
        "selected_id": _selected_id,
        "execution_armed": _execution_armed,
        "attached_path": attached_folder,
        "accounts_probed_at": _account_cache_ts,
    }


def sync_selection_from_attached() -> Optional[str]:
    """Mark the currently attached terminal as selected (startup helper).

    Called once after the startup attach so the dashboard immediately shows
    which terminal the binding is on, without a manual selection step.
    """
    global _selected_id

    attached = _detect_attached_path()
    if not attached:
        return None
    key = _norm(attached)

    for t in load_config():
        if _norm(ntpath.dirname(t["path"])) == key:
            _selected_id = t["id"]
            return _selected_id

    for r in scan_running_terminals():
        if _norm(r["folder"]) == key:
            _selected_id = f"auto-{r['pid']}"
            return _selected_id
    return None


# ---------------------------------------------------------------------------
# Selected-terminal persistence (so restarts re-attach to the operator's choice)
# ---------------------------------------------------------------------------


def _selection_state_path() -> Path:
    """Path of the tiny file remembering the last selected terminal id."""
    override = os.environ.get("MT5_SELECTION_STATE", "").strip()
    if override:
        return Path(override)
    # Next to the terminals config by default.
    return _config_path().with_name("mt5_selected.json")


def save_selection(terminal_id: str) -> None:
    """Persist the selected terminal id (fail-safe)."""
    try:
        path = _selection_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"selected_id": terminal_id}), encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not persist terminal selection: %s", exc)


def load_saved_selection() -> Optional[str]:
    """Return the persisted selected terminal id, or None."""
    try:
        raw = json.loads(_selection_state_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:  # pragma: no cover - defensive
        return None
    sid = raw.get("selected_id") if isinstance(raw, dict) else None
    return str(sid) if sid else None


def restore_saved_selection() -> Optional[str]:
    """Startup helper: re-attach to the persisted terminal if it is running.

    This fixes the "charts/backtests silently empty after restart" problem:
    without it, the binding attaches to whatever terminal MT5 last used, which
    may be a different broker/symbol set (e.g. suffixed ``XAUUSDc`` vs plain
    ``XAUUSD``). Returns the selected id, or None if it could not be restored.
    """
    saved = load_saved_selection()
    if not saved:
        return None
    with _binding_lock:
        view = list_terminals()
        entry = next((e for e in view["terminals"] if e["id"] == saved), None)
        if entry is None or not entry["running"]:
            return None
        # Already attached to the right terminal — nothing to do.
        if entry["attached"] and _selected_id == saved:
            return saved
        result = _select_terminal_locked(saved)
        return result.get("selected_id") if result.get("ok") else None


# ---------------------------------------------------------------------------
# Account probe (F3) — read-only, restores the binding in a ``finally``
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_account_summary() -> Optional[dict[str, Any]]:
    """Read the CURRENTLY attached account (no binding changes).

    Returns ``None`` when MetaTrader5 is unavailable or ``account_info()``
    has no data — never fabricates values. Contains no credentials.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None
    try:
        info = mt5.account_info()
    except Exception:
        return None
    if info is None:
        return None

    raw_mode = str(getattr(info, "trade_mode", ""))
    # MT5 trade_mode enum: 0=DEMO, 1=CONTEST, 2=REAL. Unknown values map to
    # None so the UI badge can never mislabel an account.
    mode = {"0": "DEMO", "1": "CONTEST", "2": "LIVE"}.get(raw_mode)
    return {
        "login": getattr(info, "login", None),
        "server": getattr(info, "server", None),
        "mode": mode,
        "trade_mode": raw_mode or None,
        "balance": getattr(info, "balance", None),
        "equity": getattr(info, "equity", None),
        "currency": getattr(info, "currency", None),
    }


def probe_accounts() -> dict[str, Any]:
    """Read account info from EVERY running terminal (read-only).

    Safety model:
    - Refuses while execution is armed: the probe moves the process-wide
      binding temporarily and must not run next to live-order permission.
    - Restores the binding to the originally attached terminal in a
      ``finally`` block — a failed probe can never leave the binding parked
      on a terminal the operator did not choose. If the restore itself fails,
      the result says so honestly (``restored: false``) and the selected
      terminal reports ``attached: false`` (fail-closed for orders).
    - Never sends orders, never changes the arm flag, never changes selection.
    """
    global _account_cache, _account_cache_ts

    if _execution_armed:
        return {
            "ok": False,
            "message": (
                "Execution sedang ARMED. Probe memindahkan binding sementara, "
                "jadi harus disarmed dulu — klik Disarm lalu coba lagi."
            ),
            "execution_armed": True,
        }

    with _binding_lock:
        view = list_terminals()
        running = [t for t in view["terminals"] if t.get("running")]
        if not running:
            return {
                "ok": False,
                "message": "Tidak ada terminal yang berjalan — tidak ada yang bisa dicek.",
                "execution_armed": _execution_armed,
            }

        from . import connector

        original_folder = view["attached_path"]
        original_path: Optional[str] = None
        if original_folder:
            key = _norm(original_folder)
            match = next(
                (t for t in view["terminals"] if t.get("folder") and _norm(t["folder"]) == key),
                None,
            )
            if match:
                original_path = match["path"]
        if original_path is None and view["selected_id"]:
            match = next((t for t in view["terminals"] if t["id"] == view["selected_id"]), None)
            if match:
                original_path = match["path"]

        results: list[dict[str, Any]] = []
        fresh: dict[str, dict[str, Any]] = {}
        current_key = _norm(original_folder) if original_folder else None
        try:
            for t in running:
                entry: dict[str, Any] = {
                    "id": t["id"],
                    "label": t.get("label") or t["id"],
                    "ok": False,
                    "account": None,
                    "error": None,
                }
                t_key = _norm(t["folder"]) if t.get("folder") else None
                try:
                    if t_key and current_key == t_key:
                        attached_ok = True  # binding is already here — read directly
                    else:
                        connector.shutdown()
                        attached_ok = connector.use_live_data_mode(path=t["path"])
                        current_key = t_key if attached_ok else None
                    if not attached_ok:
                        entry["error"] = "Gagal attach ke terminal (initialize gagal)."
                    else:
                        summary = _read_account_summary()
                        if summary is None:
                            entry["error"] = "account_info() tidak mengembalikan data."
                        else:
                            entry["ok"] = True
                            entry["account"] = summary
                            if t_key:
                                fresh[t_key] = summary
                except Exception as exc:  # one bad terminal must not abort the probe
                    entry["error"] = str(exc)[:160]
                results.append(entry)
        finally:
            # ALWAYS put the binding back where it was. Failure here is
            # reported, never hidden.
            restored = False
            try:
                connector.shutdown()
                if original_path:
                    restored = connector.use_live_data_mode(path=original_path)
                elif original_folder is None:
                    restored = True  # nothing was attached — detached is correct
                else:
                    # A binding existed but its path is unknown, so we cannot
                    # guarantee where it lands. Fail-closed: report honestly
                    # and let the operator re-select.
                    restored = False
            except Exception:
                restored = False

        _account_cache = fresh
        _account_cache_ts = _utc_now_iso()

        ok_count = sum(1 for r in results if r["ok"])
        message = f"Cek akun selesai: {ok_count}/{len(results)} terminal terbaca."
        if not restored:
            message += (
                " PERINGATAN: binding gagal dipulihkan ke terminal semula — "
                "pilih ulang terminal yang benar sebelum eksekusi."
            )
        return {
            "ok": True,
            "message": message,
            "probed_at": _account_cache_ts,
            "results": results,
            "restored": restored,
            "attached_path": _detect_attached_path(),
            "execution_armed": _execution_armed,
        }


# ---------------------------------------------------------------------------
# Selection / re-attach
# ---------------------------------------------------------------------------


def select_terminal(terminal_id: str) -> dict[str, Any]:
    """Select a terminal as the active data target and re-attach the binding.

    Switching terminals ALWAYS disarms execution (safety: an arm state must
    never silently carry over to a different terminal).
    """
    with _binding_lock:
        return _select_terminal_locked(terminal_id)


def _select_terminal_locked(terminal_id: str) -> dict[str, Any]:
    """Body of ``select_terminal`` — caller holds ``_binding_lock``."""
    global _selected_id, _execution_armed

    view = list_terminals()
    entry = next((e for e in view["terminals"] if e["id"] == terminal_id), None)
    if entry is None:
        return {
            "ok": False,
            "message": f"Terminal '{terminal_id}' not found in the registry.",
            "selected_id": _selected_id,
            "execution_armed": _execution_armed,
        }
    if not entry["running"]:
        return {
            "ok": False,
            "message": (
                f"Terminal '{terminal_id}' is not running. "
                "Start its terminal64.exe first, then re-select."
            ),
            "selected_id": _selected_id,
            "execution_armed": _execution_armed,
        }

    if entry["attached"] and _selected_id == terminal_id:
        return {
            "ok": True,
            "message": f"Terminal '{terminal_id}' is already selected and attached.",
            "selected_id": _selected_id,
            "execution_armed": _execution_armed,
            "attached_path": view["attached_path"],
        }

    # Re-attach: shutdown + initialize(path=exe). Verified working at runtime.
    from . import connector

    # Safety: disarm BEFORE touching the binding — a switch (even a failed one)
    # must never leave execution armed while the binding is ambiguous.
    _execution_armed = False

    connector.shutdown()
    ok = connector.use_live_data_mode(path=entry["path"])
    if not ok:
        return {
            "ok": False,
            "message": (
                f"Failed to attach to '{terminal_id}' at {entry['path']}. "
                "The binding is now detached — re-select a running terminal."
            ),
            "selected_id": _selected_id,
            "execution_armed": False,
            "attached_path": _detect_attached_path(),
        }

    _selected_id = terminal_id
    _execution_armed = False  # never inherit an arm state across terminals
    save_selection(terminal_id)
    # Symbols differ per broker (XAUUSD vs XAUUSDc) — drop the resolution cache.
    try:
        from .symbol_resolver import clear_symbol_cache

        clear_symbol_cache()
    except Exception:  # noqa: BLE001
        pass
    attached = _detect_attached_path()
    return {
        "ok": True,
        "message": (
            f"Terminal '{terminal_id}' selected. "
            f"Attached to: {attached or 'unknown'}. Execution disarmed."
        ),
        "selected_id": _selected_id,
        "execution_armed": False,
        "attached_path": attached,
    }


# ---------------------------------------------------------------------------
# Execution arm switch
# ---------------------------------------------------------------------------


def is_execution_armed() -> bool:
    """Return the raw arm flag (does not validate terminal state)."""
    return _execution_armed


def arm_execution(armed: bool) -> dict[str, Any]:
    """Arm/disarm real order execution for the SELECTED terminal.

    Arming requires ALL of:
    - a terminal is selected and currently running,
    - it is marked ``"execution": true`` in the config file,
    - the binding is attached to it (live mode).
    """
    global _execution_armed

    if not armed:
        was = _execution_armed
        _execution_armed = False
        return {
            "ok": True,
            "armed": False,
            "message": "Execution disarmed." if was else "Execution already disarmed.",
        }

    view = list_terminals()
    entry = next((e for e in view["terminals"] if e["id"] == _selected_id), None)
    if entry is None:
        return {
            "ok": False,
            "armed": _execution_armed,
            "message": "No terminal selected. Select a running terminal first.",
        }
    if not entry["running"]:
        return {
            "ok": False,
            "armed": _execution_armed,
            "message": "The selected terminal is not running.",
        }
    if not entry["execution_allowed"]:
        return {
            "ok": False,
            "armed": _execution_armed,
            "message": (
                f"Terminal '{entry['id']}' is not execution-enabled. Set "
                '"execution": true for it in mt5_terminals.json, then arm again '
                "(the config is re-read on every request — no restart needed)."
            ),
        }
    if not entry["attached"]:
        return {
            "ok": False,
            "armed": _execution_armed,
            "message": "The binding is not attached to the selected terminal. Re-select it.",
        }

    _execution_armed = True
    return {
        "ok": True,
        "armed": True,
        "message": (
            f"Execution ARMED for terminal '{entry['id']}'. "
            "Real orders may now be sent. Disarm when done."
        ),
    }


def execution_permitted() -> bool:
    """True only when the operator explicitly armed a valid terminal.

    This is the final gate consulted by the execution engine before any
    native ``mt5.order_send`` call. Fail-closed: any doubt → False.
    """
    if not _execution_armed or not _selected_id:
        return False
    view = list_terminals()
    entry = next((e for e in view["terminals"] if e["id"] == _selected_id), None)
    if entry is None:
        return False
    return bool(entry["execution_allowed"] and entry["running"] and entry["attached"])
