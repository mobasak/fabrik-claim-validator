"""taxa_aliases — fix NULL tradition_code uniqueness (FCV-251)

The original ``taxa_aliases_uniq`` index treats NULL ``tradition_code``
values as distinct (standard SQL NULL semantics), so seeds like ICTM
that have rows without a ``tradition_code`` duplicate on every re-run.

Replace the single index with two partial unique indexes:
  (a) tradition-scoped: UNIQUE(pubchem_cid, alias_name, alias_lang, tradition_code)
      WHERE tradition_code IS NOT NULL
  (b) null-tradition:   UNIQUE(pubchem_cid, alias_name, alias_lang)
      WHERE tradition_code IS NULL

This makes ON CONFLICT work correctly for both NULL and non-NULL
tradition codes.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-03

"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicate null-tradition rows before creating the stricter index.
    # Keep only the earliest (lowest id) row for each (pubchem_cid, alias_name,
    # alias_lang) group where tradition_code IS NULL.
    op.execute(
        """
        DELETE FROM taxa_aliases a
        USING taxa_aliases b
        WHERE a.tradition_code IS NULL
          AND b.tradition_code IS NULL
          AND a.pubchem_cid IS NOT DISTINCT FROM b.pubchem_cid
          AND a.alias_name  = b.alias_name
          AND a.alias_lang  = b.alias_lang
          AND a.id > b.id;
        """
    )

    # Drop the old index that couldn't handle NULLs.
    op.execute("DROP INDEX IF EXISTS taxa_aliases_uniq;")

    # (a) Tradition-scoped rows — standard 4-column unique.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS taxa_aliases_uniq_with_tradition "
        "ON taxa_aliases(pubchem_cid, alias_name, alias_lang, tradition_code) "
        "WHERE tradition_code IS NOT NULL;"
    )

    # (b) Null-tradition rows — 3-column unique (tradition is always NULL).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS taxa_aliases_uniq_null_tradition "
        "ON taxa_aliases(pubchem_cid, alias_name, alias_lang) "
        "WHERE tradition_code IS NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS taxa_aliases_uniq_null_tradition;")
    op.execute("DROP INDEX IF EXISTS taxa_aliases_uniq_with_tradition;")
    # Restore the original (broken) index.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS taxa_aliases_uniq "
        "ON taxa_aliases(pubchem_cid, alias_name, alias_lang, tradition_code);"
    )
