"""Shared database access for Azure Functions API."""

import logging
import os
import time
from threading import Lock
from typing import Any, Callable, Optional, TypeVar

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

_engine: Optional[Engine] = None
_engine_lock = Lock()
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = Lock()
_T = TypeVar("_T")


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except ValueError:
        logging.warning("Ignoring invalid %s value", name)
        return default


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                url = os.environ.get("DATABASE_URL", "")
                if not url:
                    raise RuntimeError("DATABASE_URL environment variable is not configured")
                _engine = create_engine(
                    url,
                    pool_pre_ping=True,
                    pool_recycle=_positive_int_env("DB_POOL_RECYCLE_SECONDS", 240),
                    connect_args={"timeout": _positive_int_env("DB_LOGIN_TIMEOUT_SECONDS", 20)},
                )
    return _engine


def _discard_engine(engine: Engine) -> None:
    """Remove a failed pool without disposing a newer pool made by another request."""
    global _engine
    with _engine_lock:
        if _engine is engine:
            _engine = None
    engine.dispose()


def _run_read(operation: Callable[[Any], _T]) -> _T:
    """Run a read query, reconnecting after transient Azure SQL connection failures."""
    attempts = _positive_int_env("DB_CONNECT_ATTEMPTS", 3)
    for attempt in range(1, attempts + 1):
        engine = get_engine()
        try:
            with engine.connect() as conn:
                return operation(conn)
        except OperationalError:
            _discard_engine(engine)
            if attempt == attempts:
                raise
            delay = min(2 ** (attempt - 1), 4)
            logging.warning(
                "Azure SQL connection/query attempt %d/%d failed; retrying in %ds",
                attempt,
                attempts,
                delay,
                exc_info=True,
            )
            time.sleep(delay)
    raise RuntimeError("Database retry loop ended unexpectedly")


def query_all(sql: str, params: Optional[dict] = None) -> list[dict[str, Any]]:
    def load(conn):
        rows = conn.execute(text(sql), params or {}).mappings().all()
        return [dict(r) for r in rows]

    return _run_read(load)


def query_one(sql: str, params: Optional[dict] = None) -> Optional[dict[str, Any]]:
    def load(conn):
        row = conn.execute(text(sql), params or {}).mappings().first()
        return dict(row) if row else None

    return _run_read(load)


def cached(key: str, loader, ttl_seconds: int = 300):
    """Cache read-only results and use stale data during transient DB failures."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        value = loader()
    except OperationalError:
        if hit:
            logging.exception("Returning stale cached value after DB failure for %s", key)
            return hit[1]
        raise
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl_seconds, value)
    return value
