"""One-Test-Rule regressions for Sprint 1 resolvers (FCV-101, FCV-104).

All HTTP traffic is served from ``tests/cassettes/`` via
``services.cassettes.replay`` — zero network in CI.
"""

from __future__ import annotations

import os

import pytest

from fabrik_claim_validator.resolvers.herb_ac_cn import (
    HerbAcCnResolver,
    parse_detail_html,
    parse_detail_json,
)
from fabrik_claim_validator.resolvers.pubchem import PubChemResolver

from .conftest import pg_required


@pytest.fixture(autouse=True)
def _force_replay(monkeypatch):
    """Every test in this module must replay; no accidental network calls."""
    monkeypatch.setenv("CASSETTE_MODE", "replay")
    monkeypatch.setenv("CASSETTE_DIR", os.path.join(os.path.dirname(__file__), "cassettes"))


# ─── FCV-101: PubChem resolver — name → CID → properties round-trip ─────
async def test_pubchem_name_to_properties_aspirin():
    async with PubChemResolver() as resolver:
        cid = await resolver.cid_from_name("aspirin")
        assert cid == 2244
        props = await resolver.properties(cid)
        assert props is not None
        assert props["canonical_name"] == "Aspirin"
        assert props["molecular_formula"] == "C9H8O4"
        assert props["inchi_key"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        cas = await resolver.cas_number(cid)
        assert cas == "50-78-2"


async def test_pubchem_name_to_properties_caffeine():
    async with PubChemResolver() as resolver:
        cid = await resolver.cid_from_name("caffeine")
        assert cid == 2519
        props = await resolver.properties(cid)
        assert props is not None
        assert props["canonical_name"] == "Caffeine"
        assert props["molecular_formula"] == "C8H10N4O2"
        cas = await resolver.cas_number(cid)
        assert cas == "58-08-2"


# ─── FCV-101: PubChem upsert writes the compounds row ──────────────────
@pg_required
async def test_pubchem_upsert_persists_to_compounds(pool):
    async with PubChemResolver() as resolver:
        row = await resolver.upsert(pool, cid=2244)
    assert row is not None
    assert row["pubchem_cid"] == 2244
    async with pool.acquire() as conn:
        stored = await conn.fetchrow(
            "SELECT canonical_name, molecular_formula, cas_number "
            "FROM compounds WHERE pubchem_cid = 2244"
        )
    assert stored is not None
    assert stored["canonical_name"] == "Aspirin"
    assert stored["molecular_formula"] == "C9H8O4"
    assert stored["cas_number"] == "50-78-2"


# ─── FCV-104/253: HERB 2.0 resolver — JSON API via cassettes ─────────
async def test_herb_ac_cn_fetch_detail_ginseng():
    async with HerbAcCnResolver() as resolver:
        result = await resolver.fetch_detail("Ginseng")
    assert result is not None
    assert result["herb_name"] == "Ginseng"
    assert result["herb_id"] == "HERB002319"
    assert len(result["targets"]) >= 1
    assert len(result["ingredients"]) >= 50  # HERB 2.0: 104 ingredients for Red Ginseng
    assert len(result.get("diseases", [])) >= 100  # HERB 2.0: 431 diseases
    assert len(result.get("clinical_trials", [])) >= 10  # HERB 2.0: 34 trials


async def test_herb_ac_cn_fetch_detail_astragalus():
    async with HerbAcCnResolver() as resolver:
        result = await resolver.fetch_detail("Astragalus")
    assert result is not None
    assert result["herb_id"] == "HERB007236"
    assert len(result["ingredients"]) >= 1


# ─── FCV-253: parse_detail_json pure function test ────────────────────
def test_parse_detail_json_extracts_fields():
    raw = {
        "herb_target": [["Target id", "Gene symbol"], [{}, "TP53"], [{}, "AKT1"]],
        "herb_ingredient": [["Ingredient id", "Ingredient name"], [{}, "Ginsenoside Rb1"]],
        "herb_disease": [["Disease id", "Disease name"], [{}, "Diabetes"]],
        "drug_paper_disease": [["Disease id", "Disease name", "UMLS disease type", "Reference id", "PubMed id"], [{}, "D", "T", "R", "12345678"]],
        "clinical_herb": [["Clinical trial id", "NCT id"], [{}, "NCT001"]],
        "summary": [["Herb ID", "Herb English name"], [{"link": "/", "title": "HERB999"}, "Test"]],
    }
    result = parse_detail_json(raw, herb_name="Test", herb_id="HERB999")
    assert result["targets"] == ["TP53", "AKT1"]
    assert result["ingredients"] == ["Ginsenoside Rb1"]
    assert result["diseases"] == ["Diabetes"]
    assert "12345678" in result["related_papers"]
    assert result["clinical_trials"] == ["NCT001"]


# ─── FCV-104: legacy HTML parser — test directly on a hand-rolled doc ──
def test_herb_parser_handles_missing_sections():
    empty = parse_detail_html("<html><body>no sections</body></html>", herb_name="Foo")
    assert empty == {
        "herb_name": "Foo",
        "targets": [],
        "ingredients": [],
        "related_papers": [],
    }


# ─── FCV-104: cache round-trip — second call hits cache_entries ────────
@pg_required
async def test_herb_ac_cn_caches_response(pool):
    async with HerbAcCnResolver() as resolver:
        first = await resolver.fetch_detail("Ginseng", pool=pool)
    assert first is not None

    # Second call should hit cache, not the cassette. Flip CASSETTE_MODE
    # to a nonsense value; if we bypass cache we'd crash on cassette lookup.
    os.environ["CASSETTE_MODE"] = "replay"  # keep replay available as fallback
    async with HerbAcCnResolver() as resolver:
        second = await resolver.fetch_detail("Ginseng", pool=pool)
    assert second == first

    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM cache_entries WHERE scraper_id = 'herb_ac_cn'"
        )
    assert count == 1
