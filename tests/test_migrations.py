"""Migration round-trip test — covers FCV-001 + FCV-002 DoD.

Exercises the "highest-risk" behaviour of this sprint: that every migration
has a working inverse AND the traditions seed is valid against the schema's
FK + CHECK constraints (so the aggregator's SQL joins in Sprint 5 can rely
on the data shape).

Runs against the WSL dev database when ``DATABASE_URL`` is set; skipped
otherwise (e.g. pure unit CI without PG). This matches the One-Test Rule:
one test, highest risk reduction for the ticket.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — migration tests require Postgres.",
)


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_migrations_round_trip_and_seed_is_valid() -> None:
    # 1. Fresh downgrade to base (clean slate for reproducibility).
    down = _run_alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr

    # 2. Full upgrade must succeed.
    up = _run_alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr

    # 3. Schema + seed assertions via psycopg directly (sync).
    import psycopg  # imported here so the file imports cleanly without PG

    dsn = os.environ["DATABASE_URL"]
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    if dsn.startswith("postgresql+psycopg://"):
        dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # 10 schema tables (+ alembic_version) = 11
        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname='public' ORDER BY tablename"
        )
        tables = {r[0] for r in cur.fetchall()}
        expected = {
            "alembic_version",
            "cache_entries",
            "claim_evidence",
            "claims",
            "compounds",
            "discovery_cache",
            "ingest_log",
            "monographs",
            "proxy_budget",
            "taxa_aliases",
            "traditions",
        }
        assert tables == expected, f"table set mismatch: {tables ^ expected}"

        # 12 traditions seeded (11 core + nhpid).
        cur.execute("SELECT count(*) FROM traditions")
        assert cur.fetchone()[0] == 12

        # Parent-tradition FKs resolve: kampo/dong_y -> tcm, tpm -> unani.
        cur.execute(
            "SELECT code, parent_tradition_id, independence_weight "
            "FROM traditions WHERE parent_tradition_id IS NOT NULL "
            "ORDER BY code"
        )
        children = cur.fetchall()
        assert ("dong_y", "tcm", 0.4) in children
        assert ("kampo", "tcm", 0.4) in children
        assert ("tpm", "unani", 0.4) in children

        # tri-state direction CHECK constraint must reject invalid values.
        # We need a claim first (FK). Use a throwaway one and rollback.
        cur.execute(
            "INSERT INTO claims (claim_hash, indication_code) "
            "VALUES ('test-hash-xyz', 'X99') RETURNING id"
        )
        claim_id = cur.fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO claim_evidence "
                "(claim_id, tradition_code, evidence_type, evidence_quality, direction) "
                "VALUES (%s, 'tcm', 'monograph', 'A', 'INVALID_DIRECTION')",
                (claim_id,),
            )
        conn.rollback()
