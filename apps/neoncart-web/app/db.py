"""Postgres pool + query helpers for nc-web.

Lazy-initialised AsyncConnectionPool so the web app starts even if
Postgres isn't ready yet (it just 503s catalog requests until ready).

Schema lives in postgres/schema.sql and is loaded by the seed Job
during helm install.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None


def _dsn() -> str:
    host = os.getenv("POSTGRES_HOST")
    if not host:
        raise RuntimeError("POSTGRES_HOST not set")
    return (
        f"postgresql://{os.getenv('POSTGRES_USER', 'neoncart')}:"
        f"{os.getenv('POSTGRES_PASSWORD', '')}@{host}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'neoncart')}"
    )


async def init_pool() -> None:
    """Open the connection pool on startup. Safe to call multiple times."""
    global _pool
    if _pool is not None:
        return
    if not os.getenv("POSTGRES_HOST"):
        log.warning("POSTGRES_HOST unset — DB queries will fail; catalog endpoints will 503")
        return
    _pool = AsyncConnectionPool(_dsn(), min_size=1, max_size=4, open=False)
    await _pool.open()
    log.info("Postgres pool open (host=%s)", os.getenv("POSTGRES_HOST"))


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Postgres pool not initialised")
    async with _pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            return await cur.fetchall()


async def fetchone(query: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = await fetch(query, params)
    return rows[0] if rows else None


async def execute(query: str, params: tuple = ()) -> None:
    if _pool is None:
        raise RuntimeError("Postgres pool not initialised")
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
        await conn.commit()


def pool_ready() -> bool:
    return _pool is not None
