"""HERB.ac.cn herb-detail resolver (FCV-104).

HERB is a Chinese academic TCM ingredient/target database hosted at
``http://herb.cuilab.cn``. Its ``/Detail`` pages ship the herb metadata in
a predictable HTML structure; we parse the three sections we care about:

- ``targets``         — list of human protein/gene targets
- ``ingredients``     — list of bioactive constituent names
- ``related_papers``  — list of PubMed IDs (PMIDs)

Politeness: **1 request per 2 seconds** (``TokenBucket(0.5, capacity=1)``).
Upstream has no published rate-limit but is an academic site; burst 1 and
0.5 rps keeps us polite.

Caching: successful detail responses are kept in ``cache_entries`` via
``services.cache`` with the default 90d TTL (the taxonomy and ingredient
lists are essentially static). Cassette-backed for offline CI.

Known-unknown: live runs against herb.cuilab.cn may need the FCV-006
proxy + (rarely) captcha wiring. This resolver accepts an injected
``httpx.AsyncClient`` so callers can pre-configure a proxy when required.
"""

from __future__ import annotations

import re
from typing import Any

import asyncpg
import httpx

from ..services import cache, cassettes
from ._rate_limit import TokenBucket

BASE_URL = "http://herb.cuilab.cn"
SCRAPER_ID = "herb_ac_cn"


class HerbAcCnResolver:
    """Async herb.ac.cn detail-page resolver."""

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
            self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ───────────── HTTP primitive (cassette-aware) ──────────────
    async def _get(self, path: str) -> dict[str, Any]:
        request = {"method": "GET", "url": f"{BASE_URL}{path}"}
        mode = cassettes.get_mode()
        if mode == "replay":
            return cassettes.replay(SCRAPER_ID, request)
        await self._bucket.acquire()
        assert self._client is not None  # noqa: S101 — __aenter__ ensures
        resp = await self._client.get(request["url"])
        body: dict[str, Any] = {
            "status": resp.status_code,
            "json": None,
            "text": resp.text,
        }
        if mode == "record":
            cassettes.record(SCRAPER_ID, request, body)
        return body

    # ───────────── Detail lookup ───────────────────────────────
    async def fetch_detail(
        self, herb_name: str, pool: asyncpg.Pool | None = None
    ) -> dict[str, Any] | None:
        """Return ``{herb_name, targets, ingredients, related_papers}`` or None.

        When ``pool`` is provided, the upstream response is cached via
        ``services.cache`` under the scraper's default 90d TTL.
        """
        query = {"herb_name": herb_name}
        cache_key = cache.make_key(SCRAPER_ID, query)
        if pool is not None:
            hit = await cache.get(pool, cache_key, scraper_id=SCRAPER_ID)
            if hit is not None:
                return hit

        path = f"/Detail?id={herb_name}"
        resp = await self._get(path)
        if resp.get("status") != 200 or not resp.get("text"):
            return None
        parsed = parse_detail_html(resp["text"], herb_name=herb_name)
        if pool is not None:
            await cache.set(
                pool,
                cache_key,
                scraper_id=SCRAPER_ID,
                query_payload=query,
                response_payload=parsed,
            )
        return parsed


# ───────────── HTML parsing (regex-based, section-anchored) ──────────
# We avoid pulling in a full HTML parser dependency for Sprint 1 — HERB's
# detail markup is stable and the three sections we need have unique
# anchor IDs. If the markup evolves, we swap this for lxml later.

_TARGETS_RE = re.compile(
    r"""(?isx)
    (?:<(?:h\d|div)[^>]*\bid=["']targets["'][^>]*>|targets[^<>]{0,30}</(?:h\d|a)>)
    (?P<body>.*?)
    (?:<(?:h\d)[^>]*>|$)
    """,
)
_INGREDIENTS_RE = re.compile(
    r"""(?isx)
    (?:<(?:h\d|div)[^>]*\bid=["']ingredients["'][^>]*>|ingredients[^<>]{0,30}</(?:h\d|a)>)
    (?P<body>.*?)
    (?:<(?:h\d)[^>]*>|$)
    """,
)
_PAPERS_RE = re.compile(
    r"""(?isx)
    (?:<(?:h\d|div)[^>]*\bid=["']related[_-]papers["'][^>]*>|related[_\s-]papers[^<>]{0,30}</(?:h\d|a)>)
    (?P<body>.*?)
    (?:<(?:h\d)[^>]*>|$)
    """,
)
_PMID_RE = re.compile(r"\b(?:PMID[:\s]*)?(\d{6,9})\b")
_LIST_ITEM_RE = re.compile(r"<li[^>]*>\s*([^<]+?)\s*</li>", re.IGNORECASE)
_LINK_TEXT_RE = re.compile(r"<a[^>]*>\s*([^<]+?)\s*</a>", re.IGNORECASE)


def parse_detail_html(html: str, *, herb_name: str) -> dict[str, Any]:
    """Extract targets / ingredients / PMIDs from a HERB detail page."""
    return {
        "herb_name": herb_name,
        "targets": _extract_section(html, _TARGETS_RE, _LINK_TEXT_RE),
        "ingredients": _extract_section(html, _INGREDIENTS_RE, _LIST_ITEM_RE),
        "related_papers": _extract_pmids(html, _PAPERS_RE),
    }


def _extract_section(html: str, section_re: re.Pattern[str], item_re: re.Pattern[str]) -> list[str]:
    match = section_re.search(html)
    if not match:
        return []
    body = match.group("body")
    items = [m.group(1).strip() for m in item_re.finditer(body)]
    # Dedupe preserving order; drop empties.
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_pmids(html: str, section_re: re.Pattern[str]) -> list[str]:
    match = section_re.search(html)
    if not match:
        return []
    pmids = _PMID_RE.findall(match.group("body"))
    seen: set[str] = set()
    out: list[str] = []
    for pmid in pmids:
        if pmid not in seen:
            seen.add(pmid)
            out.append(pmid)
    return out


__all__ = ["HerbAcCnResolver", "SCRAPER_ID", "BASE_URL", "parse_detail_html"]
