"""claim_evidence — evidence rows linking claims to monographs / RCTs (§4.6)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-03

Note: ``direction`` is a CHECK-constrained enum-like TEXT to enforce tri-state
at schema level (supports | contradicts | mixed | contextual | silent).
This is intentional per plan §4 — the aggregator CANNOT accidentally collapse
contextual/silent into supports/contradicts.
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS claim_evidence (
            id                  BIGSERIAL PRIMARY KEY,
            claim_id            BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
            tradition_code      TEXT NOT NULL REFERENCES traditions(code),
            evidence_type       TEXT NOT NULL,
            evidence_id         BIGINT,
            external_id         TEXT,
            verifier_response   JSONB,
            evidence_quality    TEXT NOT NULL,
            direction           TEXT NOT NULL,
            effect_size         JSONB,
            notes               TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT claim_evidence_evidence_type_chk
                CHECK (evidence_type IN (
                    'monograph','rct','meta_analysis','regulatory_assessment',
                    'case_series','in_vitro','animal'
                )),
            CONSTRAINT claim_evidence_direction_chk
                CHECK (direction IN ('supports','contradicts','mixed','contextual','silent')),
            CONSTRAINT claim_evidence_quality_chk
                CHECK (evidence_quality IN ('A','B','C'))
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS claim_evidence_claim_idx "
        "ON claim_evidence(claim_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS claim_evidence_tradition_idx "
        "ON claim_evidence(tradition_code);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS claim_evidence CASCADE;")
