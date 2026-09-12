"""Tests for the MT5 connection layer."""

from mt5._connector_base import MT5Config, MT5Connector, MT5Error, MT5Health
from mt5.connection_manager import ConnectionState, MT5ConnectionManager

# -- MT5Connector -----------------------------------------------------------


class TestMT5Config:
    def test_defaults(self):
        cfg = MT5Config()
        assert cfg.terminal_path == ""
        assert cfg.login == 0
        assert cfg.password == ""
        assert cfg.server == ""
        assert cfg.timeout_ms == 5000
        assert cfg.max_retries == 3
        assert cfg.retry_delay_s == 1.0


class TestMT5Health:
    def test_default_disconnected(self):
        h = MT5Health()
        assert h.connected is False
        assert h.authenticated is False
        assert h.error is None


# -- MT5Connector lifecycle -------------------------------------------------


class TestMT5ConnectorInit:
    def test_connector_creates(self):
        cfg = MT5Config(login=12345, password="test", server="Demo")
        connector = MT5Connector(cfg)
        assert connector.last_error is None

    def test_connector_returns_config(self):
        cfg = MT5Config(terminal_path="C:\\MT5", login=1, password="pw", server="Server")
        connector = MT5Connector(cfg)
        assert connector._config.terminal_path == "C:\\MT5"
        assert connector._config.login == 1


# -- MT5ConnectionManager ---------------------------------------------------


class TestMT5ConnectionManagerInit:
    def test_default_state(self):
        mgr = MT5ConnectionManager()
        assert mgr.state == ConnectionState.DISCONNECTED
        assert mgr.stats.total_connections == 0
        assert mgr.stats.failed_attempts == 0
        assert mgr.stats.consecutive_failures == 0

    def test_custom_config(self):
        cfg = MT5Config(login=99999, password="secret", server="CustomServer")
        mgr = MT5ConnectionManager(cfg)
        assert mgr._config.login == 99999
        assert mgr._config.server == "CustomServer"

    def test_auto_reconnect_default(self):
        mgr = MT5ConnectionManager()
        assert mgr._auto_reconnect is True

    def test_auto_reconnect_disabled(self):
        mgr = MT5ConnectionManager(auto_reconnect=False)
        assert mgr._auto_reconnect is False

    def test_max_consecutive_failures(self):
        mgr = MT5ConnectionManager(max_consecutive_failures=10)
        assert mgr._max_failures == 10


# -- connection_manager stats recording -------------------------------------


class TestStatsRecording:
    def test_record_failure_increments(self):
        mgr = MT5ConnectionManager()
        mgr._record_failure(MT5Error(100, "test error", "op"))
        assert mgr.stats.failed_attempts == 1
        assert mgr.stats.consecutive_failures == 1
        assert mgr.stats.last_error is not None
        assert mgr.stats.last_error.code == 100

    def test_record_failure_string(self):
        mgr = MT5ConnectionManager()
        mgr._record_failure("some string error")
        assert mgr.stats.failed_attempts == 1
        assert mgr.stats.consecutive_failures == 1

    def test_record_failure_none(self):
        mgr = MT5ConnectionManager()
        mgr._record_failure(None)
        assert mgr.stats.failed_attempts == 1
        assert mgr.stats.consecutive_failures == 1
        assert mgr.stats.last_error.message == "unknown error"


# -- integration: import check ----------------------------------------------


class TestImports:
    def test_connector_importable(self):
        from mt5._connector_base import MT5Config, MT5Connector, MT5Error, MT5Health  # noqa: F401

    def test_connection_manager_importable(self):
        from mt5.connection_manager import ConnectionState, MT5ConnectionManager  # noqa: F401

    def test_package_exports(self):
        from mt5 import ConnectionState, MT5ConnectionManager, MT5Connector  # noqa: F401
