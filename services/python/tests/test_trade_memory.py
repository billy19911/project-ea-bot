"""Tests for trade_memory module – Phase 16 Trade Memory.

Covers TradeMemoryStore lifecycle, agent decisions, risk checks, execution logs,
persistence, and history retrieval.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from memory import AgentDecisionRecord, TradeMemoryRecord, TradeMemoryStore


class TestAgentDecisionRecord:
    """Test AgentDecisionRecord dataclass."""

    def test_create_minimal(self):
        rec = AgentDecisionRecord(
            agent_name="StructureAgent",
            agent_type="structure",
            output_json={"signal": "buy"},
        )
        assert rec.agent_name == "StructureAgent"
        assert rec.agent_type == "structure"
        assert rec.confidence is None
        assert rec.recommendation == "hold"

    def test_create_full(self):
        rec = AgentDecisionRecord(
            agent_name="MomentumAgent",
            agent_type="momentum",
            output_json={"trend": "up"},
            confidence=0.85,
            recommendation="buy",
        )
        assert rec.confidence == 0.85
        assert rec.recommendation == "buy"


class TestTradeMemoryRecord:
    """Test TradeMemoryRecord dataclass and serialization."""

    def test_create_minimal(self):
        rec = TradeMemoryRecord(
            trade_id="test-123",
            symbol="EURUSD",
            side="buy",
            entry_price=1.1000,
            volume=0.1,
        )
        assert rec.trade_id == "test-123"
        assert rec.symbol == "EURUSD"
        assert rec.side == "buy"
        assert rec.exit_price is None
        assert rec.pnl is None
        assert rec.duration is None
        assert len(rec.decision_agents) == 0
        assert len(rec.risk_checks_passed) == 0
        assert len(rec.execution_logs) == 0
        assert rec.closed_at is None

    def test_as_dict_serialization(self):
        rec = TradeMemoryRecord(
            trade_id="abc",
            symbol="GBPUSD",
            side="sell",
            entry_price=1.3000,
            volume=0.05,
        )
        rec.decision_agents.append(
            AgentDecisionRecord("NewsAgent", "news", {"sentiment": "negative"}, 0.7, "sell")
        )
        rec.risk_checks_passed["drawdown"] = True
        rec.execution_logs.append({"type": "submit", "order_id": "o1"})

        data = rec.as_dict()
        assert data["trade_id"] == "abc"
        assert data["symbol"] == "GBPUSD"
        assert data["side"] == "sell"
        assert len(data["decision_agents"]) == 1
        assert data["decision_agents"][0]["agent_name"] == "NewsAgent"
        assert data["risk_checks_passed"]["drawdown"] is True
        assert len(data["execution_logs"]) == 1
        assert isinstance(data["created_at"], str)
        assert data["closed_at"] is None


class TestTradeMemoryStore:
    """Test TradeMemoryStore operations."""

    def test_record_trade_start(self):
        store = TradeMemoryStore(persist_path=None)
        trade_id = store.record_trade_start("EURUSD", "buy", 1.1000, 0.1)
        assert trade_id is not None
        assert len(store._records) == 1
        rec = store._records[trade_id]
        assert rec.symbol == "EURUSD"
        assert rec.side == "buy"
        assert rec.entry_price == 1.1000
        assert rec.volume == 0.1

    def test_record_agent_decision(self):
        store = TradeMemoryStore(persist_path=None)
        trade_id = store.record_trade_start("GBPUSD", "sell", 1.3000, 0.05)
        store.record_agent_decision(
            trade_id,
            "StructureAgent",
            "structure",
            {"level": "resistance"},
            confidence=0.9,
            recommendation="sell",
        )
        rec = store._records[trade_id]
        assert len(rec.decision_agents) == 1
        assert rec.decision_agents[0].agent_name == "StructureAgent"
        assert rec.decision_agents[0].confidence == 0.9

    def test_record_agent_decision_unknown_trade(self, caplog):
        store = TradeMemoryStore(persist_path=None)
        store.record_agent_decision("unknown", "Agent", "type", {})
        assert "unknown trade_id" in caplog.text.lower()

    def test_record_risk_check(self):
        store = TradeMemoryStore(persist_path=None)
        trade_id = store.record_trade_start("USDJPY", "buy", 150.0, 0.2)
        store.record_risk_check(trade_id, "daily_loss", True)
        store.record_risk_check(trade_id, "drawdown", False)
        rec = store._records[trade_id]
        assert rec.risk_checks_passed["daily_loss"] is True
        assert rec.risk_checks_passed["drawdown"] is False

    def test_record_risk_check_unknown_trade(self, caplog):
        store = TradeMemoryStore(persist_path=None)
        store.record_risk_check("fake", "check", True)
        assert "unknown trade_id" in caplog.text.lower()

    def test_record_execution(self):
        store = TradeMemoryStore(persist_path=None)
        trade_id = store.record_trade_start("AUDUSD", "sell", 0.6500, 0.15)
        store.record_execution(trade_id, {"type": "submit", "order_id": "o1"})
        store.record_execution(trade_id, {"type": "fill", "fill_price": 0.6500})
        rec = store._records[trade_id]
        assert len(rec.execution_logs) == 2
        assert rec.execution_logs[0]["type"] == "submit"
        assert rec.execution_logs[1]["fill_price"] == 0.6500

    def test_record_execution_unknown_trade(self, caplog):
        store = TradeMemoryStore(persist_path=None)
        store.record_execution("missing", {"type": "fill"})
        assert "unknown trade_id" in caplog.text.lower()

    def test_record_trade_end_buy(self):
        store = TradeMemoryStore(persist_path=None)
        trade_id = store.record_trade_start("EURUSD", "buy", 1.1000, 0.1)
        store.record_trade_end(trade_id, 1.1050)
        rec = store._records[trade_id]
        assert rec.exit_price == 1.1050
        assert rec.closed_at is not None
        assert rec.pnl == pytest.approx(0.0005)
        assert rec.duration is not None
        assert rec.duration >= 0

    def test_record_trade_end_sell(self):
        store = TradeMemoryStore(persist_path=None)
        trade_id = store.record_trade_start("GBPUSD", "sell", 1.3000, 0.05)
        store.record_trade_end(trade_id, 1.2950)
        rec = store._records[trade_id]
        assert rec.pnl == pytest.approx(0.00025)

    def test_record_trade_end_unknown_trade(self, caplog):
        store = TradeMemoryStore(persist_path=None)
        store.record_trade_end("ghost", 1.0)
        assert "unknown trade_id" in caplog.text.lower()

    def test_get_trade_history_all(self):
        store = TradeMemoryStore(persist_path=None)
        t1 = store.record_trade_start("EURUSD", "buy", 1.1000, 0.1)
        t2 = store.record_trade_start("GBPUSD", "sell", 1.3000, 0.05)
        history = store.get_trade_history()
        assert len(history) == 2
        assert history[0].trade_id in [t1, t2]

    def test_get_trade_history_by_symbol(self):
        store = TradeMemoryStore(persist_path=None)
        store.record_trade_start("EURUSD", "buy", 1.1000, 0.1)
        store.record_trade_start("GBPUSD", "sell", 1.3000, 0.05)
        store.record_trade_start("EURUSD", "sell", 1.1050, 0.1)
        history = store.get_trade_history(symbol="EURUSD")
        assert len(history) == 2
        for rec in history:
            assert rec.symbol == "EURUSD"

    def test_get_trade_history_limit(self):
        store = TradeMemoryStore(persist_path=None)
        for i in range(10):
            store.record_trade_start("USDJPY", "buy", 150.0 + i, 0.1)
        history = store.get_trade_history(limit=5)
        assert len(history) == 5

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "test_memory.json"
            store1 = TradeMemoryStore(persist_path=str(p))
            t1 = store1.record_trade_start("EURUSD", "buy", 1.1000, 0.1)
            store1.record_agent_decision(t1, "Agent1", "structure", {"x": 1}, 0.8, "buy")
            store1.record_risk_check(t1, "check1", True)
            store1.record_execution(t1, {"type": "fill"})
            store1.record_trade_end(t1, 1.1050)

            store2 = TradeMemoryStore(persist_path=str(p))
            assert len(store2._records) == 1
            rec = store2._records[t1]
            assert rec.symbol == "EURUSD"
            assert rec.exit_price == 1.1050
            assert len(rec.decision_agents) == 1
            assert rec.decision_agents[0].agent_name == "Agent1"
            assert rec.risk_checks_passed["check1"] is True
            assert len(rec.execution_logs) == 1

    def test_shutdown_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "shutdown_test.json"
            store = TradeMemoryStore(persist_path=str(p))
            store.record_trade_start("AUDUSD", "sell", 0.6500, 0.15)
            store.shutdown()
            assert p.exists()
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) == 1
            assert data[0]["symbol"] == "AUDUSD"

    def test_load_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "nonexistent.json"
            store = TradeMemoryStore(persist_path=str(p))
            assert len(store._records) == 0
