"""ingest_log — per-tradition fetch telemetry (§4.10)

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-03

"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ingest_log (
            id                  BIGSERIAL PRIMARY KEY,
            tradition_code      TEXT NOT NULL REFERENCES traditions(code),
            scraper_id          TEXT NOT NULL,
            worker_id           INT,
            proxy_used          TEXT,
            request_url         TEXT,
            http_status         INT,
            bytes_received      BIGINT,
            elapsed_ms          INT,
            captcha_solved      BOOLEAN NOT NULL DEFAULT FALSE,
            captcha_cost_ms     INT,
            error_class         TEXT,
            cassette_id         TEXT,
            occurred_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ingest_log_tradition_time "
        "ON ingest_log(tradition_code, occurred_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ingest_log CASCADE;")
