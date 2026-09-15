# -*- coding: utf-8 -*-
"""Metrics registry for observability — EPIC 16.05, 16.08–16.09, 16.11–16.17.

Lightweight in-process counters/gauges/histograms with label support and
domain-specific convenience recorders (risk, execution, committee,
learning, telegram, provider, tokens, supervisor KPIs).
"""

from typing import Any, Dict, List, Optional, Tuple

LabelKey = Tuple[Tuple[str, str], ...]


def _label_key(labels: Optional[Dict[str, Any]]) -> LabelKey:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


class MetricsRegistry:
    """In-memory metrics registry with labeled counters, gauges, histograms."""

    def __init__(self) -> None:
        self._counters: Dict[str, Dict[LabelKey, float]] = {}
        self._gauges: Dict[str, Dict[LabelKey, float]] = {}
        self._histograms: Dict[str, Dict[LabelKey, List[float]]] = {}

    # ── Core primitives ─────────────────────────────────────────────────────
    def increment(
        self, name: str, value: float = 1.0, labels: Optional[Dict[str, Any]] = None
    ) -> None:
        key = _label_key(labels)
        self._counters.setdefault(name, {})
        self._counters[name][key] = self._counters[name].get(key, 0.0) + value

    def get_counter(self, name: str, labels: Optional[Dict[str, Any]] = None) -> float:
        return self._counters.get(name, {}).get(_label_key(labels), 0.0)

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, Any]] = None) -> None:
        self._gauges.setdefault(name, {})[_label_key(labels)] = float(value)

    def get_gauge(self, name: str, labels: Optional[Dict[str, Any]] = None) -> Optional[float]:
        return self._gauges.get(name, {}).get(_label_key(labels))

    def observe(self, name: str, value: float, labels: Optional[Dict[str, Any]] = None) -> None:
        self._histograms.setdefault(name, {}).setdefault(_label_key(labels), []).append(
            float(value)
        )

    def get_histogram(self, name: str, labels: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        values = self._histograms.get(name, {}).get(_label_key(labels), [])
        count = len(values)
        total = sum(values)
        return {
            "count": count,
            "sum": total,
            "avg": (total / count) if count else 0.0,
            "min": min(values) if values else 0.0,
            "max": max(values) if values else 0.0,
        }

    # ── Domain recorders ────────────────────────────────────────────────────
    def record_risk_decision(self, verdict: str) -> None:
        """16.08 Risk decisions."""
        self.increment("risk.decisions", labels={"verdict": verdict})

    def record_execution(
        self,
        symbol: str,
        success: bool,
        slippage: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        """16.09 Execution metrics."""
        result = "success" if success else "failure"
        self.increment("execution.orders", labels={"symbol": symbol, "result": result})
        self.observe("execution.slippage", slippage, labels={"symbol": symbol})
        self.observe("execution.latency_ms", latency_ms, labels={"symbol": symbol})

    def record_supervisor_kpi(
        self, win_rate: float, profit_factor: float, max_drawdown: float
    ) -> None:
        """16.11 Supervisor KPIs."""
        self.set_gauge("supervisor.win_rate", win_rate)
        self.set_gauge("supervisor.profit_factor", profit_factor)
        self.set_gauge("supervisor.max_drawdown", max_drawdown)

    def record_committee_round(self, consensus: float, dissent_count: int = 0) -> None:
        """16.12 Committee consensus metrics."""
        self.observe("committee.consensus", consensus)
        if dissent_count:
            self.increment("committee.dissent", dissent_count)

    def record_decision_quality(self, correct: bool, confidence: float = 0.0) -> None:
        """16.13 Decision quality metrics."""
        result = "correct" if correct else "wrong"
        self.increment("decision.quality", labels={"result": result})
        self.observe("decision.confidence", confidence)

    def record_no_trade(self, reason: str, would_have_won: bool) -> None:
        """16.14 No-trade outcome metrics."""
        outcome = "missed_gain" if would_have_won else "avoided_loss"
        self.increment("no_trade.outcomes", labels={"reason": reason, "outcome": outcome})

    def record_pattern(self, pattern: str, validated: bool, sample_size: int = 0) -> None:
        """16.15 Learning pattern metrics."""
        self.increment(
            "learning.patterns",
            labels={"pattern": pattern, "validated": "true" if validated else "false"},
        )
        self.set_gauge("learning.pattern_sample_size", sample_size, labels={"pattern": pattern})

    def record_telegram_delivery(self, success: bool, latency_ms: float = 0.0) -> None:
        """16.16 Telegram delivery metrics."""
        result = "success" if success else "failed"
        self.increment("telegram.delivery", labels={"result": result})
        self.observe("telegram.latency_ms", latency_ms)

    def record_provider_health(self, provider: str, status: str, latency_ms: float = 0.0) -> None:
        """16.17 Provider/model health metrics."""
        self.increment("provider.health", labels={"provider": provider, "status": status})
        self.observe("provider.latency_ms", latency_ms, labels={"provider": provider})

    def record_token_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float = 0.0,
    ) -> None:
        """16.05 Model/token usage."""
        self.increment("llm.tokens", prompt_tokens, labels={"model": model, "type": "prompt"})
        self.increment(
            "llm.tokens", completion_tokens, labels={"model": model, "type": "completion"}
        )
        self.increment("llm.calls", labels={"model": model})
        if cost_usd:
            self.set_gauge("llm.cost_usd", cost_usd, labels={"model": model})

    # ── Snapshot ────────────────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        counters: Dict[str, Dict[str, float]] = {}
        for name, entries in self._counters.items():
            counters[name] = {
                "|".join(f"{k}={v}" for k, v in key) or "total": val for key, val in entries.items()
            }
        gauges: Dict[str, Dict[str, float]] = {}
        for name, entries in self._gauges.items():
            gauges[name] = {
                "|".join(f"{k}={v}" for k, v in key) or "total": val for key, val in entries.items()
            }
        histograms: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for name, entries in self._histograms.items():
            histograms[name] = {
                "|".join(f"{k}={v}" for k, v in key) or "total": self.get_histogram(name, dict(key))
                for key in entries
            }
        return {"counters": counters, "gauges": gauges, "histograms": histograms}
