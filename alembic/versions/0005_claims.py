"""claims — canonical (substance, indication) atoms (§4.5)

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-03

"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS claims (
            id                      BIGSERIAL PRIMARY KEY,
            claim_hash              TEXT UNIQUE NOT NULL,
            pubchem_cid             BIGINT REFERENCES compounds(pubchem_cid),
            taxon_canonical         TEXT,
            indication_code         TEXT NOT NULL,
            mechanism               TEXT,
            endpoint                TEXT,
            dose_range              JSONB,
            population              JSONB,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS claims_pubchem_idx ON claims(pubchem_cid);")
    op.execute("CREATE INDEX IF NOT EXISTS claims_indication_idx ON claims(indication_code);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS claims CASCADE;")
