"""Persistent scraper cache backed by ``cache_entries`` (FCV-003, plan §4.7).

Default TTL is 90 days. Sweeper deletes expired rows in batches; intended to
run as a daily background asyncio task.

Keys are produced by ``make_key(scraper_id, payload)`` — a stable sha256 over
the canonicalised JSON payload — so callers do not have to worry about dict
ordering when constructing them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

DEFAULT_TTL = timedelta(days=90)


def make_key(scraper_id: str, payload: dict[str, Any]) -> str:
    """Build a stable cache key from scraper id + canonical JSON payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{scraper_id}|{canonical}".encode()).hexdigest()
    return f"{scraper_id}:{digest}"


async def get(pool: asyncpg.Pool, key: str, *, scraper_id: str) -> dict[str, Any] | None:
    """Return cached response or None if missing / expired.

    Increments ``hit_count`` on hit. ``scraper_id`` is matched defensively
    in addition to the key so a key collision across scrapers can never
    return a wrong-tradition response.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE cache_entries
               SET hit_count = hit_count + 1
             WHERE cache_key = $1
               AND scraper_id = $2
               AND expires_at > NOW()
            RETURNING response_payload
            """,
            key,
            scraper_id,
        )
    if row is None:
        return None
    raw = row["response_payload"]
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


async def set(  # noqa: A001  (shadowing builtin is intentional — module-level API)
    pool: asyncpg.Pool,
    key: str,
    *,
    scraper_id: str,
    query_payload: dict[str, Any],
    response_payload: dict[str, Any],
    ttl: timedelta = DEFAULT_TTL,
    upstream_etag: str | None = None,
) -> None:
    """Insert-or-update a cache row. ON CONFLICT bumps ``fetched_at`` + ``expires_at``."""
    expires = datetime.now(tz=UTC) + ttl
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO cache_entries
                (cache_key, scraper_id, query_payload, response_payload,
                 upstream_etag, fetched_at, expires_at, hit_count)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, NOW(), $6, 0)
            ON CONFLICT (cache_key) DO UPDATE
              SET response_payload = EXCLUDED.response_payload,
                  upstream_etag    = EXCLUDED.upstream_etag,
                  fetched_at       = NOW(),
                  expires_at       = EXCLUDED.expires_at
            """,
            key,
            scraper_id,
            json.dumps(query_payload),
            json.dumps(response_payload),
            upstream_etag,
            expires,
        )


async def invalidate_scraper(pool: asyncpg.Pool, scraper_id: str) -> int:
    """Wipe every row for a scraper. Returns row count deleted."""
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM cache_entries WHERE scraper_id = $1", scraper_id)
    # asyncpg returns "DELETE N"
    return int(result.split()[-1]) if result else 0


async def sweep_expired(pool: asyncpg.Pool, batch_size: int = 1000) -> int:
    """Delete expired rows in one batch. Returns row count deleted.

    Intended to run on a ~24h cadence from a background asyncio task.
    """
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM cache_entries
             WHERE cache_key IN (
                 SELECT cache_key FROM cache_entries
                  WHERE expires_at <= NOW()
                  LIMIT $1
             )
            """,
            batch_size,
        )
    return int(result.split()[-1]) if result else 0
