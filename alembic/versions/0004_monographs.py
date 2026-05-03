"""monographs — per-tradition monograph entries (§4.4)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-03

"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS monographs (
            id                            BIGSERIAL PRIMARY KEY,
            tradition_code                TEXT NOT NULL REFERENCES traditions(code),
            source_id                     TEXT NOT NULL,
            monograph_native_id           TEXT NOT NULL,
            pubchem_cid                   BIGINT REFERENCES compounds(pubchem_cid),
            taxon_canonical               TEXT,
            title_native                  TEXT,
            title_en                      TEXT,
            monograph_lang                TEXT NOT NULL,
            monograph_script              TEXT,
            evidence_tier                 TEXT NOT NULL,
            indications_native            TEXT[],
            indications_normalized        TEXT[],
            preparations                  JSONB,
            contraindications_native      TEXT[],
            contraindications_normalized  TEXT[],
            full_text                     TEXT,
            full_text_translation         TEXT,
            source_url                    TEXT,
            page_refs                     JSONB,
            scraped_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            cassette_id                   TEXT,
            raw_response_hash             TEXT
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS monographs_tradition_idx ON monographs(tradition_code);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS monographs_pubchem_idx ON monographs(pubchem_cid);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS monographs_indications_gin "
        "ON monographs USING GIN (indications_normalized);"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS monographs_native_uniq "
        "ON monographs(tradition_code, source_id, monograph_native_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS monographs CASCADE;")
