# -*- coding: utf-8 -*-
"""Tests for observability module — EPIC 16.

Covers structured event/task traces (16.03–16.04), domain metrics
(16.05, 16.08–16.09, 16.11–16.17), and alerts (16.10).
"""

import pytest

from src.observability import AlertManager, AlertSeverity, MetricsRegistry, TraceCollector


class TestTraceCollector:
    """16.03 Event traces & 16.04 Task traces."""

    def test_start_and_finish_span(self) -> None:
        tc = TraceCollector()
        span = tc.start_span("market.analyze", trace_id="t1")
        assert span.name == "market.analyze"
        assert span.trace_id == "t1"
        assert span.finished_at is None
        tc.finish_span(span.span_id, status="ok")
        assert span.finished_at is not None
        assert span.status == "ok"

    def test_span_duration_recorded(self) -> None:
        tc = TraceCollector()
        span = tc.start_span("risk.assess")
        tc.finish_span(span.span_id)
        assert span.duration_ms is not None
        assert span.duration_ms >= 0

    def test_parent_child_spans(self) -> None:
        tc = TraceCollector()
        parent = tc.start_span("decision.cycle", trace_id="t2")
        child = tc.start_span("agent.run", trace_id="t2", parent_id=parent.span_id)
        assert child.parent_id == parent.span_id
        assert child.trace_id == "t2"

    def test_task_trace_groups_spans(self) -> None:
        tc = TraceCollector()
        tc.start_span("task.analysis", trace_id="task-1")
        tc.start_span("task.structure", trace_id="task-1")
        trace = tc.get_trace("task-1")
        assert len(trace.spans) == 2
        assert trace.task_id == "task-1"

    def test_trace_status_failed_when_span_fails(self) -> None:
        tc = TraceCollector()
        span = tc.start_span("execution.order", trace_id="t3")
        tc.finish_span(span.span_id, status="error")
        trace = tc.get_trace("t3")
        assert trace.status == "error"

    def test_unknown_trace_returns_none(self) -> None:
        tc = TraceCollector()
        assert tc.get_trace("missing") is None

    def test_finish_unknown_span_returns_false(self) -> None:
        tc = TraceCollector()
        assert tc.finish_span("nope") is False


class TestMetricsRegistry:
    """16.05, 16.08–16.09, 16.11–16.17 domain metrics."""

    def test_counter_increment(self) -> None:
        m = MetricsRegistry()
        m.increment("decisions.total", labels={"symbol": "XAUUSD"})
        m.increment("decisions.total", labels={"symbol": "XAUUSD"})
        assert m.get_counter("decisions.total", {"symbol": "XAUUSD"}) == 2

    def test_counter_separates_labels(self) -> None:
        m = MetricsRegistry()
        m.increment("trades.total", labels={"side": "buy"})
        m.increment("trades.total", labels={"side": "sell"})
        assert m.get_counter("trades.total", {"side": "buy"}) == 1
        assert m.get_counter("trades.total", {"side": "sell"}) == 1

    def test_gauge_set(self) -> None:
        m = MetricsRegistry()
        m.set_gauge("risk.utilization", 42.5)
        assert m.get_gauge("risk.utilization") == 42.5

    def test_histogram_observe(self) -> None:
        m = MetricsRegistry()
        m.observe("latency.ms", 120.0)
        m.observe("latency.ms", 80.0)
        stats = m.get_histogram("latency.ms")
        assert stats["count"] == 2
        assert stats["sum"] == 200.0
        assert stats["avg"] == 100.0

    def test_risk_decision_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_risk_decision(verdict="approve")
        m.record_risk_decision(verdict="approve")
        m.record_risk_decision(verdict="reject")
        assert m.get_counter("risk.decisions", {"verdict": "approve"}) == 2
        assert m.get_counter("risk.decisions", {"verdict": "reject"}) == 1

    def test_execution_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_execution(symbol="XAUUSD", success=True, slippage=0.3, latency_ms=150)
        assert m.get_counter("execution.orders", {"symbol": "XAUUSD", "result": "success"}) == 1
        assert m.get_histogram("execution.slippage", {"symbol": "XAUUSD"})["count"] == 1
        assert m.get_histogram("execution.latency_ms", {"symbol": "XAUUSD"})["sum"] == 150

    def test_supervisor_kpi_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_supervisor_kpi(win_rate=58.5, profit_factor=1.8, max_drawdown=9.2)
        assert m.get_gauge("supervisor.win_rate") == 58.5
        assert m.get_gauge("supervisor.profit_factor") == 1.8
        assert m.get_gauge("supervisor.max_drawdown") == 9.2

    def test_committee_consensus_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_committee_round(consensus=0.75, dissent_count=2)
        stats = m.get_histogram("committee.consensus")
        assert stats["count"] == 1
        assert stats["avg"] == 0.75
        assert m.get_counter("committee.dissent") == 2

    def test_decision_quality_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_decision_quality(correct=True, confidence=0.9)
        m.record_decision_quality(correct=False, confidence=0.6)
        assert m.get_counter("decision.quality", {"result": "correct"}) == 1
        assert m.get_counter("decision.quality", {"result": "wrong"}) == 1

    def test_no_trade_outcome_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_no_trade(reason="low_confidence", would_have_won=True)
        m.record_no_trade(reason="low_confidence", would_have_won=False)
        assert (
            m.get_counter(
                "no_trade.outcomes", {"reason": "low_confidence", "outcome": "avoided_loss"}
            )
            == 1
        )
        assert (
            m.get_counter(
                "no_trade.outcomes", {"reason": "low_confidence", "outcome": "missed_gain"}
            )
            == 1
        )

    def test_learning_pattern_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_pattern(pattern="london_breakout", validated=True, sample_size=25)
        assert (
            m.get_counter("learning.patterns", {"pattern": "london_breakout", "validated": "true"})
            == 1
        )
        assert m.get_gauge("learning.pattern_sample_size", {"pattern": "london_breakout"}) == 25

    def test_telegram_delivery_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_telegram_delivery(success=True, latency_ms=220)
        m.record_telegram_delivery(success=False, latency_ms=5000)
        assert m.get_counter("telegram.delivery", {"result": "success"}) == 1
        assert m.get_counter("telegram.delivery", {"result": "failed"}) == 1
        assert m.get_histogram("telegram.latency_ms")["count"] == 2

    def test_provider_health_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_provider_health(provider="9router", status="up", latency_ms=320)
        m.record_provider_health(provider="9router", status="down", latency_ms=0)
        assert m.get_counter("provider.health", {"provider": "9router", "status": "up"}) == 1
        assert m.get_counter("provider.health", {"provider": "9router", "status": "down"}) == 1

    def test_token_usage_metrics(self) -> None:
        m = MetricsRegistry()
        m.record_token_usage(
            model="gemini-flash", prompt_tokens=1000, completion_tokens=500, cost_usd=0.002
        )
        assert m.get_counter("llm.tokens", {"model": "gemini-flash", "type": "prompt"}) == 1000
        assert m.get_counter("llm.tokens", {"model": "gemini-flash", "type": "completion"}) == 500
        assert m.get_gauge("llm.cost_usd", {"model": "gemini-flash"}) == 0.002

    def test_snapshot_returns_all_sections(self) -> None:
        m = MetricsRegistry()
        m.increment("a.total")
        m.set_gauge("b.gauge", 1.0)
        m.observe("c.hist", 5.0)
        snap = m.snapshot()
        assert "counters" in snap
        assert "gauges" in snap
        assert "histograms" in snap

    def test_missing_metric_defaults(self) -> None:
        m = MetricsRegistry()
        assert m.get_counter("nope") == 0
        assert m.get_gauge("nope") is None
        assert m.get_histogram("nope")["count"] == 0


class TestAlertManager:
    """16.10 Alerts."""

    def test_register_and_trigger_alert(self) -> None:
        am = AlertManager()
        am.add_rule(name="high_error_rate", metric="error.rate", threshold=5.0, severity="critical")
        alerts = am.evaluate({"error.rate": 7.5})
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL
        assert alerts[0].value == 7.5

    def test_no_alert_below_threshold(self) -> None:
        am = AlertManager()
        am.add_rule(name="high_error_rate", metric="error.rate", threshold=5.0)
        alerts = am.evaluate({"error.rate": 2.0})
        assert alerts == []

    def test_below_comparison_rule(self) -> None:
        am = AlertManager()
        am.add_rule(name="low_win_rate", metric="win.rate", threshold=40.0, comparison="below")
        alerts = am.evaluate({"win.rate": 35.0})
        assert len(alerts) == 1

    def test_alert_deduplication(self) -> None:
        am = AlertManager()
        am.add_rule(name="high_drawdown", metric="drawdown", threshold=10.0)
        first = am.evaluate({"drawdown": 12.0})
        second = am.evaluate({"drawdown": 13.0})
        assert len(first) == 1
        assert len(second) == 0  # already firing

    def test_alert_resolves_when_back_to_normal(self) -> None:
        am = AlertManager()
        am.add_rule(name="high_drawdown", metric="drawdown", threshold=10.0)
        am.evaluate({"drawdown": 12.0})
        resolved = am.evaluate({"drawdown": 5.0})
        assert any(a.resolved for a in resolved)

    def test_active_alerts_listing(self) -> None:
        am = AlertManager()
        am.add_rule(name="r1", metric="m1", threshold=1.0)
        am.add_rule(name="r2", metric="m2", threshold=1.0)
        am.evaluate({"m1": 2.0, "m2": 0.0})
        assert len(am.active_alerts()) == 1

    def test_clear_alerts(self) -> None:
        am = AlertManager()
        am.add_rule(name="r1", metric="m1", threshold=1.0)
        am.evaluate({"m1": 2.0})
        am.clear()
        assert am.active_alerts() == []

    def test_invalid_severity_rejected(self) -> None:
        am = AlertManager()
        with pytest.raises(ValueError):
            am.add_rule(name="bad", metric="m", threshold=1.0, severity="extreme")
