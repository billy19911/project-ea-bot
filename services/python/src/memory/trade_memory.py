"""Trade Memory module – archival of trade history, decisions, risk checks, execution logs.

Provides in‑memory store with optional JSON persistence for debugging or post‑mortem analysis.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentDecisionRecord:
    """Capture a single agent's recommendation for a trade.

    Attributes:
        agent_name: Human‑readable identifier, e.g. "StructureAgent".
        agent_type: Category – "structure", "momentum", "volatility", "news", "synthesis".
        output_json: Full JSON payload returned by the LLM.
        confidence: Optional confidence score (0‑1) if provided.
        recommendation: Final string decision – "buy", "sell", "hold".
    """

    agent_name: str
    agent_type: str
    output_json: Dict[str, Any]
    confidence: Optional[float] = None
    recommendation: str = "hold"


@dataclass
class TradeMemoryRecord:
    """Aggregated record for a completed trade.

    trade_id: UUID string – unique identifier for correlation.
    symbol: Trading symbol (e.g. "EURUSD").
    side: "buy" or "sell".
    entry_price: Price at entry.
    volume: Lots/units.
    exit_price: Price at exit (may be None until closed).
    pnl: Profit‑and‑loss (float, may be None until closed).
    duration: Seconds the trade was open.
    decision_agents: List of AgentDecisionRecord.
    risk_checks_passed: Mapping of check name → bool.
    execution_logs: List of raw order events (dicts).
    created_at: UTC timestamp when trade entered.
    closed_at: UTC timestamp when trade exited (None if open).
    """

    trade_id: str
    symbol: str
    side: str
    entry_price: float
    volume: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    duration: Optional[int] = None
    decision_agents: List[AgentDecisionRecord] = field(default_factory=list)
    risk_checks_passed: Dict[str, bool] = field(default_factory=dict)
    execution_logs: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None

    def as_dict(self) -> Dict[str, Any]:
        """Serialize to JSON‑compatible dict.

        Datetimes become ISO strings; nested dataclasses are recursively converted.
        """
        data = asdict(self)
        data["decision_agents"] = [asdict(a) for a in self.decision_agents]
        data["created_at"] = self.created_at.isoformat()
        if self.closed_at:
            data["closed_at"] = self.closed_at.isoformat()
        else:
            data["closed_at"] = None
        return data


class TradeMemoryStore:
    """Simple in‑memory store with optional JSON persistence.

    ``record_*`` methods update the active TradeMemoryRecord identified by ``trade_id``.
    """

    def __init__(self, persist_path: Optional[str] = None):
        self._records: Dict[str, TradeMemoryRecord] = {}
        self._persist_path = persist_path  # None means persistence disabled.
        if persist_path:
            try:
                with open(self._persist_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    for rec in raw:
                        rec["decision_agents"] = [
                            AgentDecisionRecord(**a) for a in rec.get("decision_agents", [])
                        ]
                        rec["created_at"] = datetime.fromisoformat(rec["created_at"]).replace(
                            tzinfo=timezone.utc
                        )
                        if rec.get("closed_at"):
                            rec["closed_at"] = datetime.fromisoformat(rec["closed_at"]).replace(
                                tzinfo=timezone.utc
                            )
                        self._records[rec["trade_id"]] = TradeMemoryRecord(**rec)
                logger.info(
                    "Loaded trade memory from %s (%d records)",
                    self._persist_path,
                    len(self._records),
                )
            except FileNotFoundError:
                logger.debug("No existing trade memory file at %s", self._persist_path)
            except Exception as exc:  # pragma: no cover – defensive.
                logger.warning("Failed to load trade memory %s: %s", self._persist_path, exc)

    def _new_trade_id(self) -> str:
        return str(uuid.uuid4())

    def record_trade_start(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        volume: float,
    ) -> str:
        """Create a new TradeMemoryRecord and return its ID."""
        trade_id = self._new_trade_id()
        record = TradeMemoryRecord(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            volume=volume,
        )
        self._records[trade_id] = record
        logger.debug("Trade start recorded: %s", trade_id)
        return trade_id

    def record_agent_decision(
        self,
        trade_id: str,
        agent_name: str,
        agent_type: str,
        output_json: Dict[str, Any],
        confidence: Optional[float] = None,
        recommendation: str = "hold",
    ) -> None:
        """Append an AgentDecisionRecord to the trade's history."""
        record = self._records.get(trade_id)
        if not record:
            logger.warning("Agent decision for unknown trade_id %s", trade_id)
            return
        decision = AgentDecisionRecord(
            agent_name=agent_name,
            agent_type=agent_type,
            output_json=output_json,
            confidence=confidence,
            recommendation=recommendation,
        )
        record.decision_agents.append(decision)
        logger.debug(
            "Agent %s (%s) decision recorded for trade %s",
            agent_name,
            agent_type,
            trade_id,
        )

    def record_risk_check(self, trade_id: str, check_name: str, passed: bool) -> None:
        """Log outcome of a single risk gate check."""
        rec = self._records.get(trade_id)
        if not rec:
            logger.warning("Risk check for unknown trade_id %s", trade_id)
            return
        rec.risk_checks_passed[check_name] = passed
        logger.debug("Risk check %s = %s for trade %s", check_name, passed, trade_id)

    def record_execution(self, trade_id: str, order_event: Dict[str, Any]) -> None:
        """Append raw order engine event (e.g. submission, fill, reject)."""
        rec = self._records.get(trade_id)
        if not rec:
            logger.warning("Execution log for unknown trade_id %s", trade_id)
            return
        rec.execution_logs.append(order_event)
        logger.debug(
            "Execution event recorded for trade %s: %s",
            trade_id,
            order_event.get("type"),
        )

    def record_trade_end(
        self,
        trade_id: str,
        exit_price: float,
        exit_time: Optional[datetime] = None,
    ) -> None:
        """Close a trade – compute P&L, duration, set timestamps."""
        rec = self._records.get(trade_id)
        if not rec:
            logger.warning("Trade end for unknown trade_id %s", trade_id)
            return
        rec.exit_price = exit_price
        rec.closed_at = (exit_time or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)
        if rec.side.lower() == "buy":
            price_diff = exit_price - rec.entry_price
        else:
            price_diff = rec.entry_price - exit_price
        rec.pnl = price_diff * rec.volume
        rec.duration = int((rec.closed_at - rec.created_at).total_seconds())
        logger.info(
            "Trade %s closed – P&L: %.4f, duration %ds",
            trade_id,
            rec.pnl,
            rec.duration,
        )
        self._persist()

    def get_trade_history(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> List[TradeMemoryRecord]:
        """Return recent trade records, optionally filtered by ``symbol`` (newest first)."""
        records = list(self._records.values())
        if symbol:
            records = [r for r in records if r.symbol == symbol]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]

    def _persist(self) -> None:
        """Write current memory to ``self._persist_path`` as a JSON list."""
        if not self._persist_path:
            return
        try:
            with open(self._persist_path, "w", encoding="utf-8") as f:
                payload = [r.as_dict() for r in self._records.values()]
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.debug("Persisted %d trade records to %s", len(self._records), self._persist_path)
        except Exception as exc:  # pragma: no cover – defensive.
            logger.error("Failed to persist trade memory: %s", exc)

    def shutdown(self) -> None:
        """Call at application exit to ensure data is flushed to disk."""
        self._persist()
