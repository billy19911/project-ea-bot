# -*- coding: utf-8 -*-
"""Tests for MT5 selected-terminal persistence (restart re-attach)."""

from __future__ import annotations

import json

from src import main
from src.mt5 import terminals


def test_save_and_load_selection(tmp_path, monkeypatch) -> None:
    state = tmp_path / "mt5_selected.json"
    monkeypatch.setenv("MT5_SELECTION_STATE", str(state))
    terminals.save_selection("bil2")
    assert state.exists()
    assert terminals.load_saved_selection() == "bil2"


def test_load_missing_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MT5_SELECTION_STATE", str(tmp_path / "nope.json"))
    assert terminals.load_saved_selection() is None


def test_load_corrupt_returns_none(tmp_path, monkeypatch) -> None:
    state = tmp_path / "bad.json"
    state.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("MT5_SELECTION_STATE", str(state))
    assert terminals.load_saved_selection() is None


def test_restore_no_saved_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MT5_SELECTION_STATE", str(tmp_path / "none.json"))
    assert terminals.restore_saved_selection() is None


def test_restore_unknown_terminal_returns_none(tmp_path, monkeypatch) -> None:
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"selected_id": "does-not-exist"}), encoding="utf-8")
    monkeypatch.setenv("MT5_SELECTION_STATE", str(state))
    monkeypatch.setattr(terminals, "list_terminals", lambda: {"terminals": []})
    assert terminals.restore_saved_selection() is None


def test_restore_when_already_attached(tmp_path, monkeypatch) -> None:
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"selected_id": "bil2"}), encoding="utf-8")
    monkeypatch.setenv("MT5_SELECTION_STATE", str(state))
    monkeypatch.setattr(
        terminals,
        "list_terminals",
        lambda: {
            "terminals": [
                {"id": "bil2", "running": True, "attached": True},
            ]
        },
    )
    monkeypatch.setattr(terminals, "_selected_id", "bil2")
    assert terminals.restore_saved_selection() == "bil2"


def test_restore_selects_when_running(tmp_path, monkeypatch) -> None:
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"selected_id": "bil2"}), encoding="utf-8")
    monkeypatch.setenv("MT5_SELECTION_STATE", str(state))
    monkeypatch.setattr(
        terminals,
        "list_terminals",
        lambda: {
            "terminals": [
                {"id": "bil2", "running": True, "attached": False},
            ]
        },
    )
    monkeypatch.setattr(terminals, "_selected_id", None)
    monkeypatch.setattr(
        terminals,
        "_select_terminal_locked",
        lambda tid: {"ok": True, "selected_id": tid},
    )
    assert terminals.restore_saved_selection() == "bil2"


def test_startup_uses_saved_terminal_without_generic_attach(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(terminals, "load_saved_selection", lambda: "bil2")
    monkeypatch.setattr(terminals, "restore_saved_selection", lambda: "bil2")
    monkeypatch.setattr(
        main.connector,
        "use_live_data_mode",
        lambda path=None: calls.append(("attach", path)) or True,
    )
    monkeypatch.setattr(
        terminals,
        "sync_selection_from_attached",
        lambda: calls.append(("sync", None)),
    )

    assert main._start_mt5_data_binding() is True
    assert calls == [("sync", None)]


def test_startup_does_not_fallback_when_saved_terminal_cannot_attach(monkeypatch) -> None:
    calls = []
    shutdown_calls = []
    monkeypatch.setattr(terminals, "load_saved_selection", lambda: "bil2")
    monkeypatch.setattr(terminals, "restore_saved_selection", lambda: None)
    monkeypatch.setattr(main.connector, "shutdown", lambda: shutdown_calls.append(True))
    monkeypatch.setattr(
        main.connector,
        "use_live_data_mode",
        lambda path=None: calls.append(("attach", path)) or True,
    )
    monkeypatch.setattr(
        terminals,
        "sync_selection_from_attached",
        lambda: calls.append(("sync", None)),
    )

    assert main._start_mt5_data_binding() is False
    assert calls == []
    assert shutdown_calls == [True]
