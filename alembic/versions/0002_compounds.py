"""compounds — PubChem-rooted compound identity (§4.2)

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-03

"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compounds (
            pubchem_cid             BIGINT PRIMARY KEY,
            canonical_name          TEXT NOT NULL,
            iupac_name              TEXT,
            inchi                   TEXT,
            inchi_key               TEXT UNIQUE,
            smiles                  TEXT,
            molecular_formula       TEXT,
            molecular_weight        REAL,
            cas_number              TEXT,
            is_botanical            BOOLEAN NOT NULL DEFAULT FALSE,
            taxon_canonical         TEXT,
            wfo_id                  TEXT,
            fetched_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS compounds_inchi_key_idx ON compounds(inchi_key);")
    op.execute("CREATE INDEX IF NOT EXISTS compounds_taxon_idx ON compounds(taxon_canonical);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compounds CASCADE;")
