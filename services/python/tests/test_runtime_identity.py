# -*- coding: utf-8 -*-
"""TASK 05 — runtime identity + singleton / duplicate-worker detection.

Proves the "runtime singleton rule" is observable at runtime:

* exactly one runtime/scheduler/queue/supervisor/pipeline/position-monitor/
  reconciliation instance per process;
* a market feed registers its own ``feed_instance_id`` on the runtime identity;
* every analysis log/trace carries ``process_id``, ``runtime_instance_id``,
  ``scheduler_instance_id`` and ``feed_instance_id``;
* two runtime instances (or two feeds) are distinguishable — the duplicate
  worker signal we need to detect.
"""

from __future__ import annotations

import json

from orchestration.runtime import OrchestrationRuntime, get_runtime, set_runtime
from orchestration.runtime_identity import RuntimeIdentity, new_instance_id, process_identity
from trading.event_engine import EventQueue
from trading.feed_loop import MarketFeedLoop
from trading.scheduler import AutonomousScheduler


# ----------------------------------------------------------------------
# Identity primitives
# ----------------------------------------------------------------------
def test_process_identity_has_pid_and_host():
    proc = process_identity()
    assert isinstance(proc["process_id"], int)
    assert proc["process_id"] > 0
    assert isinstance(proc["host"], str) and proc["host"]


def test_instance_ids_are_unique_and_kind_prefixed():
    a = new_instance_id("scheduler")
    b = new_instance_id("scheduler")
    assert a != b
    assert a.startswith("scheduler-")
    # Two distinct kind labels never collide.
    assert new_instance_id("feed").startswith("feed-")


def test_identity_registration_is_idempotent():
    ident = RuntimeIdentity("runtime")
    first = ident.register_scheduler()
    second = ident.register_scheduler()
    assert first == second  # first writer wins; never overwritten
    assert ident.scheduler_instance_id == first


def test_two_runtime_identities_are_distinct():
    a = RuntimeIdentity("runtime")
    b = RuntimeIdentity("runtime")
    assert a.runtime_instance_id != b.runtime_instance_id
    # Same process → same process_id.
    assert a.process_id == b.process_id


def test_log_fields_contain_the_four_required_ids():
    ident = RuntimeIdentity("runtime")
    ident.register_scheduler()
    ident.register_feed()
    fields = ident.log_fields()
    for key in (
        "process_id",
        "runtime_instance_id",
        "scheduler_instance_id",
        "feed_instance_id",
    ):
        assert key in fields
    assert fields["scheduler_instance_id"]
    assert fields["feed_instance_id"]


# ----------------------------------------------------------------------
# Runtime singleton identity
# ----------------------------------------------------------------------
def test_runtime_registers_all_singleton_component_ids():
    rt = OrchestrationRuntime()
    ident = rt.identity.to_dict()
    assert ident["process_id"] > 0
    assert ident["runtime_instance_id"]
    assert ident["queue_instance_id"]
    assert ident["scheduler_instance_id"]
    assert ident["supervisor_instance_id"]
    assert ident["pipeline_instance_id"]
    assert ident["position_monitor_instance_id"]
    assert ident["reconciliation_instance_id"]
    # Feed is registered only when the feed loop is constructed.
    assert ident["feed_instance_id"] is None


def test_scheduler_shares_the_runtime_identity_object():
    rt = OrchestrationRuntime()
    assert rt.scheduler.identity is rt.identity


def test_get_runtime_is_a_singleton():
    set_runtime(None)
    try:
        assert get_runtime() is get_runtime()
    finally:
        set_runtime(None)


# ----------------------------------------------------------------------
# Duplicate-worker detection
# ----------------------------------------------------------------------
def test_two_runtimes_have_different_instance_ids():
    a = OrchestrationRuntime()
    b = OrchestrationRuntime()
    assert a.identity.runtime_instance_id != b.identity.runtime_instance_id
    assert a.identity.scheduler_instance_id != b.identity.scheduler_instance_id
    # Same process though.
    assert a.identity.process_id == b.identity.process_id


def test_feed_registers_its_instance_id_on_the_runtime_identity():
    rt = OrchestrationRuntime()
    assert rt.identity.feed_instance_id is None
    feed = MarketFeedLoop(
        queue=rt.queue,
        symbols=["XAUUSD"],
        connector=object(),
        identity=rt.identity,
    )
    assert rt.identity.feed_instance_id == feed.identity.feed_instance_id
    assert rt.identity.feed_instance_id.startswith("feed-")


def test_second_feed_in_same_process_is_distinguishable():
    rt = OrchestrationRuntime()
    MarketFeedLoop(queue=rt.queue, symbols=["XAUUSD"], connector=object(), identity=rt.identity)
    # A duplicate worker would construct a second feed; it must not be silently
    # identical to the first.
    other = RuntimeIdentity("runtime")
    MarketFeedLoop(queue=rt.queue, symbols=["XAUUSD"], connector=object(), identity=other)
    assert rt.identity.feed_instance_id != other.feed_instance_id


# ----------------------------------------------------------------------
# Analysis log carries the identity
# ----------------------------------------------------------------------
class _FakeResult:
    status = "REJECTED"
    decision = "WAIT"
    error = None


class _FakePipeline:
    def run(self, event, context=None):  # noqa: D401 - duck-typed pipeline
        return _FakeResult()


def test_analysis_trace_carries_all_four_identity_fields():
    ident = RuntimeIdentity("runtime")
    ident.register_scheduler()
    ident.register_feed()

    scheduler = AutonomousScheduler(
        queue=EventQueue(),
        pipeline=_FakePipeline(),
        identity=ident,
    )
    scheduler.queue.enqueue(
        {"event_type": "BREAKOUT", "symbol": "XAUUSD", "event_id": "e1", "bar_time": "t1"}
    )
    processed = scheduler.process_available()
    assert processed == 1

    trace = scheduler.recent_event_traces(1)[0]
    assert trace["process_id"] == ident.process_id
    assert trace["runtime_instance_id"] == ident.runtime_instance_id
    assert trace["scheduler_instance_id"] == ident.scheduler_instance_id
    assert trace["feed_instance_id"] == ident.feed_instance_id


def test_scheduler_without_identity_still_logs_process_id():
    scheduler = AutonomousScheduler(queue=EventQueue(), pipeline=_FakePipeline())
    scheduler.queue.enqueue({"event_type": "BREAKOUT", "symbol": "XAUUSD", "event_id": "e2"})
    scheduler.process_available()
    trace = scheduler.recent_event_traces(1)[0]
    # Fail-safe fallback: process_id is still present, instance ids blank.
    assert trace["process_id"] == process_identity()["process_id"]
    assert trace["scheduler_instance_id"] == ""


def test_identity_is_json_serialisable():
    rt = OrchestrationRuntime()
    payload = json.dumps(rt.identity.to_dict())
    assert "runtime_instance_id" in payload
