"""Shared fixtures.

A module-scoped asyncpg pool reused across DB-backed tests, plus a
per-test cleanup that truncates the few tables Sprint 0 services touch.
Tests that need PG are skipped automatically when ``DATABASE_URL`` is
unset (mirrors ``test_migrations.py``).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

if os.getenv("DATABASE_URL"):
    import asyncpg

    from fabrik_claim_validator import db as db_module
else:  # pragma: no cover — no PG, fixtures will be skipped
    asyncpg = None  # type: ignore[assignment]
    db_module = None  # type: ignore[assignment]


_PG_REQUIRED = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — DB-backed tests need Postgres.",
)


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[object]:
    if db_module is None:
        pytest.skip("DATABASE_URL not set")
    p = await db_module.create_pool(min_size=1, max_size=2)
    try:
        # Reset state for the few Sprint 0 tables we exercise. Traditions
        # seed (FCV-002) is preserved — FK targets need to stay populated.
        async with p.acquire() as conn:
            await conn.execute(
                "TRUNCATE cache_entries, discovery_cache, ingest_log, "
                "proxy_budget, claim_evidence, claims, "
                "monographs, scrape_queue, "
                "taxa_aliases, compounds "
                "RESTART IDENTITY CASCADE"
            )
        yield p
    finally:
        await p.close()


pg_required = _PG_REQUIRED
