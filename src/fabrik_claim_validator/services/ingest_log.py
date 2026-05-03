"""Per-fetch telemetry rows in ``ingest_log`` (FCV-010, plan §4.10).

Provides:

- ``record(...)`` — append-only insert of one fetch event.
- ``track_fetch(tradition_code, scraper_id)`` — async decorator that wraps
  a scraper call with timing + error classification + budget bookkeeping +
  ingest_log row + budget hard-stop pre-check.

The decorated coroutine MUST take ``pool`` as a kwarg and return a dict
with at least ``{bytes: int}``; any extra fields are passed through.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg

from . import budget


async def record(
    pool: asyncpg.Pool,
    *,
    tradition_code: str,
    scraper_id: str,
    worker_id: int | None = None,
    proxy_used: str | None = None,
    request_url: str | None = None,
    http_status: int | None = None,
    bytes_received: int | None = None,
    elapsed_ms: int | None = None,
    captcha_solved: bool = False,
    captcha_cost_ms: int | None = None,
    error_class: str | None = None,
    cassette_id: str | None = None,
) -> None:
    """Append one telemetry row. All fields except tradition+scraper optional."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ingest_log (
                tradition_code, scraper_id, worker_id, proxy_used,
                request_url, http_status, bytes_received, elapsed_ms,
                captcha_solved, captcha_cost_ms, error_class, cassette_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """,
            tradition_code,
            scraper_id,
            worker_id,
            proxy_used,
            request_url,
            http_status,
            bytes_received,
            elapsed_ms,
            captcha_solved,
            captcha_cost_ms,
            error_class,
            cassette_id,
        )


def track_fetch(
    tradition_code: str, scraper_id: str
) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[dict[str, Any]]]]:
    """Decorator: budget pre-check, time the call, record telemetry, consume budget.

    Wrapped function is invoked with the same args/kwargs and must return a
    dict containing at least ``{"bytes": int}``. Failures are recorded and
    re-raised — never swallowed.

    Usage:

    .. code-block:: python

        @track_fetch("tcm", "herb_ac_cn")
        async def fetch_herb(*, pool, herb_name):
            ...
            return {"bytes": len(body), "http_status": 200, "data": ...}
    """

    def decorator(
        fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> Callable[..., Awaitable[dict[str, Any]]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, pool: asyncpg.Pool, **kwargs: Any) -> dict[str, Any]:
            await budget.check_budget(pool)  # raises ProxyBudgetExceeded
            t0 = time.perf_counter()
            err_class: str | None = None
            result: dict[str, Any] = {}
            try:
                result = await fn(*args, pool=pool, **kwargs)
                return result
            except Exception as exc:
                err_class = type(exc).__name__
                raise
            finally:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                bytes_received = int(result.get("bytes", 0)) if result else 0
                await record(
                    pool,
                    tradition_code=tradition_code,
                    scraper_id=scraper_id,
                    request_url=result.get("request_url") if result else None,
                    http_status=result.get("http_status") if result else None,
                    bytes_received=bytes_received,
                    elapsed_ms=elapsed_ms,
                    error_class=err_class,
                )
                if bytes_received:
                    await budget.consume(pool, bytes_received)

        return wrapper

    return decorator
