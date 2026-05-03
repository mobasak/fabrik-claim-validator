"""discovery_cache — short-TTL convergence-query cache (§4.8)

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-03

Separate table from cache_entries because discovery answers invalidate the
instant a new monograph for that indication arrives (invalidated_by_ingest).
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_cache (
            cache_key               TEXT PRIMARY KEY,
            indication              TEXT NOT NULL,
            request_payload         JSONB NOT NULL,
            response_payload        JSONB NOT NULL,
            computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at              TIMESTAMPTZ NOT NULL,
            invalidated_by_ingest   BOOLEAN NOT NULL DEFAULT FALSE
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS discovery_cache_indication_idx "
        "ON discovery_cache(indication);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS discovery_cache_expires_idx "
        "ON discovery_cache(expires_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS discovery_cache CASCADE;")
