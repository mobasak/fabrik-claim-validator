"""traditions — first-class peer-equal registry (§4.1)

Revision ID: 0001
Revises:
Create Date: 2026-05-03

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS traditions (
            code                    TEXT PRIMARY KEY,
            name_en                 TEXT NOT NULL,
            name_native             TEXT,
            primary_authority_url   TEXT NOT NULL,
            monograph_corpus_size   INT,
            ingestion_status        TEXT NOT NULL,
            evidence_weight_class   TEXT NOT NULL,
            primary_lang            TEXT NOT NULL,
            parent_tradition_id     TEXT REFERENCES traditions(code),
            independence_weight     REAL NOT NULL DEFAULT 1.0,
            evidence_tier_map       JSONB NOT NULL,
            last_indexed_at         TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT traditions_ingestion_status_chk
                CHECK (ingestion_status IN ('pending','partial','complete','data_acquisition_pending')),
            CONSTRAINT traditions_evidence_weight_class_chk
                CHECK (evidence_weight_class IN (
                    'regulatory_pharmacopoeia','academic_consensus',
                    'clinical_research','ethnobotanical_record'
                ))
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS traditions_parent_idx "
        "ON traditions(parent_tradition_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS traditions CASCADE;")
