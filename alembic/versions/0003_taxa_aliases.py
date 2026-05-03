"""taxa_aliases — cross-tradition plant name aliases (§4.3)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-03

"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS taxa_aliases (
            id                      BIGSERIAL PRIMARY KEY,
            pubchem_cid             BIGINT REFERENCES compounds(pubchem_cid),
            alias_name              TEXT NOT NULL,
            alias_lang              TEXT NOT NULL,
            alias_script            TEXT,
            tradition_code          TEXT REFERENCES traditions(code),
            alias_type              TEXT NOT NULL,
            source                  TEXT NOT NULL,
            source_record_id        TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT taxa_aliases_alias_type_chk
                CHECK (alias_type IN (
                    'common','pharmacopoeial','pinyin',
                    'romanized','scientific_synonym','legacy'
                ))
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS taxa_aliases_uniq "
        "ON taxa_aliases(pubchem_cid, alias_name, alias_lang, tradition_code);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS taxa_aliases_alias_lower "
        "ON taxa_aliases(LOWER(alias_name));"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS taxa_aliases CASCADE;")
