"""Health Canada NHPID web UI scraper (FCV-255 pivot).

Scrapes the NHPID (Natural Health Products Ingredients Database) web UI at
``https://webprod.hc-sc.gc.ca/nhpid-bdipsn/`` instead of the broken LNHPD JSON API.

**Pivot reason (2026-05-03):** The LNHPD JSON API at health-products.canada.ca/api/natural-licences/
returns empty arrays (backing DB detached or endpoint shape changed). The API is responsive
but returns no data. NHPID ≠ LNHPID — NHPID is the ingredient database we need,
LNHPD is licensed products (less useful).

Strategy:
    1. GET homepage to obtain CSRF token + session cookie.
    2. POST ``/nhpid-bdipsn/searchIngred`` with searchTxt='a' & searchRole=-1
       (returns ~15K ingredient links as ``ingredReq?id=NNN``).
    3. Follow each ingredient detail page.
    4. Extract: NHPID name, CAS number, monograph reference, role (Medicinal/
       Non-medicinal), category, proper names, common names.
    5. Map to ``monographs`` row with tradition_code='nhpid'.

Rate limit: 1 req / 2 sec (polite — government site).
"""

from __future__ import annotations

import re
from typing import Any

import asyncpg
import httpx

from ..logger import get_logger
from ..resolvers._rate_limit import TokenBucket
from ..services import cache, cassettes

logger = get_logger(__name__)

SCRAPER_ID = "nhpid"
BASE_URL = "https://webprod.hc-sc.gc.ca/nhpid-bdipsn"
TRADITION_CODE = "nhpid"


class NhpidScraper:
    """Async Health Canada NHPID web UI client."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rate_per_sec: float = 0.5,
        max_ingredients: int | None = None,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._bucket = TokenBucket(rate_per_sec, capacity=1)
        self._max_ingredients = max_ingredients

    async def __aenter__(self) -> NhpidScraper:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers={"User-Agent": "FabrikClaimValidator/1.0 (research)"},
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ─── HTTP primitives (cassette-aware) ──────────────────────
    async def _get_html(self, url: str) -> str:
        """Fetch HTML via GET, respecting cassette mode."""
        request: dict[str, Any] = {"method": "GET", "url": url}
        mode = cassettes.get_mode()
        if mode == "replay":
            body = cassettes.replay(SCRAPER_ID, request)
            return body.get("text", "")
        await self._bucket.acquire()
        assert self._client is not None  # noqa: S101
        resp = await self._client.get(url)
        body = {
            "status": resp.status_code,
            "text": resp.text,
        }
        if mode == "record":
            cassettes.record(SCRAPER_ID, request, body)
        return resp.text

    async def _post_html(self, url: str, data: dict[str, str]) -> str:
        """POST form data, respecting cassette mode."""
        request: dict[str, Any] = {"method": "POST", "url": url, "data": data}
        mode = cassettes.get_mode()
        if mode == "replay":
            body = cassettes.replay(SCRAPER_ID, request)
            return body.get("text", "")
        await self._bucket.acquire()
        assert self._client is not None  # noqa: S101
        resp = await self._client.post(url, data=data)
        body = {
            "status": resp.status_code,
            "text": resp.text,
        }
        if mode == "record":
            cassettes.record(SCRAPER_ID, request, body)
        return resp.text

    # ─── Main scrape flow ──────────────────────────────────────
    async def scrape(self, pool: asyncpg.Pool) -> dict[str, int]:
        """Scrape NHPID web UI for ingredient monographs.

        Returns dict with counts: {seen, inserted, updated}.
        """
        ingredients = await self._fetch_ingredient_list(pool)
        if self._max_ingredients is not None:
            ingredients = ingredients[: self._max_ingredients]
        logger.info("nhpid.ingredients_found", count=len(ingredients))

        upserted = 0
        for ingredient in ingredients:
            monograph = await self._scrape_ingredient_detail(ingredient)
            if monograph:
                await self._upsert_monograph(pool, monograph)
                upserted += 1

        logger.info("nhpid.done", upserted=upserted)
        return {"seen": len(ingredients), "inserted": upserted, "updated": 0}

    async def _fetch_ingredient_list(self, pool: asyncpg.Pool) -> list[dict[str, Any]]:
        """Fetch list of ingredients from NHPID search page.

        The NHPID search form requires a CSRF token from a GET to the homepage,
        then a POST to ``/nhpid-bdipsn/searchIngred`` with form data.
        Searching for 'a' with role=-1 returns all ~15K ingredients.
        """
        cache_key = cache.make_key(SCRAPER_ID, {"type": "ingredient_list"})
        cached = await cache.get(pool, cache_key, scraper_id=SCRAPER_ID)

        if cached is not None:
            return cached

        # Step 1: GET homepage to establish session + grab CSRF token
        home_html = await self._get_html(f"{BASE_URL}/")
        csrf_match = re.search(r'name="_csrf"\s+value="([^"]+)"', home_html)
        if not csrf_match:
            logger.error("nhpid.csrf_not_found")
            return []
        csrf_token = csrf_match.group(1)

        # Step 2: POST search — 'a' matches virtually all ingredients
        search_url = f"{BASE_URL}/searchIngred"
        html = await self._post_html(
            search_url,
            {
                "_csrf": csrf_token,
                "searchTxt": "a",
                "searchRole": "-1",
            },
        )

        # Parse HTML: links are <a href="/nhpid-bdipsn/ingredReq?id=NNN">Name</a>
        ingredients = []
        for match in re.finditer(
            r'href="/nhpid-bdipsn/ingredReq\?id=(\d+)">([^<]+)</a>',
            html,
        ):
            ingred_id = match.group(1)
            name = match.group(2).strip()
            if name:
                ingredients.append(
                    {
                        "id": ingred_id,
                        "name": name,
                        "detail_url": f"{BASE_URL}/ingredReq?id={ingred_id}",
                    }
                )

        logger.info("nhpid.search_results", count=len(ingredients))

        await cache.set(
            pool,
            cache_key,
            scraper_id=SCRAPER_ID,
            query_payload={"type": "ingredient_list"},
            response_payload=ingredients,
        )
        return ingredients

    @staticmethod
    def _extract_aligned(html: str, label: str) -> str | None:
        """Extract text from a leftLabel / alignedContent div pair."""
        pattern = (
            rf"{re.escape(label)}.*?</div>\s*"
            r'<div class="alignedContent[^"]*">\s*(.*?)\s*</div>'
        )
        m = re.search(pattern, html, re.DOTALL)
        if not m:
            return None
        # Strip HTML tags from the captured content
        raw = re.sub(r"<[^>]+>", " ", m.group(1)).strip()
        return raw or None

    async def _scrape_ingredient_detail(self, ingredient: dict[str, Any]) -> dict[str, Any] | None:
        """Scrape individual ingredient detail page.

        The page uses ``leftLabel`` / ``alignedContent`` div pairs:
        - NHPID name, Reference, Proper name(s), Common name(s)
        - CAS registry number (link inside alignedContent)
        - Monograph(s) (link inside alignedContent)
        - Role heading: ``<h3>Medicinal</h3>`` or ``<h3>Non-medicinal</h3>``
        """
        html = await self._get_html(ingredient["detail_url"])

        # CAS registry number — inside <a> tag in alignedContent
        cas_match = re.search(
            r"CAS registry number.*?<a[^>]+>(\S+)</a>",
            html,
            re.DOTALL,
        )
        cas = cas_match.group(1).strip() if cas_match else None

        # Role — <h3>Medicinal</h3> or <h3>Non-medicinal</h3> etc.
        role_match = re.search(
            r"<h2[^>]*>Roles</h2>.*?<h3>([^<]+)</h3>",
            html,
            re.DOTALL,
        )
        role = role_match.group(1).strip().lower() if role_match else "unknown"

        # Monograph reference — link text in Monograph(s) row
        mono_match = re.search(
            r'Monograph\(s\).*?class="at">([^<]+)</a>',
            html,
            re.DOTALL,
        )
        monograph_ref = mono_match.group(1).strip() if mono_match else None

        # Category (Approved Herbal Name, Chemical Substance, etc.)
        category = self._extract_aligned(html, "Category:")

        # Preparations (if present)
        preps_raw = self._extract_aligned(html, "Preparations:")
        preparations = []
        if preps_raw:
            preparations = [p.strip() for p in re.split(r"[;,]", preps_raw) if p.strip()]

        return {
            "tradition_code": TRADITION_CODE,
            "source_id": "nhpid",
            "monograph_native_id": f"nhpid_{ingredient['id']}",
            "title_en": ingredient["name"],
            "title_native": ingredient["name"],
            "monograph_lang": "en",
            "evidence_tier": "A",
            "indications_native": [],
            "contraindications_native": [],
            "preparations": preparations,
            "source_url": ingredient["detail_url"],
            "metadata": {
                "cas": cas,
                "role": role,
                "monograph_reference": monograph_ref,
                "category": category,
            },
        }

    async def _upsert_monograph(self, pool: asyncpg.Pool, data: dict[str, Any]) -> None:
        """Insert or update a monograph row."""
        import json

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO monographs (
                    tradition_code, source_id, monograph_native_id,
                    title_en, title_native, monograph_lang,
                    evidence_tier, indications_native,
                    contraindications_native, preparations,
                    source_url, scraped_at, page_refs
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8::text[], $9::text[],
                    $10::jsonb, $11, NOW(), $12::jsonb
                )
                ON CONFLICT (tradition_code, source_id, monograph_native_id)
                DO UPDATE SET
                    title_en = EXCLUDED.title_en,
                    title_native = EXCLUDED.title_native,
                    evidence_tier = EXCLUDED.evidence_tier,
                    indications_native = EXCLUDED.indications_native,
                    contraindications_native = EXCLUDED.contraindications_native,
                    preparations = EXCLUDED.preparations,
                    source_url = EXCLUDED.source_url,
                    scraped_at = NOW(),
                    page_refs = EXCLUDED.page_refs
                """,
                data["tradition_code"],
                data["source_id"],
                data["monograph_native_id"],
                data["title_en"],
                data["title_native"],
                data["monograph_lang"],
                data["evidence_tier"],
                data["indications_native"],
                data["contraindications_native"],
                json.dumps(data["preparations"]),
                data["source_url"],
                json.dumps(data.get("metadata", {})),
            )


__all__ = ["NhpidScraper", "SCRAPER_ID", "TRADITION_CODE"]
