"""HERB 2.0 resolver via JSON API (FCV-104, rewritten FCV-253).

HERB 2.0 is a Chinese academic TCM database at ``http://47.92.70.12``
(also reachable via ``http://herb.ac.cn/v2``). It exposes a single
``POST /chedi/api/`` JSON-RPC endpoint with ``func_name`` dispatch:

- ``search_api``  — name→herb-ID lookup
- ``detail_api``  — full herb detail (ingredients, targets, diseases,
  clinical trials, meta-analyses, papers)

Politeness: **1 request per 2 seconds** (``TokenBucket(0.5, capacity=1)``).
Upstream has no published rate-limit but is an academic site.

Caching: successful detail responses are kept in ``cache_entries`` via
``services.cache`` with the default 90d TTL. Cassette-backed for offline CI.

Base URL is configurable via ``HERB_BASE_URL`` env var (default
``http://47.92.70.12``). No proxy or Browserless needed — the JSON API
is reachable directly from WSL.
"""

from __future__ import annotations

import os
import re
from typing import Any

import asyncpg
import httpx

from ..logger import get_logger
from ..services import cache, cassettes
from ._rate_limit import TokenBucket

logger = get_logger(__name__)

BASE_URL = os.getenv("HERB_BASE_URL", "http://47.92.70.12")
API_PATH = "/chedi/api/"
SCRAPER_ID = "herb_ac_cn"

_PMID_RE = re.compile(r"\b(\d{6,9})\b")

# HERB 2.0 indexes herbs by Chinese/Pinyin names. Latin binomials often
# fail search. This maps lowercased Latin names to Pinyin search terms.
_PINYIN_ALIASES: dict[str, list[str]] = {
    "astragalus membranaceus": ["Huang Qi"],
    "bupleurum chinense": ["Chai Hu"],
    "salvia miltiorrhiza": ["Dan Shen"],
    "rehmannia glutinosa": ["Di Huang"],
    "angelica sinensis": ["Dang Gui"],
    "atractylodes macrocephala": ["Bai Zhu"],
    "codonopsis pilosula": ["Dang Shen"],
    "schisandra chinensis": ["Wu Wei Zi"],
    "panax ginseng": ["Ren Shen", "Ginseng"],
    "glycyrrhiza uralensis": ["Gan Cao"],
}


class HerbAcCnResolver:
    """Async HERB 2.0 JSON API resolver."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rate_per_sec: float = 0.5,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._bucket = TokenBucket(rate_per_sec, capacity=1)

    async def __aenter__(self) -> HerbAcCnResolver:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "fabrik-claim-validator/0.1 (research; ozgur@ocoron.com)"},
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ───────────── HTTP primitive (cassette-aware) ──────────────
    async def _post_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to /chedi/api/ with JSON body. Cassette-aware."""
        url = f"{BASE_URL}{API_PATH}"
        request = {"method": "POST", "url": url, "body": payload}
        mode = cassettes.get_mode()
        if mode == "replay":
            return cassettes.replay(SCRAPER_ID, request)
        await self._bucket.acquire()
        assert self._client is not None  # noqa: S101 — __aenter__ ensures
        resp = await self._client.post(url, json=payload)
        body: dict[str, Any] = {
            "status": resp.status_code,
            "json": resp.json() if resp.status_code == 200 else None,
            "text": resp.text,
        }
        if mode == "record":
            cassettes.record(SCRAPER_ID, request, body)
        return body

    # ───────────── Search (name → herb IDs) ────────────────────
    async def search_herb(self, keyword: str) -> list[dict[str, str]]:
        """Search HERB 2.0 by keyword. Returns list of ``{herb_id, english_name, latin_name, ...}``."""
        resp = await self._post_api(
            {
                "keyword": keyword,
                "label": "Herb",
                "func_name": "search_api",
            }
        )
        raw = resp.get("json")
        if not raw or "res_data" not in raw:
            return []
        return _parse_search_results(raw["res_data"])

    # ───────────── Detail by ID (skip search) ───────────────────
    async def fetch_detail_by_id(
        self,
        herb_id: str,
        herb_name: str = "",
        pool: asyncpg.Pool | None = None,
    ) -> dict[str, Any] | None:
        """Fetch detail directly by HERB ID (e.g. ``HERB002560``), skipping search."""
        resp = await self._post_api(
            {
                "v": herb_id,
                "label": "Herb",
                "key_id": herb_id,
                "func_name": "detail_api",
            }
        )
        raw = resp.get("json")
        if not raw:
            return None
        parsed = parse_detail_json(raw, herb_name=herb_name or herb_id, herb_id=herb_id)
        if pool is not None:
            cache_key = cache.make_key(SCRAPER_ID, {"herb_name": herb_name or herb_id})
            await cache.set(
                pool,
                cache_key,
                scraper_id=SCRAPER_ID,
                query_payload={"herb_name": herb_name or herb_id},
                response_payload=parsed,
            )
        return parsed

    # ───────────── Detail lookup ───────────────────────────────
    async def fetch_detail(
        self, herb_name: str, pool: asyncpg.Pool | None = None
    ) -> dict[str, Any] | None:
        """Return ``{herb_name, herb_id, targets, ingredients, related_papers, ...}`` or None.

        Two-step: search for the herb ID first, then fetch detail.
        Tries the original name, then known Pinyin aliases if no results.
        When ``pool`` is provided, the upstream response is cached via
        ``services.cache`` under the scraper's default 90d TTL.
        """
        query = {"herb_name": herb_name}
        cache_key = cache.make_key(SCRAPER_ID, query)
        if pool is not None:
            hit = await cache.get(pool, cache_key, scraper_id=SCRAPER_ID)
            if hit is not None:
                return hit

        # Step 1: search for herb ID — try original name then Pinyin aliases.
        search_terms = [herb_name] + _PINYIN_ALIASES.get(herb_name.lower(), [])
        matches: list[dict[str, str]] = []
        for term in search_terms:
            matches = await self.search_herb(term)
            if matches:
                break
        if not matches:
            logger.warning("herb.search.no_results", keyword=herb_name, tried=search_terms)
            return None
        herb_id = matches[0]["herb_id"]
        logger.info("herb.search.matched", keyword=herb_name, herb_id=herb_id)

        # Step 2: fetch detail by ID.
        resp = await self._post_api(
            {
                "v": herb_id,
                "label": "Herb",
                "key_id": herb_id,
                "func_name": "detail_api",
            }
        )
        raw = resp.get("json")
        if not raw:
            logger.warning("herb.detail.empty", herb_id=herb_id)
            return None

        parsed = parse_detail_json(raw, herb_name=herb_name, herb_id=herb_id)
        if pool is not None:
            await cache.set(
                pool,
                cache_key,
                scraper_id=SCRAPER_ID,
                query_payload=query,
                response_payload=parsed,
            )
        return parsed


# ───────────── JSON response parsers ──────────────────────────


def _parse_search_results(res_data: list[Any]) -> list[dict[str, str]]:
    """Parse ``res_data`` from search_api response into flat dicts."""
    if len(res_data) < 2:
        return []
    header = res_data[0]  # column names
    results: list[dict[str, str]] = []
    for row in res_data[1:]:
        entry: dict[str, str] = {}
        for i, cell in enumerate(row):
            col_name = header[i] if i < len(header) else f"col_{i}"
            key = col_name.lower().replace(" ", "_")
            if isinstance(cell, dict):
                if "link" in cell:
                    # Herb ID link cell: {"link": "/Detail/?v=HERB002319&label=Herb", "title": "HERB002319"}
                    entry["herb_id"] = cell.get("title", "")
                    entry["detail_link"] = cell.get("link", "")
                else:
                    # Styled cell (e.g. Latin name with italic): {"style": {...}, "title": "..."}
                    entry[key] = cell.get("title", "")
            elif isinstance(cell, str):
                entry[key] = cell
        results.append(entry)
    return results


def parse_detail_json(raw: dict[str, Any], *, herb_name: str, herb_id: str) -> dict[str, Any]:
    """Extract targets / ingredients / PMIDs / diseases / clinical trials from detail_api JSON."""
    targets = _extract_table_column(raw.get("herb_target", []), "Gene symbol")
    ingredients = _extract_table_column(raw.get("herb_ingredient", []), "Ingredient name")
    diseases = _extract_table_column(raw.get("herb_disease", []), "Disease name")

    # PMIDs from drug_paper_disease and drug_paper_target.
    paper_pmids: list[str] = []
    for key in ("drug_paper_disease", "drug_paper_target"):
        for pmid in _extract_table_column(raw.get(key, []), "PubMed id"):
            if pmid and pmid not in paper_pmids:
                paper_pmids.append(pmid)

    # Clinical trial NCT IDs.
    clinical_trials = _extract_table_column(raw.get("clinical_herb", []), "NCT id")

    # Summary metadata.
    summary = _parse_summary(raw.get("summary", []))

    return {
        "herb_name": herb_name,
        "herb_id": herb_id,
        "targets": targets,
        "ingredients": ingredients,
        "related_papers": paper_pmids,
        "diseases": diseases,
        "clinical_trials": clinical_trials,
        "summary": summary,
    }


def _extract_table_column(table: list[Any], column_name: str) -> list[str]:
    """Extract a named column from HERB's table format: [header_row, data_row1, ...]."""
    if len(table) < 2:
        return []
    header = table[0]
    try:
        col_idx = header.index(column_name)
    except ValueError:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in table[1:]:
        if col_idx >= len(row):
            continue
        cell = row[col_idx]
        val = cell.get("title", "") if isinstance(cell, dict) else str(cell) if cell else ""
        if val and val != "NA" and val not in seen:
            seen.add(val)
            out.append(val)
    return out


def _parse_summary(summary: list[Any]) -> dict[str, str]:
    """Parse the summary table into a flat dict."""
    if len(summary) < 2:
        return {}
    header = summary[0]
    row = summary[1]
    result: dict[str, str] = {}
    for i, col in enumerate(header):
        if i < len(row):
            cell = row[i]
            val = cell.get("title", "") if isinstance(cell, dict) else str(cell) if cell else ""
            key = col.lower().replace(" ", "_")
            result[key] = val
    return result


# ───────────── Legacy HTML parser (backward compat for tests) ─────────


def parse_detail_html(html: str, *, herb_name: str) -> dict[str, Any]:
    """Extract targets / ingredients / PMIDs from HERB v1 HTML (legacy, cassette-only)."""
    _TARGETS_RE = re.compile(
        r"(?isx)(?:<(?:h\d|div)[^>]*\bid=[\"']targets[\"'][^>]*>|targets[^<>]{0,30}</(?:h\d|a)>)"
        r"(?P<body>.*?)(?:<(?:h\d)[^>]*>|$)",
    )
    _INGREDIENTS_RE = re.compile(
        r"(?isx)(?:<(?:h\d|div)[^>]*\bid=[\"']ingredients[\"'][^>]*>|ingredients[^<>]{0,30}</(?:h\d|a)>)"
        r"(?P<body>.*?)(?:<(?:h\d)[^>]*>|$)",
    )
    _PAPERS_RE = re.compile(
        r"(?isx)(?:<(?:h\d|div)[^>]*\bid=[\"']related[_-]papers[\"'][^>]*>|related[_\s-]papers[^<>]{0,30}</(?:h\d|a)>)"
        r"(?P<body>.*?)(?:<(?:h\d)[^>]*>|$)",
    )
    _LINK_TEXT_RE = re.compile(r"<a[^>]*>\s*([^<]+?)\s*</a>", re.IGNORECASE)
    _LIST_ITEM_RE = re.compile(r"<li[^>]*>\s*([^<]+?)\s*</li>", re.IGNORECASE)

    def _extract(section_re: re.Pattern[str], item_re: re.Pattern[str]) -> list[str]:
        match = section_re.search(html)
        if not match:
            return []
        body = match.group("body")
        seen: set[str] = set()
        out: list[str] = []
        for m in item_re.finditer(body):
            val = m.group(1).strip()
            if val and val not in seen:
                seen.add(val)
                out.append(val)
        return out

    def _extract_pmids(section_re: re.Pattern[str]) -> list[str]:
        match = section_re.search(html)
        if not match:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for pmid in _PMID_RE.findall(match.group("body")):
            if pmid not in seen:
                seen.add(pmid)
                out.append(pmid)
        return out

    return {
        "herb_name": herb_name,
        "targets": _extract(_TARGETS_RE, _LINK_TEXT_RE),
        "ingredients": _extract(_INGREDIENTS_RE, _LIST_ITEM_RE),
        "related_papers": _extract_pmids(_PAPERS_RE),
    }


__all__ = ["HerbAcCnResolver", "SCRAPER_ID", "BASE_URL", "parse_detail_html", "parse_detail_json"]
