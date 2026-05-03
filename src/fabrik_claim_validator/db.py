"""asyncpg connection pool — direct driver, no SQLAlchemy ORM.

Pool is created at FastAPI lifespan startup and stored on ``app.state.pool``.
Sibling pattern to ``fabrik-citation-verifier``.
"""

from __future__ import annotations

import os

import asyncpg


def _normalise_dsn(database_url: str) -> str:
    """Strip SQLAlchemy-style driver suffixes asyncpg does not understand."""
    return (
        database_url.replace("+asyncpg", "")
        .replace("+psycopg", "")
        .replace("postgresql://", "postgres://", 1)
    )


async def create_pool(
    database_url: str | None = None,
    min_size: int = 2,
    max_size: int = 10,
) -> asyncpg.Pool:
    """Create a fresh asyncpg pool. Caller is responsible for closing it.

    Args:
        database_url: DSN. If None, reads ``DATABASE_URL`` from env.
        min_size: pool minimum size.
        max_size: pool maximum size.
    """
    dsn = database_url or os.getenv("DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    return await asyncpg.create_pool(
        dsn=_normalise_dsn(dsn),
        min_size=min_size,
        max_size=max_size,
    )


async def ping(pool: asyncpg.Pool) -> bool:
    """Single ``SELECT 1`` round-trip — used by /health."""
    async with pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
    return bool(result == 1)
