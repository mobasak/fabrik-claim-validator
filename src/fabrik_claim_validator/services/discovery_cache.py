"""Discovery-query cache backed by ``discovery_cache`` (FCV-004, plan §4.8).

Separate from ``services.cache`` because:

1. Default TTL is 24h, not 90d.
2. Rows can be invalidated *event-driven* by ``invalidate_by_indication`` —
   triggered whenever a new monograph for that indication is ingested. This
   prevents stale convergence answers after fresh data lands.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

DEFAULT_TTL = timedelta(hours=24)


def make_key(indication: str, payload: dict[str, Any]) -> str:
    """Stable cache key from indication + canonical JSON payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{indication}|{canonical}".encode()).hexdigest()
    return f"discover:{indication}:{digest}"


async def get(pool: asyncpg.Pool, key: str) -> dict[str, Any] | None:
    """Return cached response or None if missing / expired / invalidated.

    A row with ``invalidated_by_ingest=true`` is treated as a miss (and
    swept out below).
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT response_payload
              FROM discovery_cache
             WHERE cache_key = $1
               AND expires_at > NOW()
               AND invalidated_by_ingest = FALSE
            """,
            key,
        )
    if row is None:
        return None
    raw = row["response_payload"]
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


async def set(  # noqa: A001
    pool: asyncpg.Pool,
    key: str,
    *,
    indication: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    ttl: timedelta = DEFAULT_TTL,
) -> None:
    """Insert-or-update a discovery cache row (resets ``invalidated_by_ingest``)."""
    expires = datetime.now(tz=UTC) + ttl
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO discovery_cache
                (cache_key, indication, request_payload, response_payload,
                 computed_at, expires_at, invalidated_by_ingest)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, NOW(), $5, FALSE)
            ON CONFLICT (cache_key) DO UPDATE
              SET response_payload      = EXCLUDED.response_payload,
                  computed_at           = NOW(),
                  expires_at            = EXCLUDED.expires_at,
                  invalidated_by_ingest = FALSE
            """,
            key,
            indication,
            json.dumps(request_payload),
            json.dumps(response_payload),
            expires,
        )


async def invalidate_by_indication(pool: asyncpg.Pool, indication: str) -> int:
    """Mark every cache row for ``indication`` as stale. Returns row count."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE discovery_cache
               SET invalidated_by_ingest = TRUE
             WHERE indication = $1
               AND invalidated_by_ingest = FALSE
            """,
            indication,
        )
    return int(result.split()[-1]) if result else 0
