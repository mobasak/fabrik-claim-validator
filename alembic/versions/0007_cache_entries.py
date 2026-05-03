"""cache_entries — persistent scraper cache, 90d TTL (§4.7)

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-03

"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cache_entries (
            cache_key               TEXT PRIMARY KEY,
            scraper_id              TEXT NOT NULL,
            query_payload           JSONB NOT NULL,
            response_payload        JSONB NOT NULL,
            upstream_etag           TEXT,
            fetched_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at              TIMESTAMPTZ NOT NULL,
            hit_count               INT NOT NULL DEFAULT 0
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS cache_entries_scraper_idx ON cache_entries(scraper_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS cache_entries_expires_idx ON cache_entries(expires_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cache_entries CASCADE;")
