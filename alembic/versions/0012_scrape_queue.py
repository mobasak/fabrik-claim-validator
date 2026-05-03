"""scrape_queue — per-scraper URL queue with status tracking (Sprint 2)

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-03

Stores discovered URLs from listing scrapers (e.g. EMA HMPC herbal index).
Workers claim rows via UPDATE...RETURNING with status transitions:
pending → processing → done | failed.
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scrape_queue (
            id              BIGSERIAL PRIMARY KEY,
            scraper_id      TEXT NOT NULL,
            url             TEXT NOT NULL,
            priority        INT NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'pending',
            worker_id       INT,
            attempts        INT NOT NULL DEFAULT 0,
            max_attempts    INT NOT NULL DEFAULT 3,
            last_error      TEXT,
            metadata        JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            claimed_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            CONSTRAINT scrape_queue_status_chk
                CHECK (status IN ('pending','processing','done','failed'))
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS scrape_queue_scraper_status_idx "
        "ON scrape_queue(scraper_id, status, priority DESC);"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS scrape_queue_url_uniq "
        "ON scrape_queue(scraper_id, url);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scrape_queue CASCADE;")
