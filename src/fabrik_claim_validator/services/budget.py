"""Per-day proxy bandwidth accounting (FCV-010, plan §4.9).

Reads/writes ``proxy_budget`` rows. Hard-stop semantics: when
``bytes_consumed >= bytes_budget`` for the current UTC day, the next call to
``check_budget()`` raises ``ProxyBudgetExceeded`` and stamps ``hard_stopped_at``.

Budget is configured via ``PROXY_DAILY_BUDGET_BYTES`` env (default 5 GiB).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any

import asyncpg


class ProxyBudgetExceeded(RuntimeError):
    """Raised when the day's bandwidth budget is fully consumed."""


def _today() -> date:
    return datetime.now(tz=UTC).date()


def _default_budget() -> int:
    raw = os.getenv("PROXY_DAILY_BUDGET_BYTES", str(5 * 1024 * 1024 * 1024))
    try:
        return int(raw)
    except ValueError:
        return 5 * 1024 * 1024 * 1024


async def check_budget(pool: asyncpg.Pool) -> dict[str, Any]:
    """Return today's budget row; insert one with the env default if missing.

    Raises ``ProxyBudgetExceeded`` when the budget is fully consumed (and
    stamps ``hard_stopped_at`` the first time it crosses the line).
    """
    bucket = _today()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO proxy_budget (bucket_date, bytes_consumed, bytes_budget, request_count)
            VALUES ($1, 0, $2, 0)
            ON CONFLICT (bucket_date) DO UPDATE
              SET bytes_consumed = proxy_budget.bytes_consumed
            RETURNING bucket_date, bytes_consumed, bytes_budget, request_count, hard_stopped_at
            """,
            bucket,
            _default_budget(),
        )
    assert row is not None  # ON CONFLICT DO UPDATE always returns a row  # noqa: S101
    if row["bytes_consumed"] >= row["bytes_budget"]:
        if row["hard_stopped_at"] is None:
            await _stamp_hard_stop(pool, bucket)
        raise ProxyBudgetExceeded(
            f"daily budget exhausted: "
            f"{row['bytes_consumed']}/{row['bytes_budget']} bytes on {bucket}"
        )
    return dict(row)


async def consume(pool: asyncpg.Pool, bytes_used: int) -> None:
    """Increment today's counters by one fetch's bandwidth."""
    bucket = _today()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO proxy_budget (bucket_date, bytes_consumed, bytes_budget, request_count)
            VALUES ($1, $2, $3, 1)
            ON CONFLICT (bucket_date) DO UPDATE
              SET bytes_consumed = proxy_budget.bytes_consumed + EXCLUDED.bytes_consumed,
                  request_count  = proxy_budget.request_count  + 1
            """,
            bucket,
            bytes_used,
            _default_budget(),
        )


async def _stamp_hard_stop(pool: asyncpg.Pool, bucket: date) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE proxy_budget SET hard_stopped_at = NOW() "
            "WHERE bucket_date = $1 AND hard_stopped_at IS NULL",
            bucket,
        )


async def status(pool: asyncpg.Pool) -> dict[str, Any]:
    """Return today's budget status (for ``/health/proxy_budget`` endpoint)."""
    bucket = _today()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT bucket_date, bytes_consumed, bytes_budget, request_count, "
            "hard_stopped_at FROM proxy_budget WHERE bucket_date = $1",
            bucket,
        )
    if row is None:
        return {
            "day": str(bucket),
            "bytes_consumed": 0,
            "bytes_budget": _default_budget(),
            "request_count": 0,
            "hard_stopped": False,
        }
    return {
        "day": str(row["bucket_date"]),
        "bytes_consumed": row["bytes_consumed"],
        "bytes_budget": row["bytes_budget"],
        "request_count": row["request_count"],
        "hard_stopped": row["hard_stopped_at"] is not None,
    }
