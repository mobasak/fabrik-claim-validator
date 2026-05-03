"""One-Test-Rule regressions for Sprint 1 loaders (FCV-102, FCV-103)."""

from __future__ import annotations

from pathlib import Path

from fabrik_claim_validator.loaders import ictm_seed, wfo_seed

from .conftest import pg_required

FIXTURES = Path(__file__).parent / "fixtures"


# ─── FCV-102: WFO TSV parser — accepted-only filter ────────────────────
def test_wfo_iter_accepted_rows_filters_synonyms():
    rows = wfo_seed.iter_accepted_rows(FIXTURES / "wfo_sample.tsv")
    # Fixture has 11 total; 2 synonyms → 9 accepted.
    assert len(rows) == 9
    assert all(r["taxonomicStatus"] == "Accepted" for r in rows)
    assert any(r["scientificName"] == "Panax ginseng" for r in rows)
    assert all(r["taxonID"].startswith("wfo-") for r in rows)


# ─── FCV-252: WFO loader suffix handling (Zenodo .json.zip, .json.gz) ───
def test_wfo_iter_accepted_json_zip_path():
    """Zenodo files are named plant_list_YYYY-MM.json.zip — suffix is .zip, not .json."""
    # Create a mock .json.zip file to verify the path detection works
    import zipfile
    import json

    mock_zip = FIXTURES / "mock_wfo.json.zip"
    mock_data = [
        {"wfo_id_s": "wfo-0000000001", "full_name_string_no_authors_plain_s": "Panax ginseng", "role_s": "accepted"},
        {"wfo_id_s": "wfo-0000000002", "full_name_string_no_authors_plain_s": "Astragalus membranaceus", "role_s": "synonym"},
    ]
    with zipfile.ZipFile(mock_zip, "w") as zf:
        zf.writestr("plant_list.json", json.dumps(mock_data).encode("utf-8"))

    try:
        rows = wfo_seed.iter_accepted_rows(mock_zip)
        assert len(rows) == 1
        assert rows[0]["scientificName"] == "Panax ginseng"
    finally:
        mock_zip.unlink()


def test_wfo_iter_accepted_json_gz_path():
    """Zenodo also serves .json.gz files — suffix is .gz."""
    import gzip
    import json

    mock_gz = FIXTURES / "mock_wfo.json.gz"
    mock_data = [
        {"wfo_id_s": "wfo-0000000001", "full_name_string_no_authors_plain_s": "Panax ginseng", "role_s": "accepted"},
    ]
    with gzip.open(mock_gz, "wb") as f:
        f.write(json.dumps(mock_data).encode("utf-8"))

    try:
        rows = wfo_seed.iter_accepted_rows(mock_gz)
        assert len(rows) == 1
        assert rows[0]["scientificName"] == "Panax ginseng"
    finally:
        mock_gz.unlink()


# ─── FCV-102: WFO loader end-to-end ─────────────────────────────────────
@pg_required
async def test_wfo_seed_load_persists_accepted_taxa(pool):
    result = await wfo_seed.load(pool, FIXTURES / "wfo_sample.tsv")
    assert result["seen"] == 9
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM compounds WHERE is_botanical = TRUE "
            "AND wfo_id IS NOT NULL"
        )
        ginseng = await conn.fetchrow(
            "SELECT canonical_name, wfo_id, is_botanical FROM compounds "
            "WHERE canonical_name = 'Panax ginseng'"
        )
    assert count == 9
    assert ginseng is not None
    assert ginseng["is_botanical"] is True
    assert ginseng["wfo_id"] == "wfo-0000000001"


# ─── FCV-103: ICTM loader coverage — ≥8 langs + ginseng hits 6 target langs ─
@pg_required
async def test_ictm_seed_covers_required_languages_and_ginseng_aliases(pool):
    result = await ictm_seed.load(pool, FIXTURES / "ictm_sample.json")
    assert result["entries"] == 2
    # DoD: ≥ 8 distinct alias languages across the seed.
    assert result["langs_seen"] >= 8

    async with pool.acquire() as conn:
        distinct_langs = await conn.fetchval(
            "SELECT count(DISTINCT alias_lang) FROM taxa_aliases WHERE source = 'ictm'"
        )
        ginseng_langs = await conn.fetch(
            """
            SELECT DISTINCT ta.alias_lang
              FROM taxa_aliases ta
              JOIN compounds c ON c.pubchem_cid = ta.pubchem_cid
             WHERE c.canonical_name = 'Panax ginseng'
            """
        )
    assert distinct_langs >= 8
    # Ginseng must carry aliases in each target language required by §5 of the plan.
    langs = {row["alias_lang"] for row in ginseng_langs}
    assert {"zh", "ja", "ko", "ru", "en", "ar"}.issubset(langs)


# ─── FCV-103 + FCV-251: re-running the loader is fully idempotent ─────
#
# Migration 0013 (FCV-251) replaces the single taxa_aliases_uniq index
# with two partial unique indexes — one for tradition-scoped rows, one
# for null-tradition rows.  Both paths now use ON CONFLICT DO NOTHING,
# so re-runs produce zero net new rows regardless of NULL tradition_code.
@pg_required
async def test_ictm_seed_idempotent_for_tradition_scoped_rows(pool):
    first = await ictm_seed.load(pool, FIXTURES / "ictm_sample.json")
    second = await ictm_seed.load(pool, FIXTURES / "ictm_sample.json")
    assert first["aliases_inserted"] == second["aliases_inserted"]
    async with pool.acquire() as conn:
        # Tradition-scoped rows (tradition_code IS NOT NULL) must be stable.
        tradition_rows = await conn.fetchval(
            "SELECT count(*) FROM taxa_aliases "
            "WHERE source = 'ictm' AND tradition_code IS NOT NULL"
        )
        # Null-tradition rows are now properly deduped (FCV-251 fix).
        null_rows = await conn.fetchval(
            "SELECT count(*) FROM taxa_aliases "
            "WHERE source = 'ictm' AND tradition_code IS NULL"
        )
    # 8 tradition-scoped + 4 null-tradition = 12 total; second run dedupes all.
    assert tradition_rows == 8
    assert null_rows == 4
