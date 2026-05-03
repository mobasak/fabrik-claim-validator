"""proxy_budget — per-day bandwidth accounting (§4.9)

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-03

"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS proxy_budget (
            bucket_date             DATE PRIMARY KEY,
            bytes_consumed          BIGINT NOT NULL DEFAULT 0,
            bytes_budget            BIGINT NOT NULL,
            request_count           BIGINT NOT NULL DEFAULT 0,
            hard_stopped_at         TIMESTAMPTZ
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS proxy_budget CASCADE;")
