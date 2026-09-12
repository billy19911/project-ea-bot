# -*- coding: utf-8 -*-
"""SQLAlchemy ORM models — initial set for EA Bot Python service."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# =============================================================================
# Enums
# =============================================================================


class Role(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"


class Side(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
    TRAILING_STOP = "TRAILING_STOP"


class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PARTIAL = "PARTIAL"
    LIQUIDATED = "LIQUIDATED"


class StrategyType(str, enum.Enum):
    TREND_FOLLOWING = "TREND_FOLLOWING"
    MEAN_REVERSION = "MEAN_REVERSION"
    SCALPING = "SCALPING"
    GRID = "GRID"
    ARBITRAGE = "ARBITRAGE"
    MARKET_MAKING = "MARKET_MAKING"
    CUSTOM = "CUSTOM"


class AgentRunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    PAUSED = "PAUSED"


class AuditSeverity(str, enum.Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# =============================================================================
# Models
# =============================================================================


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: None)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[Role] = mapped_column(
        Enum(Role, create_type=False), default=Role.USER, nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    accounts: Mapped[list["Account"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    strategies: Mapped[list["Strategy"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship(  # type: ignore[attr-defined]
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(  # type: ignore[attr-defined]
        back_populates="user", lazy="selectin"
    )


class Account(Base):
    __tablename__ = "account"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: None)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)  # encrypted
    api_secret: Mapped[str] = mapped_column(String(512), nullable=False)  # encrypted
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    balance: Mapped[Optional[float]] = mapped_column(Numeric(20, 8), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), default="USDT", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="accounts")
    positions: Mapped[list["Position"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", lazy="selectin"
    )
    trades: Mapped[list["Trade"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", lazy="selectin"
    )
    orders: Mapped[list["Order"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("ix_account_user_provider", "user_id", "provider"),)


class Trade(Base):
    __tablename__ = "trade"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: None)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[Side] = mapped_column(Enum(Side, create_type=False), nullable=False)
    order_type: Mapped[OrderType] = mapped_column(
        Enum(OrderType, create_type=False), nullable=False
    )
    price: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    fee: Mapped[Optional[float]] = mapped_column(Numeric(20, 8), nullable=True)
    fee_asset: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    position_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("position.id", ondelete="SET NULL"), nullable=True, index=True
    )
    strategy_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("strategy.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("agent_run.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    account: Mapped["Account"] = relationship(back_populates="trades")
    position: Mapped[Optional["Position"]] = relationship(back_populates="trades")
    strategy: Mapped[Optional["Strategy"]] = relationship(back_populates="trades")
    agent_run: Mapped[Optional["AgentRun"]] = relationship(back_populates="trades")  # type: ignore[attr-defined]

    __table_args__ = (Index("ix_trade_account_time", "account_id", "trade_time"),)


class Position(Base):
    __tablename__ = "position"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: None)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[Side] = mapped_column(Enum(Side, create_type=False), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    current_price: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unrealized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(20, 8), nullable=True)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(20, 8), nullable=True)
    margin: Mapped[Optional[float]] = mapped_column(Numeric(20, 8), nullable=True)
    status: Mapped[PositionStatus] = mapped_column(
        Enum(PositionStatus, create_type=False), default=PositionStatus.OPEN, nullable=False
    )
    strategy_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("strategy.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("agent_run.id", ondelete="SET NULL"), nullable=True, index=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    account: Mapped["Account"] = relationship(back_populates="positions")
    trades: Mapped[list["Trade"]] = relationship(back_populates="position", lazy="selectin")

    __table_args__ = (
        Index(
            "ix_position_account_symbol_side",
            "account_id",
            "symbol",
            "side",
            unique=True,
        ),
        Index("ix_position_status", "status"),
    )


class Order(Base):
    __tablename__ = "order"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: None)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[Side] = mapped_column(Enum(Side, create_type=False), nullable=False)
    order_type: Mapped[OrderType] = mapped_column(
        Enum(OrderType, create_type=False), nullable=False
    )
    price: Mapped[Optional[float]] = mapped_column(Numeric(20, 8), nullable=True)
    stop_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 8), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    filled_qty: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, create_type=False), default=OrderStatus.NEW, nullable=False
    )
    strategy_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("strategy.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("agent_run.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    account: Mapped["Account"] = relationship(back_populates="orders")
    strategy: Mapped[Optional["Strategy"]] = relationship(back_populates="orders")  # type: ignore[attr-defined]
    agent_run: Mapped[Optional["AgentRun"]] = relationship(back_populates="orders")  # type: ignore[attr-defined]

    __table_args__ = (
        Index("ix_order_account_symbol", "account_id", "symbol"),
        Index("ix_order_status", "status"),
    )


class Strategy(Base):
    __tablename__ = "strategy"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: None)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type: Mapped[StrategyType] = mapped_column(
        Enum(StrategyType, create_type=False), nullable=False
    )
    config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_paper_trading: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="strategies")
    agent_runs: Mapped[list["AgentRun"]] = relationship(  # type: ignore[attr-defined]
        back_populates="strategy", cascade="all, delete-orphan", lazy="selectin"
    )
    orders: Mapped[list["Order"]] = relationship(  # type: ignore[attr-defined]
        back_populates="strategy", lazy="selectin"
    )
    trades: Mapped[list["Trade"]] = relationship(  # type: ignore[attr-defined]
        back_populates="strategy", lazy="selectin"
    )

    __table_args__ = (Index("ix_strategy_user_name", "user_id", "name", unique=True),)


class AgentRun(Base):
    __tablename__ = "agent_run"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: None)
    strategy_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("strategy.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, create_type=False), default=AgentRunStatus.RUNNING, nullable=False
    )
    input_params: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="agent_runs")  # type: ignore[attr-defined]
    strategy: Mapped[Optional["Strategy"]] = relationship(  # type: ignore[attr-defined]
        back_populates="agent_runs"
    )
    agent_outputs: Mapped[list["AgentOutput"]] = relationship(  # type: ignore[attr-defined]
        back_populates="agent_run", cascade="all, delete-orphan", lazy="selectin"
    )
    trades: Mapped[list["Trade"]] = relationship(  # type: ignore[attr-defined]
        back_populates="agent_run", lazy="selectin"
    )
    orders: Mapped[list["Order"]] = relationship(  # type: ignore[attr-defined]
        back_populates="agent_run", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_agent_run_status", "status"),
        Index("ix_agent_run_started", "started_at"),
    )


class AgentOutput(Base):
    __tablename__ = "agent_output"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: None)
    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    suggested_trade: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    metrics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON

    # Relationships
    agent_run: Mapped["AgentRun"] = relationship(  # type: ignore[attr-defined]
        back_populates="agent_outputs"
    )

    __table_args__ = (Index("ix_agent_output_run_timestamp", "agent_run_id", "timestamp"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: None)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[AuditSeverity] = mapped_column(
        Enum(AuditSeverity, create_type=False), default=AuditSeverity.INFO, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False, index=True
    )

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")  # type: ignore[attr-defined]

    __table_args__ = (
        Index("ix_audit_user_created", "user_id", "created_at"),
        Index("ix_audit_action", "action"),
    )
