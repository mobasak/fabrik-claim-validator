"""Sprint 2 scraper tests (FCV-201, FCV-202, FCV-203).

Covers:
- EMA HMPC listing scrape → queue insertion.
- EMA HMPC detail parser → monograph extraction.
- NHPID product scrape → filtered monograph insertion.

All tests use cassette replay mode (no network).
DB-backed tests require DATABASE_URL.
"""

from __future__ import annotations

import os

import pytest

from fabrik_claim_validator.scrapers.ema_hmpc import (
    EmaHmpcScraper,
    _split_list_items,
    _strip_html,
)
from fabrik_claim_validator.scrapers.nhpid import NhpidScraper

# Force cassette replay for all tests in this module.
os.environ.setdefault("CASSETTE_MODE", "replay")


# ─── Unit tests (no DB) ───────────────────────────────────────


class TestHtmlHelpers:
    """Test HTML parsing helpers."""

    def test_strip_html_removes_tags(self) -> None:
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_strip_html_collapses_whitespace(self) -> None:
        assert _strip_html("<p>  foo   bar  </p>") == "foo bar"

    def test_split_list_items_semicolons(self) -> None:
        result = _split_list_items("item one; item two; item three")
        assert result == ["item one", "item two", "item three"]

    def test_split_list_items_bullets(self) -> None:
        result = _split_list_items("•first•second•third")
        assert result == ["first", "second", "third"]


class TestEmaMonographExtraction:
    """Test EMA monograph HTML parsing logic."""

    def test_extract_valerian(self) -> None:
        html = (
            "<html><body><h1>Valerianae radix - Valerian root</h1>"
            "<div><h2>Therapeutic indications</h2>"
            "<p>Well-established use: Relief of mild nervous tension and sleep disorders.</p>"
            "<h2>Contraindications</h2>"
            "<p>Hypersensitivity to the active substance; Children under 12 years.</p>"
            "<h2>Pharmaceutical form</h2>"
            "<p>Herbal tea; Dry extract; Tincture.</p></div></body></html>"
        )
        scraper = EmaHmpcScraper.__new__(EmaHmpcScraper)
        result = scraper._extract_monograph_data(html, "https://example.com/valerianae-radix")
        assert result is not None
        assert result["title_en"] == "Valerianae radix - Valerian root"
        assert result["evidence_tier"] == "A"  # well-established
        assert result["tradition_code"] == "ema_hmpc"
        assert len(result["indications_native"]) >= 1
        assert len(result["contraindications_native"]) >= 1

    def test_extract_traditional_use_only(self) -> None:
        html = (
            "<html><body><h1>Passiflorae herba</h1>"
            "<div><h2>Therapeutic indications</h2>"
            "<p>Traditional use: relief of mild symptoms of mental stress; aid to sleep.</p>"
            "<h2>Contraindications</h2>"
            "<p>Hypersensitivity to Passiflora.</p></div></body></html>"
        )
        scraper = EmaHmpcScraper.__new__(EmaHmpcScraper)
        result = scraper._extract_monograph_data(html, "https://example.com/passiflorae-herba")
        assert result is not None
        assert result["evidence_tier"] == "B"  # traditional use only

    def test_extract_no_title_returns_none(self) -> None:
        html = "<html><body><div>No heading here</div></body></html>"
        scraper = EmaHmpcScraper.__new__(EmaHmpcScraper)
        result = scraper._extract_monograph_data(html, "https://example.com/empty")
        assert result is None


class TestNhpidWebUI:
    """Tests for NHPID web UI scraper (FCV-255 pivot)."""

    def test_scrape_ingredient_detail_parses_html(self) -> None:
        """Test HTML parsing against real NHPID web UI structure."""
        html = """
        <main>
        <h1>Chemical Substance - Ascorbic acid</h1>
        <div class="leftLabel">NHPID name:</div>
        <div class="alignedContent">Ascorbic acid</div>
        <div class="leftLabel">CAS registry number:</div>
        <div class="alignedContent">
            <a href="/nhpid-bdipsn/regReq?id=999">50-81-7</a>
        </div>
        <div class="leftLabel">Category:</div>
        <div class="alignedContent"><span>Approved Chemical Name</span></div>
        <div class="leftLabel">Monograph(s):</div>
        <div class="alignedContent">
            <a href="atReq?atid=vitc" class="at">Vitamin C</a>
        </div>
        <h2 class="mrgn-tp-0">Roles</h2>
        <h3>Medicinal</h3>
        </main>
        """
        import asyncio
        from fabrik_claim_validator.scrapers.nhpid import NhpidScraper

        ingredient = {"id": "1234", "name": "Ascorbic acid", "detail_url": "https://example.com/ingredReq?id=1234"}
        scraper = NhpidScraper.__new__(NhpidScraper)

        async def mock_get_html(_url):
            return html
        scraper._get_html = mock_get_html

        result = asyncio.run(scraper._scrape_ingredient_detail(ingredient))

        assert result is not None
        assert result["title_en"] == "Ascorbic acid"
        assert result["tradition_code"] == "nhpid"
        assert result["evidence_tier"] == "A"
        assert result["monograph_native_id"] == "nhpid_1234"
        assert result["metadata"]["cas"] == "50-81-7"
        assert result["metadata"]["role"] == "medicinal"
        assert result["metadata"]["monograph_reference"] == "Vitamin C"
        assert result["metadata"]["category"] == "Approved Chemical Name"

    def test_scrape_ingredient_detail_handles_missing_fields(self) -> None:
        """Test that missing optional fields are handled gracefully."""
        html = """
        <main>
        <h1>Chemical Substance - Unknown thing</h1>
        <div class="leftLabel">NHPID name:</div>
        <div class="alignedContent">Unknown thing</div>
        </main>
        """
        import asyncio
        from fabrik_claim_validator.scrapers.nhpid import NhpidScraper

        ingredient = {"id": "9999", "name": "Test", "detail_url": "https://example.com/test"}
        scraper = NhpidScraper.__new__(NhpidScraper)

        async def mock_get_html(_url):
            return html
        scraper._get_html = mock_get_html

        result = asyncio.run(scraper._scrape_ingredient_detail(ingredient))

        assert result is not None
        assert result["metadata"]["cas"] is None
        assert result["metadata"]["role"] == "unknown"
        assert result["metadata"]["monograph_reference"] is None
        assert result["indications_native"] == []
        assert result["contraindications_native"] == []


# ─── Integration tests (require DATABASE_URL) ─────────────────


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")
@pytest.mark.skip(reason="EMA listing route /en/medicines/herbal returns 404; blocked on FCV-202c")
class TestEmaHmpcIntegration:
    """Integration tests for EMA HMPC scraper with DB."""

    @pytest.mark.asyncio
    async def test_scrape_listing_enqueues_urls(self, pool) -> None:
        """FCV-201: listing scrape discovers URLs and enqueues them."""
        async with EmaHmpcScraper() as scraper:
            urls = await scraper.scrape_listing(pool)

        assert len(urls) == 5  # cassette has 5 monograph links
        # Verify queue table.
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT count(*) AS cnt FROM scrape_queue WHERE scraper_id = 'ema_hmpc'"
            )
        assert row["cnt"] == 5

    @pytest.mark.asyncio
    async def test_process_queue_parses_monographs(self, pool) -> None:
        """FCV-202: detail parser extracts monograph data from queue."""
        # First enqueue.
        async with EmaHmpcScraper() as scraper:
            await scraper.scrape_listing(pool)
            # Process only the 2 URLs we have detail cassettes for.
            # Others will fail gracefully.
            processed = await scraper.process_queue(pool, batch_size=5)

        # At least 2 monographs should be processed (valerian + echinacea).
        assert processed >= 2

        # Verify monographs table.
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM monographs WHERE tradition_code = 'ema_hmpc'"
            )
        assert len(rows) >= 2
        titles = [r["title_en"] for r in rows]
        assert any("Valerian" in t for t in titles)


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")
class TestNhpidIntegration:
    """Integration tests for NHPID scraper with DB."""

    @pytest.mark.asyncio
    async def test_scrape_ingredients_inserts(self, pool) -> None:
        """FCV-255: NHPID web UI scraper extracts ingredients and inserts monographs."""
        async with NhpidScraper(max_ingredients=5) as scraper:
            result = await scraper.scrape(pool)

        assert result["seen"] >= 1

        # Verify monographs table.
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM monographs WHERE tradition_code = 'nhpid'"
            )
        assert len(rows) >= 1
