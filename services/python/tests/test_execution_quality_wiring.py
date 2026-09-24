from execution import ExecutionEngine, OrderRequest


def test_simulated_execution_records_quality():
    import src.system.v2_endpoints as v2

    v2._execution_quality = None
    engine = ExecutionEngine(mt5_connector=None, simulation_mode=True)
    result = engine.execute_order(
        OrderRequest(
            symbol="EURUSD", order_type="BUY", volume=0.1, price=1.08, idempotency_key="quality-ok"
        )
    )
    assert result.success is True
    records = v2.get_execution_quality().records()
    assert len(records) == 1
    assert records[0].rejected is False
    assert records[0].requested_entry == 1.08


def test_rejected_execution_records_quality():
    import src.system.v2_endpoints as v2

    v2._execution_quality = None
    engine = ExecutionEngine(mt5_connector=None, simulation_mode=True, require_approval=True)
    result = engine.execute_order(
        OrderRequest(
            symbol="EURUSD",
            order_type="BUY",
            volume=0.1,
            price=1.08,
            idempotency_key="quality-reject",
        )
    )
    assert result.success is False
    records = v2.get_execution_quality().records()
    assert len(records) == 1
    assert records[0].rejected is True


def test_execution_quality_failure_never_breaks_execution(monkeypatch):
    import src.system.v2_endpoints as v2

    class Broken:
        def record(self, record):
            raise RuntimeError("analytics unavailable")

    monkeypatch.setattr(v2, "get_execution_quality", lambda: Broken())
    engine = ExecutionEngine(mt5_connector=None, simulation_mode=True)
    result = engine.execute_order(
        OrderRequest(
            symbol="EURUSD",
            order_type="BUY",
            volume=0.1,
            price=1.08,
            idempotency_key="quality-broken",
        )
    )
    assert result.success is True
