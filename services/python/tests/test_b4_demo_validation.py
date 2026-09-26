# -*- coding: utf-8 -*-
"""Unit tests for the B-4 controlled DEMO validation harness (T1).

All tests are mock-based: a fake ``MetaTrader5`` module and a fake
``mt5.terminals`` module are injected into :class:`DemoValidationHarness`, so no
live terminal or broker connection is required.

The harness module is loaded *by path* (it lives outside the ``tests`` package,
under ``scripts/``), which also exercises its import bootstrap.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_PATH = REPO_ROOT / "scripts" / "b4_demo_validation.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("b4_demo_validation", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["b4_demo_validation"] = module
    spec.loader.exec_module(module)
    return module


harness_mod = _load_harness()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeTick:
    def __init__(self, bid=60000.0, ask=60010.0, t=1700000000):
        self.bid = bid
        self.ask = ask
        self.time = t


class FakeSymbolInfo:
    def __init__(self, volume_min=0.01, volume_step=0.01, digits=2, filling_mode=1):
        self.name = "X"
        self.volume_min = volume_min
        self.volume_step = volume_step
        self.digits = digits
        self.filling_mode = filling_mode


class FakeAccount:
    def __init__(
        self, login=49662626, server="Demo-Server", trade_mode=0, balance=10000.0
    ):
        self.login = login
        self.server = server
        self.trade_mode = trade_mode
        self.balance = balance
        self.equity = balance
        self.currency = "USD"
        self.leverage = 100


class FakePosition:
    def __init__(
        self,
        ticket=555001,
        symbol="#BTCUSD",
        volume=0.01,
        magic=84004,
        comment="B4DEMO",
    ):
        self.ticket = ticket
        self.symbol = symbol
        self.volume = volume
        self.price_open = 60010.0
        self.sl = 0.0
        self.tp = 0.0
        self.magic = magic
        self.comment = comment
        self.type = 0
        self.profit = 0.0


class FakeOrderCheck:
    def __init__(self, retcode=0, comment="Done"):
        self.retcode = retcode
        self.comment = comment
        self.balance = 10000.0
        self.margin = 12.0
        self.margin_free = 9988.0


class FakeSendResult:
    def __init__(self, retcode=10009, order=555001, comment="Done", price=60010.0):
        self.retcode = retcode
        self.order = order
        self.deal = order
        self.comment = comment
        self.price = price
        self.volume = 0.01


class FakeMT5:
    """Minimal fake of the MetaTrader5 module surface used by the harness."""

    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0

    def __init__(self, *, account=None, tick=None, symbol_info=None, init_ok=True):
        self._account = account if account is not None else FakeAccount()
        self._tick = tick if tick is not None else FakeTick()
        self._symbol_info = symbol_info if symbol_info is not None else FakeSymbolInfo()
        self._init_ok = init_ok
        self._positions = []
        self.initialized = False
        self.shutdown_called = False
        self.order_check_calls = 0
        self.order_send_calls = 0

    def initialize(self, path=None):
        self.initialized = True
        return self._init_ok

    def shutdown(self):
        self.shutdown_called = True

    def account_info(self):
        return self._account if self.initialized else None

    def symbol_info_tick(self, symbol):
        return self._tick

    def symbol_info(self, symbol):
        return self._symbol_info

    def positions_get(self, ticket=None):
        if ticket is None:
            return list(self._positions)
        return [p for p in self._positions if p.ticket == ticket]

    def order_check(self, payload):
        self.order_check_calls += 1
        self.last_check_payload = payload
        return FakeOrderCheck()

    def order_send(self, payload):
        self.order_send_calls += 1
        self.last_send_payload = payload
        pos = FakePosition()
        self._positions.append(pos)
        return FakeSendResult(order=pos.ticket)


class FakeTerminals:
    """Fake of ``src.mt5.terminals`` used by the harness arm/select flow."""

    def __init__(self, *, running=True, armed_ok=True, arm_permitted=True):
        self.running = running
        self.armed_ok = armed_ok
        self.arm_permitted = arm_permitted
        self.arm_calls = []
        self.select_calls = []

    def list_terminals(self):
        return {
            "terminals": [
                {
                    "id": "bil2",
                    "running": self.running,
                    "selected": True,
                    "attached": True,
                    "execution_allowed": True,
                }
            ]
        }

    def select_terminal(self, terminal_id):
        self.select_calls.append(terminal_id)
        return {"ok": True, "message": "selected"}

    def arm_terminal(self, terminal_id, armed):
        self.arm_calls.append((terminal_id, armed))
        return {"ok": self.armed_ok, "armed": self.armed_ok, "message": "armed"}

    def execution_permitted(self):
        return self.arm_permitted


def _make_harness(mt5, terminals=None, **kwargs):
    return harness_mod.DemoValidationHarness(
        mt5_module=mt5,
        terminals_module=terminals if terminals is not None else FakeTerminals(),
        stdout=open(__import__("os").devnull, "w"),
        **kwargs,
    )


@pytest.fixture
def evidence_paths(monkeypatch, tmp_path):
    """Redirect evidence files into a throwaway dir for every test."""
    json_path = tmp_path / "evidence.json"
    md_path = tmp_path / "evidence.md"
    monkeypatch.setattr(harness_mod, "_EVIDENCE_JSON", json_path)
    monkeypatch.setattr(harness_mod, "_EVIDENCE_MD", md_path)
    return json_path, md_path


@pytest.fixture(autouse=True)
def isolate_order_ledger(monkeypatch, tmp_path):
    """Point the durable order ledger at a throwaway file for every test.

    Without this, the harness store wiring would append to the operator's real
    ``services/python/logs/order_state.jsonl`` and leak state across tests. The
    module-level state-machine store is also reset so a ticket recorded by one
    test can never surface as a phantom in another test's reconciliation.
    """
    monkeypatch.setenv("ORDER_STATE_PATH", str(tmp_path / "order_state.jsonl"))
    try:
        from src.execution.state_machine import reset_store, set_store

        reset_store()
        set_store(None)
    except Exception:  # noqa: BLE001 - isolation is best-effort
        pass
    yield


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------


def test_preflight_initialize_failure_aborts(evidence_paths):
    mt5 = FakeMT5(init_ok=False)
    h = _make_harness(mt5)
    code = h.run()
    assert code == 2
    assert h.evidence["result"] == "aborted"
    assert mt5.order_send_calls == 0


def test_preflight_account_none_aborts(evidence_paths):
    mt5 = FakeMT5(account=None)
    mt5.initialized = True  # simulate initialize ok but account_info None
    mt5.account_info = lambda: None
    h = _make_harness(mt5, timeout=0.5)
    code = h.run()
    assert code == 2
    assert "account_info()" in h.evidence["abort_reason"]


# ---------------------------------------------------------------------------
# DEMO guard (fail-closed) — the non-negotiable gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trade_mode", [1, 2, 99])
def test_demo_guard_rejects_non_demo(evidence_paths, trade_mode):
    mt5 = FakeMT5(account=FakeAccount(trade_mode=trade_mode))
    h = _make_harness(mt5)
    code = h.run()
    assert code == 2
    assert "DEMO GUARD TRIPPED" in h.evidence["abort_reason"]
    # Crucially: nothing was submitted and no order_check ran.
    assert mt5.order_send_calls == 0
    assert mt5.order_check_calls == 0


def test_demo_guard_passes_demo(evidence_paths):
    mt5 = FakeMT5(account=FakeAccount(trade_mode=0))
    h = _make_harness(mt5, dry_run=True)
    code = h.run()
    assert code == 0
    assert h.evidence["result"] == "dry_run_ok"


# ---------------------------------------------------------------------------
# Market check
# ---------------------------------------------------------------------------


def test_market_check_none_tick_aborts(evidence_paths):
    mt5 = FakeMT5()
    mt5.symbol_info_tick = lambda symbol: None
    h = _make_harness(mt5)
    code = h.run()
    assert code == 2
    assert "no market data" in h.evidence["abort_reason"]
    assert mt5.order_send_calls == 0


def test_market_check_zero_price_aborts(evidence_paths):
    mt5 = FakeMT5(tick=FakeTick(bid=0.0, ask=0.0))
    h = _make_harness(mt5)
    code = h.run()
    assert code == 2
    assert "no valid bid/ask" in h.evidence["abort_reason"]


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_performs_order_check_only(evidence_paths):
    mt5 = FakeMT5()
    h = _make_harness(mt5, dry_run=True)
    code = h.run()
    assert code == 0
    assert mt5.order_check_calls == 1
    assert mt5.order_send_calls == 0
    json_path, md_path = evidence_paths
    assert json_path.exists()
    assert md_path.exists()
    assert h.evidence["order_check"]["retcode"] == 0


def test_dry_run_order_check_failure_aborts(evidence_paths):
    mt5 = FakeMT5()
    mt5.order_check = lambda payload: FakeOrderCheck(
        retcode=10030, comment="IOC rejected"
    )
    h = _make_harness(mt5, dry_run=True)
    code = h.run()
    assert code == 2
    assert "order_check retcode=10030" in h.evidence["abort_reason"]


# ---------------------------------------------------------------------------
# Open-position guard (idempotent re-run)
# ---------------------------------------------------------------------------


def test_open_position_guard_skips_submit(evidence_paths):
    mt5 = FakeMT5()
    mt5._positions.append(FakePosition())
    h = _make_harness(mt5)
    code = h.run()
    assert code == 0
    assert h.evidence["result"] == "already_validated"
    assert h.evidence.get("skipped_submit") is True
    assert mt5.order_send_calls == 0
    assert mt5.order_check_calls == 0


def test_open_position_guard_ignores_foreign_positions(evidence_paths):
    mt5 = FakeMT5()
    mt5._positions.append(FakePosition(ticket=999, magic=12345, comment="OTHER"))
    h = _make_harness(mt5, dry_run=True)
    code = h.run()
    assert code == 0
    assert h.evidence["result"] == "dry_run_ok"  # proceeded past the guard


def test_open_position_guard_records_ledger_entry(evidence_paths):
    """Idempotent re-run records the observed broker position in the ledger."""
    mt5 = FakeMT5()
    mt5._positions.append(FakePosition(ticket=555777))
    h = _make_harness(mt5)
    assert h.run() == 0
    assert h.evidence["ledger_intent_id"] == "b4-t1-555777"
    ledger = Path(h.evidence["ledger_path"])
    assert ledger.exists()
    states = [
        json.loads(line)["state"]
        for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    assert "position_confirmed" in states


# ---------------------------------------------------------------------------
# Durable ledger wiring
# ---------------------------------------------------------------------------


def test_wire_store_attaches_durable_ledger(evidence_paths):
    mt5 = FakeMT5()
    h = _make_harness(mt5, dry_run=True)
    h._wire_store()
    assert h.evidence["ledger_path"]
    from src.execution.state_machine import get_store

    assert get_store() is h._store
    assert h._store is not None


# ---------------------------------------------------------------------------
# Arm gate
# ---------------------------------------------------------------------------


def test_arm_failure_aborts(evidence_paths):
    mt5 = FakeMT5()
    terms = FakeTerminals(armed_ok=False)
    h = _make_harness(mt5, terminals=terms)
    code = h.run()
    assert code == 2
    assert "arm_terminal failed" in h.evidence["abort_reason"]
    assert mt5.order_send_calls == 0


def test_execution_not_permitted_aborts(evidence_paths):
    mt5 = FakeMT5()
    terms = FakeTerminals(arm_permitted=False)
    h = _make_harness(mt5, terminals=terms)
    code = h.run()
    assert code == 2
    assert "execution_permitted() is False" in h.evidence["abort_reason"]
    assert mt5.order_send_calls == 0


def test_terminal_not_running_aborts(evidence_paths):
    mt5 = FakeMT5()
    terms = FakeTerminals(running=False)
    h = _make_harness(mt5, terminals=terms)
    code = h.run()
    assert code == 2
    assert "not running" in h.evidence["abort_reason"]


# ---------------------------------------------------------------------------
# Full submit path (engine wired to fake MT5 + fake terminals)
# ---------------------------------------------------------------------------


def _patch_native_engine(monkeypatch, mt5, terminals):
    """Wire the real ExecutionEngine to the fakes via the module seam.

    The engine imports MetaTrader5 and ``mt5.terminals`` lazily inside
    ``_send_to_mt5``/``_native_execution_armed``; those imports resolve to the
    REAL modules. We therefore inject the fakes into ``sys.modules`` so the
    genuine engine code path runs against them — no gate is bypassed.
    """
    monkeypatch.setitem(sys.modules, "MetaTrader5", mt5)
    monkeypatch.setitem(sys.modules, "src.mt5.terminals", terminals)
    # ``_get_armed_terminal_ids`` / ``_native_execution_armed`` try both
    # ``mt5.terminals`` and ``src.mt5.terminals``. Alias both to the fake.
    monkeypatch.setitem(sys.modules, "mt5.terminals", terminals)


def test_full_submit_places_one_order_and_verifies_fill(evidence_paths, monkeypatch):
    mt5 = FakeMT5()
    # Real positions_get starts empty; the fake order_send appends the position,
    # so _verify_fill finds the ticket on the first poll.
    terms = FakeTerminals()
    _patch_native_engine(monkeypatch, mt5, terms)

    h = _make_harness(mt5, terminals=terms)
    code = h.run()

    assert code == 0, h.evidence
    assert h.evidence["result"] == "filled"
    assert mt5.order_send_calls == 1
    assert h.evidence["execution_result"]["success"] is True
    assert h.evidence["execution_result"]["ticket"] == 555001
    assert h.evidence["position"]["ticket"] == 555001
    assert h.evidence["position"]["symbol"] == "#BTCUSD"
    assert ("bil2", True) in terms.arm_calls
    # Position must remain open (never closed by the harness).
    assert mt5.positions_get()[0].ticket == 555001


def test_full_submit_uses_volume_min_by_default(evidence_paths, monkeypatch):
    mt5 = FakeMT5(symbol_info=FakeSymbolInfo(volume_min=0.02))
    terms = FakeTerminals()
    _patch_native_engine(monkeypatch, mt5, terms)

    h = _make_harness(mt5, terminals=terms)
    assert h.run() == 0
    assert h.evidence["request"]["volume"] == 0.02
    assert mt5.last_send_payload["volume"] == 0.02


def test_full_submit_explicit_volume_override(evidence_paths, monkeypatch):
    mt5 = FakeMT5(symbol_info=FakeSymbolInfo(volume_min=0.01))
    terms = FakeTerminals()
    _patch_native_engine(monkeypatch, mt5, terms)

    h = _make_harness(mt5, terminals=terms, volume=0.05)
    assert h.run() == 0
    assert h.evidence["request"]["volume"] == 0.05


def test_full_submit_flags_fok_in_payload(evidence_paths, monkeypatch):
    """The engine payload must not force an IOC filling mode (broker needs FOK)."""
    mt5 = FakeMT5()
    terms = FakeTerminals()
    _patch_native_engine(monkeypatch, mt5, terms)

    h = _make_harness(mt5, terminals=terms)
    assert h.run() == 0
    assert "type_filling" not in mt5.last_send_payload


# ---------------------------------------------------------------------------
# Evidence format
# ---------------------------------------------------------------------------


def test_evidence_json_has_t1_section(evidence_paths):
    mt5 = FakeMT5()
    h = _make_harness(mt5, dry_run=True)
    assert h.run() == 0
    json_path, md_path = evidence_paths
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "t1" in payload
    t1 = payload["t1"]
    for key in ("timestamp", "terminal_path", "account", "symbol", "python_version"):
        assert key in t1
    assert "T1" in md_path.read_text(encoding="utf-8")


def test_evidence_md_is_append_friendly(evidence_paths):
    mt5 = FakeMT5()
    _make_harness(mt5, dry_run=True).run()
    _, md_path = evidence_paths
    first = md_path.read_text(encoding="utf-8")
    _make_harness(FakeMT5(), dry_run=True).run()
    second = md_path.read_text(encoding="utf-8")
    # A second run appends a new T1 section rather than overwriting.
    assert second.count("## T1 —") == 2
    assert first in second


def test_evidence_merge_preserves_prior_fill_data(evidence_paths):
    """An idempotent re-run must not clobber the original fill evidence."""
    json_path, _ = evidence_paths
    # Seed a prior JSON that has the richer fill data.
    json_path.write_text(
        json.dumps(
            {
                "t1": {
                    "order_check": {"retcode": 0},
                    "execution_result": {"success": True, "ticket": 424242},
                }
            }
        ),
        encoding="utf-8",
    )
    mt5 = FakeMT5()
    mt5._positions.append(FakePosition(ticket=424242))
    h = _make_harness(mt5)
    assert h.run() == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    # The prior order_check/execution_result survived the re-run.
    assert payload["t1"]["order_check"] == {"retcode": 0}
    assert payload["t1"]["execution_result"]["ticket"] == 424242


# ---------------------------------------------------------------------------
# CLI skeleton / stubs
# ---------------------------------------------------------------------------


def test_reconcile_dispatches_to_cmd(monkeypatch):
    """``reconcile`` now dispatches to the T2 command (no longer a stub)."""
    called = {}

    def fake_cmd(args):
        called["terminal_id"] = args.terminal_id
        return 0

    monkeypatch.setattr(harness_mod, "_cmd_reconcile", fake_cmd)
    assert harness_mod.main(["reconcile"]) == 0
    assert called["terminal_id"] == "bil2"


def test_recovery_check_dispatches_to_cmd(monkeypatch):
    """``recovery-check`` dispatches to the T3 command with the chosen stage."""
    called = {}

    def fake_cmd(args):
        called["stage"] = args.stage
        called["terminal_id"] = args.terminal_id
        return 0

    monkeypatch.setattr(harness_mod, "_cmd_recovery_check", fake_cmd)
    assert harness_mod.main(["recovery-check", "--stage", "pre"]) == 0
    assert called["stage"] == "pre"
    assert called["terminal_id"] == "bil2"


def test_recovery_check_requires_stage():
    """``--stage`` is mandatory — a bare invocation is rejected by argparse."""
    with pytest.raises(SystemExit):
        harness_mod.main(["recovery-check"])


def test_default_command_is_validate(monkeypatch):
    captured = {}

    def fake_validate(args):
        captured["symbol"] = args.symbol
        captured["dry_run"] = args.dry_run
        return 0

    monkeypatch.setattr(harness_mod, "_cmd_validate", fake_validate)
    assert harness_mod.main([]) == 0
    assert captured["symbol"] == "#BTCUSD"


def test_bootstrap_chdirs_into_services_python():
    assert Path.cwd() == REPO_ROOT / "services" / "python"
    assert str(REPO_ROOT / "services" / "python") in sys.path[:3]


def test_parse_send_result_retcode_zero_is_success():
    """Sanity: engine's result normalisation treats retcode 0 + order as done."""
    from src.execution.engine import ExecutionEngine

    engine = ExecutionEngine()
    res = engine._parse_send_result(
        SimpleNamespace(retcode=0, order=42, deal=42, comment="ok")
    )
    assert res["success"] is True
    assert res["ticket"] == 42


# ---------------------------------------------------------------------------
# T2 — live reconciliation (reconcile subcommand)
# ---------------------------------------------------------------------------


class FakeConnector:
    """Fake of ``src.mt5.connector`` for the reconcile attach step."""

    def __init__(self, *, live_ok=True):
        self._live = False
        self.live_ok = live_ok
        self.attach_calls = []

    def use_live_data_mode(self, path=None):
        self.attach_calls.append(path)
        self._live = bool(self.live_ok)
        return self._live

    def is_live_mode(self):
        return self._live


class FakeProviders:
    """Provider object exposing the four reconciliation hooks."""

    def __init__(
        self, *, internal_positions=None, broker_positions=None, broker_orders=None
    ):
        self._ip = list(internal_positions or [])
        self._bp = list(broker_positions or [])
        self._bo = list(broker_orders or [])

    def internal_positions(self):
        return list(self._ip)

    def broker_positions(self):
        return list(self._bp)

    def internal_orders(self):
        return []

    def broker_orders(self):
        return list(self._bo)


def _seed_t1_evidence(json_path, ticket):
    """Write a minimal evidence JSON carrying a T1 ticket."""
    json_path.write_text(
        json.dumps(
            {
                "t1": {
                    "execution_result": {"success": True, "ticket": ticket},
                    "position": {"ticket": ticket, "symbol": "#BTCUSD", "volume": 0.01},
                }
            }
        ),
        encoding="utf-8",
    )


def _make_reconcile_harness(providers, connector=None):
    """Build a harness wired for the reconcile path with fake providers."""
    return harness_mod.DemoValidationHarness(
        connector_module=connector if connector is not None else FakeConnector(),
        providers_factory=lambda: providers,
        stdout=open(__import__("os").devnull, "w"),
    )


def test_reconcile_matched_ticket_passes(evidence_paths):
    """T1 ticket present on both sides → matched, exit 0."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "symbol": "", "volume": None}],
        broker_positions=[{"ticket": 555001, "symbol": "#BTCUSD", "volume": 0.01}],
    )
    h = _make_reconcile_harness(providers)
    code = h.run_reconcile()

    assert code == 0
    t2 = h.evidence["t2"]
    assert t2["t1_ticket"] == 555001
    assert t2["t1_ticket_matched"] is True
    assert 555001 in t2["matched"]
    assert t2["missing_in_broker"] == []
    assert t2["missing_internal"] == []


def test_reconcile_missing_ticket_fails(evidence_paths):
    """T1 ticket absent from the broker side → not matched, exit non-zero."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "symbol": "", "volume": None}],
        broker_positions=[],  # broker does not report the ticket
    )
    h = _make_reconcile_harness(providers)
    code = h.run_reconcile()

    assert code == 3
    t2 = h.evidence["t2"]
    assert t2["t1_ticket_matched"] is False
    assert 555001 in t2["missing_in_broker"]
    assert h.evidence["result"] == "t1_ticket_unmatched"


def test_reconcile_volume_gap_is_reported_not_hidden(evidence_paths):
    """The ledger volume gap must surface as a classified field difference."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "symbol": "", "volume": None}],
        broker_positions=[{"ticket": 555001, "symbol": "#BTCUSD", "volume": 0.01}],
    )
    h = _make_reconcile_harness(providers)
    assert h.run_reconcile() == 0

    diffs = h.evidence["t2"]["field_differences"]
    volume_diffs = [d for d in diffs if d["field"] == "volume"]
    assert volume_diffs, "volume gap must be reported, not hidden"
    assert volume_diffs[0]["internal"] in (None, 0.0)
    assert volume_diffs[0]["broker"] == 0.01
    # Classified as the expected ledger-shape gap, never as a silent pass.
    assert volume_diffs[0]["classification"] == "expected_ledger_shape_gap"
    # It is a real (reported) mismatch — criticality is not faked.
    assert h.evidence["t2"]["has_critical"] is True


def test_reconcile_symbol_and_magic_gaps_classified_expected(evidence_paths):
    """Symbol/magic/sl-tp diffs from the ledger shape are classified expected."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "symbol": "", "volume": 0.01}],
        broker_positions=[
            {"ticket": 555001, "symbol": "#BTCUSD", "volume": 0.01, "magic": 84004}
        ],
    )
    h = _make_reconcile_harness(providers)
    assert h.run_reconcile() == 0

    diffs = {d["field"]: d for d in h.evidence["t2"]["field_differences"]}
    assert diffs["symbol"]["classification"] == "expected_ledger_shape_gap"
    assert diffs["magic"]["classification"] == "expected_ledger_shape_gap"


def test_reconcile_no_t1_evidence_aborts(evidence_paths):
    """Without T1 evidence there is no join key → abort (exit 2)."""
    json_path, _ = evidence_paths
    assert not json_path.exists()
    providers = FakeProviders()
    h = _make_reconcile_harness(providers)
    code = h.run_reconcile()
    assert code == 2
    assert h.evidence["t2"]["result"] == "aborted"
    assert "evidence" in h.evidence["t2"]["abort_reason"].lower()


def test_reconcile_attaches_connector(evidence_paths):
    """The reconcile path must attach the read-only connector to the terminal."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    connector = FakeConnector()
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "volume": None}],
        broker_positions=[{"ticket": 555001, "volume": 0.01}],
    )
    h = _make_reconcile_harness(providers, connector=connector)
    assert h.run_reconcile() == 0
    assert connector.attach_calls  # use_live_data_mode was called
    assert h.evidence["t2"]["broker_live"] is True


def test_reconcile_uses_durable_ledger(evidence_paths):
    """The internal side comes from the durable ledger, not a fabricated list."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    # Persist to the durable ledger the same way T1's idempotent re-run does:
    # attach the store FIRST, then write — so the record is on disk and must be
    # rehydrated by OrderStateStore() inside run_reconcile.
    from src.execution.state_machine import set_order, set_store
    from src.persistence.order_state_store import OrderStateStore

    store = OrderStateStore()
    set_store(store)
    set_order("b4-t1-555001", "position_confirmed", {"ticket": 555001})
    assert Path(store.path).exists()

    from src.execution.reconciliation_providers import MT5ReconciliationProviders

    providers = MT5ReconciliationProviders(
        connector=SimpleNamespace(
            get_positions=lambda: [
                {"ticket": 555001, "symbol": "#BTCUSD", "volume": 0.01}
            ],
            get_orders=lambda: [],
        )
    )
    h = _make_reconcile_harness(providers)
    assert h.run_reconcile() == 0
    assert h.evidence["t2"]["t1_ticket_matched"] is True
    assert h.evidence["ledger_path"] == store.path


def test_reconcile_writes_t2_evidence(evidence_paths):
    """The t2 section is merged into the JSON and appended to the MD."""
    json_path, md_path = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "volume": None}],
        broker_positions=[{"ticket": 555001, "volume": 0.01}],
    )
    h = _make_reconcile_harness(providers)
    assert h.run_reconcile() == 0

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "t2" in payload
    assert "raw_report" in payload["t2"]
    assert payload["t2"]["raw_report"]["matched"] == [555001]
    # T1 section preserved.
    assert payload["t1"]["execution_result"]["ticket"] == 555001
    assert "## T2 — Live reconciliation" in md_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T3 — restart recovery (recovery-check --stage pre/post)
# ---------------------------------------------------------------------------


class FakeArmStateTerminals:
    """Stateful fake of ``src.mt5.terminals`` tracking a real arm flag.

    A genuine restart constructs a fresh module (arm flag back to False), which
    the tests model by making a NEW instance for the ``post`` stage. Selection
    is modelled as persisted (survives the restart).
    """

    def __init__(self, *, armed=False, selected=True, running=True, saved="bil2"):
        self.armed = armed
        self.selected = selected
        self.running = running
        self.saved = saved
        self.arm_calls = []
        self.select_calls = []

    def list_terminals(self):
        return {
            "terminals": [
                {
                    "id": "bil2",
                    "running": self.running,
                    "selected": True,
                    "attached": True,
                    "armed": self.armed,
                    "execution_allowed": True,
                }
            ],
            "selected_id": "bil2" if self.selected else None,
            "execution_armed": self.armed,
            "armed_terminals": ["bil2"] if self.armed else [],
        }

    def select_terminal(self, terminal_id):
        self.select_calls.append(terminal_id)
        self.selected = True
        self.armed = False
        return {"ok": True, "message": "selected"}

    def arm_terminal(self, terminal_id, armed):
        self.arm_calls.append((terminal_id, armed))
        self.armed = bool(armed)
        return {"ok": True, "armed": self.armed, "message": "armed"}

    def execution_permitted(self):
        return bool(self.armed)


def _make_recovery_harness(providers, terminals, connector=None):
    return harness_mod.DemoValidationHarness(
        terminals_module=terminals,
        connector_module=connector if connector is not None else FakeConnector(),
        providers_factory=lambda: providers,
        stdout=open(__import__("os").devnull, "w"),
    )


def _seed_ledger_record(ticket, state="position_confirmed", intent_id=None):
    """Write a T1 record to the durable ledger FILE (isolated by fixture)."""
    from src.persistence.order_state_store import OrderStateStore

    store = OrderStateStore()
    store.set_order(intent_id or f"b4-t1-{ticket}", state, {"ticket": ticket})
    return store.path


# --- rehydration round-trip (the core T3 guarantee) ------------------------


def test_rehydration_round_trip_state_survives_new_store(evidence_paths):
    """write to ledger file → NEW store instance → state present (from disk)."""
    from src.persistence.order_state_store import OrderStateStore

    path = _seed_ledger_record(555001)
    # A brand-new instance must rehydrate the record from the file at __init__.
    fresh = OrderStateStore()
    record = fresh.get_order("b4-t1-555001")
    assert record is not None
    assert record["state"] == "position_confirmed"
    assert record["ticket"] == 555001
    assert fresh.path == path


def test_rehydration_from_file_not_memory(evidence_paths):
    """A fresh store with NO prior in-memory cache still reads the file."""
    from src.execution import state_machine

    # Wipe the process-wide in-memory store to model a restart.
    state_machine.reset_store()
    state_machine.set_store(None)
    _seed_ledger_record(555002)
    assert state_machine.get_store() is None

    # Wiring a fresh store rehydrates the file into memory.
    from src.persistence.order_state_store import OrderStateStore

    store = OrderStateStore()
    state_machine.set_store(store)
    assert state_machine.get_order("b4-t1-555002")["ticket"] == 555002


# --- stage pre -------------------------------------------------------------


def test_recovery_pre_records_ledger_file_and_arm_state(evidence_paths):
    """Stage pre: ticket in ledger FILE + arm state captured + armed."""
    json_path, md_path = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    _seed_ledger_record(555001)
    terms = FakeArmStateTerminals(armed=True)

    h = _make_recovery_harness(FakeProviders(), terms)
    code = h.run_recovery_check("pre")

    assert code == 0, h.evidence
    t3 = h.evidence["t3"]
    assert t3["stage"] == "pre"
    assert t3["t1_ticket"] == 555001
    assert t3["ledger_record"]["ticket"] == 555001
    assert t3["ledger_record"]["state"] == "position_confirmed"
    assert t3["arm_state"]["execution_armed"] is True
    assert "## T3" in md_path.read_text(encoding="utf-8")


def test_recovery_pre_aborts_without_ledger_record(evidence_paths):
    """Stage pre must fail-closed when the ticket is missing from the file."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 999999)  # ticket with NO ledger record
    terms = FakeArmStateTerminals(armed=True)
    h = _make_recovery_harness(FakeProviders(), terms)
    code = h.run_recovery_check("pre")
    assert code == 2
    assert h.evidence["t3"]["result"] == "aborted"
    assert "NO record" in h.evidence["t3"]["abort_reason"]


# --- stage post ------------------------------------------------------------


def test_recovery_post_rehydrates_reconciles_and_rearms(evidence_paths):
    """Full post-restart cycle: rehydrate + match + arm-empty + re-arm."""
    json_path, md_path = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    _seed_ledger_record(555001)
    # Fresh terminals instance models the restart: arm flag cleared (False).
    terms = FakeArmStateTerminals(armed=False)
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "symbol": "", "volume": None}],
        broker_positions=[{"ticket": 555001, "symbol": "#BTCUSD", "volume": 0.01}],
    )

    h = _make_recovery_harness(providers, terms)
    code = h.run_recovery_check("post")

    assert code == 0, h.evidence
    t3 = h.evidence["t3"]
    assert t3["stage"] == "post"
    assert t3["rehydrated_state"] == "position_confirmed"
    assert t3["arm_cleared"] is True
    assert t3["arm_state_post_restart"]["execution_armed"] is False
    assert t3["t1_ticket_matched"] is True
    assert 555001 in t3["matched"]
    # Re-armed via the same mechanism as T1.
    assert ("bil2", True) in terms.arm_calls
    assert t3["arm_state_after_rearm"]["execution_permitted"] is True
    assert t3["result"] == "recovered"
    assert "## T3" in md_path.read_text(encoding="utf-8")


def test_recovery_post_aborts_if_not_rehydrated(evidence_paths):
    """Post must fail-closed if the fresh store cannot find the ticket."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 888888)  # no ledger record written
    terms = FakeArmStateTerminals(armed=False)
    h = _make_recovery_harness(FakeProviders(), terms)
    code = h.run_recovery_check("post")
    assert code == 2
    assert "did NOT rehydrate" in h.evidence["t3"]["abort_reason"]


def test_recovery_post_detects_arm_not_cleared(evidence_paths):
    """If arm state somehow survived, post aborts (surfaces a real bug)."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    _seed_ledger_record(555001)
    # Terminals still armed — the opposite of a real restart.
    terms = FakeArmStateTerminals(armed=True)
    h = _make_recovery_harness(FakeProviders(), terms)
    code = h.run_recovery_check("post")
    assert code == 2
    assert "Arm state is NOT empty" in h.evidence["t3"]["abort_reason"]


def test_recovery_post_aborts_if_unmatched(evidence_paths):
    """Post must fail-closed when reconciliation no longer matches the ticket."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    _seed_ledger_record(555001)
    terms = FakeArmStateTerminals(armed=False)
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "symbol": "", "volume": None}],
        broker_positions=[],  # ticket gone from broker after restart
    )
    h = _make_recovery_harness(providers, terms)
    code = h.run_recovery_check("post")
    assert code == 2
    assert "NOT matched after restart" in h.evidence["t3"]["abort_reason"]


def test_recovery_post_writes_t3_section_preserving_t1_t2(evidence_paths):
    """The t3 section is merged without clobbering t1/t2."""
    json_path, _ = evidence_paths
    json_path.write_text(
        json.dumps(
            {
                "t1": {"execution_result": {"ticket": 555001}},
                "t2": {"result": "matched"},
            }
        ),
        encoding="utf-8",
    )
    _seed_ledger_record(555001)
    terms = FakeArmStateTerminals(armed=False)
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "volume": None}],
        broker_positions=[{"ticket": 555001, "volume": 0.01}],
    )
    h = _make_recovery_harness(providers, terms)
    assert h.run_recovery_check("post") == 0

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["t3"]["post"]["result"] == "recovered"
    assert payload["t1"]["execution_result"]["ticket"] == 555001
    assert payload["t2"]["result"] == "matched"


def test_recovery_pre_and_post_merge_into_both_stages(evidence_paths):
    """Pre + post (separate processes) both survive in the JSON t3 section."""
    json_path, _ = evidence_paths
    _seed_t1_evidence(json_path, 555001)
    _seed_ledger_record(555001)
    providers = FakeProviders(
        internal_positions=[{"ticket": 555001, "volume": None}],
        broker_positions=[{"ticket": 555001, "volume": 0.01}],
    )
    # Pre process (armed), then a FRESH terminals instance for post (cleared).
    assert (
        _make_recovery_harness(
            providers, FakeArmStateTerminals(armed=True)
        ).run_recovery_check("pre")
        == 0
    )
    assert (
        _make_recovery_harness(
            providers, FakeArmStateTerminals(armed=False)
        ).run_recovery_check("post")
        == 0
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "pre" in payload["t3"] and "post" in payload["t3"]
    assert payload["t3"]["stages_present"] == ["pre", "post"]
    assert payload["t3"]["both_stages_present"] is True
    assert payload["t3"]["pre"]["arm_state"]["execution_armed"] is True
    assert payload["t3"]["post"]["arm_cleared"] is True


def test_recovery_unknown_stage_raises(evidence_paths):
    h = _make_recovery_harness(FakeProviders(), FakeArmStateTerminals())
    with pytest.raises(harness_mod.ValidationAbort, match="unknown recovery stage"):
        h.run_recovery_check("bogus")
