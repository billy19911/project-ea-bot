# -*- coding: utf-8 -*-
"""Auto-detect MT5 accounts without clicking "Cek akun".

Rules proven here:

* ``list_terminals()`` auto-reads the ATTACHED terminal's account for free
  (no re-bind, no arm change) so the dashboard shows identity immediately.
* While NO terminal is armed, ``list_terminals()`` also triggers a best-effort
  full probe of running terminals (so BIL2/VITO2 fill in by themselves).
* While ANY terminal is armed, the full probe is SKIPPED (fail-closed: the
  probe moves the process-wide binding and must not run next to live orders).
* Auto-detection never recurses infinitely and never raises.
"""

from __future__ import annotations

import importlib

import pytest

terminals = importlib.import_module("mt5.terminals")

CONFIG = {
    "terminals": [
        {"id": "bil2", "label": "BIL 2", "path": r"C:\mt\BIL2\terminal64.exe"},
        {"id": "vito2", "label": "VITO 2", "path": r"C:\mt\VITO2\terminal64.exe"},
    ]
}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    cfg = tmp_path / "mt5_terminals.json"
    cfg.write_text(__import__("json").dumps(CONFIG), encoding="utf-8")
    monkeypatch.setenv("MT5_TERMINALS_CONFIG", str(cfg))
    terminals._selected_id = None
    terminals._execution_armed = False
    terminals._terminal_states = {}
    terminals._mirror_selected = None
    terminals._mirror_armed = False
    terminals._account_cache = {}
    terminals._account_cache_ts = None
    terminals._auto_probe_running = False
    yield
    terminals._execution_armed = False
    terminals._terminal_states = {}
    terminals._account_cache = {}
    terminals._auto_probe_running = False


def _running(*folders):
    return lambda: [
        {"pid": 10 + i, "exe": f"{f}\\terminal64.exe", "folder": f} for i, f in enumerate(folders)
    ]


def test_attached_account_is_auto_read(monkeypatch) -> None:
    monkeypatch.setattr(terminals, "scan_running_terminals", _running(r"C:\mt\BIL2"))
    monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\BIL2")
    monkeypatch.setattr(
        terminals,
        "_read_account_summary",
        lambda: {"login": 49662626, "server": "HFMarketsGlobal-Demo", "mode": "DEMO"},
    )
    # The full probe must not be needed for the attached terminal.
    monkeypatch.setattr(terminals, "probe_accounts", lambda: {"ok": False})

    view = terminals.list_terminals()
    bil2 = next(t for t in view["terminals"] if t["id"] == "bil2")
    assert bil2["account_verified"] is True
    assert bil2["account"]["login"] == 49662626
    assert bil2["account"]["mode"] == "DEMO"


def test_full_probe_runs_when_idle(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        terminals._account_cache[terminals._norm(r"C:\mt\VITO2")] = {
            "login": 205022033,
            "server": "HFMarketsGlobal-Live15",
            "mode": "LIVE",
        }
        return {"ok": True}

    monkeypatch.setattr(terminals, "scan_running_terminals", _running(r"C:\mt\VITO2"))
    monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)
    monkeypatch.setattr(terminals, "_read_account_summary", lambda: None)
    monkeypatch.setattr(terminals, "probe_accounts", fake_probe)

    assert terminals.auto_probe_accounts() is True
    view = terminals.list_terminals()
    vito2 = next(t for t in view["terminals"] if t["id"] == "vito2")
    assert calls["n"] == 1
    assert vito2["account_verified"] is True
    assert vito2["account"]["mode"] == "LIVE"


def test_full_probe_is_skipped_when_armed(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_probe():  # pragma: no cover - must NOT be called
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(terminals, "scan_running_terminals", _running(r"C:\mt\BIL2"))
    monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)
    monkeypatch.setattr(terminals, "_read_account_summary", lambda: None)
    monkeypatch.setattr(terminals, "probe_accounts", fake_probe)
    terminals._state_for("bil2")["armed"] = True
    terminals._sync_backcompat_globals()

    assert terminals.auto_probe_accounts() is False
    terminals.list_terminals()
    assert calls["n"] == 0  # fail-closed: no binding move while armed


def test_auto_probe_does_not_recurse(monkeypatch) -> None:
    """The re-entrancy guard prevents endpoint probe -> list -> probe loops."""
    calls = {"n": 0}

    def counting_probe():
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(terminals, "scan_running_terminals", _running(r"C:\mt\BIL2"))
    monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)
    monkeypatch.setattr(terminals, "_read_account_summary", lambda: None)
    monkeypatch.setattr(terminals, "probe_accounts", counting_probe)

    # Simulate being inside a probe already: the guard must refuse a nested run.
    terminals._auto_probe_running = True
    try:
        assert terminals.auto_probe_accounts() is False
    finally:
        terminals._auto_probe_running = False
    assert calls["n"] == 0
    # Normal path still works afterwards.
    assert terminals.auto_probe_accounts() is True
    assert calls["n"] == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
