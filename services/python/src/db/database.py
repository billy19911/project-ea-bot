# -*- coding: utf-8 -*-
"""
Database engine, session factory, and lifecycle helpers for EA Bot Python service.

Uses SQLAlchemy 2.0 style with async support ready (switch to create_async_engine
if you prefer asyncpg). Currently uses synchronous psycopg2 for simplicity.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .base import Base

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL_PYTHON",
    "postgresql://ea_bot:changeme_dev@localhost:5432/ea_bot",
)

DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,  # set True for SQL logging during development
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    """
    Dependency-style generator for DB sessions.
    Usage (FastAPI / any context):
        with get_db() as db:
            db.query(...)
    Also usable as a context manager directly.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager that commits on success, rolls back on exception."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables defined in models/. Use Alembic for migrations in production."""
    Base.metadata.create_all(bind=engine)


def close_engine() -> None:
    """Dispose of the connection pool. Call at application shutdown."""
    engine.dispose()
