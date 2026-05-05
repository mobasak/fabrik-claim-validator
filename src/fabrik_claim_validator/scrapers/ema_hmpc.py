"""EMA HMPC herbal monograph scraper (FCV-201 + FCV-202 + FCV-202b).

Two-phase scraper:

Phase 1 (FCV-201 — search index):
    Scrape ``https://www.ema.europa.eu/en/medicines/herbal`` listing pages.
    Extract monograph detail URLs, insert into ``scrape_queue``.
    Allocates ``worker_id`` for sticky session. Rate: 1 req / 3 sec.
    Caches each listing page via ``services.cache``.

Phase 2 (FCV-202b — detail parser, PDF primary path):
    For each queued URL, fetch the detail page and discover linked PDFs.
    Download and parse PDFs via ``parsers.pdf_monograph``:
    - community-herbal-monograph → primary (evidence_tier A or B)
    - assessment-report → secondary evidence
    If no PDF is available, fall back to HTML parsing (FCV-202 legacy).
    Insert into ``monographs`` table.
"""

from __future__ import annotations

import base64
import re
from typing import Any

import asyncpg
import httpx

from ..logger import get_logger
from ..parsers.pdf_monograph import PdfMonographParser, SectionPattern
from ..resolvers._rate_limit import TokenBucket
from ..services import cache, cassettes

logger = get_logger(__name__)

SCRAPER_ID = "ema_hmpc"
BASE_URL = "https://www.ema.europa.eu"
LISTING_PATH = "/en/medicines/herbal"
TRADITION_CODE = "ema_hmpc"

# EMA listing page contains links to monograph details in a paged view.
# We parse the listing HTML for links matching the monograph URL pattern.
_MONOGRAPH_LINK_RE = re.compile(r'href="(/en/medicines/herbal/[^"]+)"', re.IGNORECASE)
# From monograph detail page, extract structured sections.
_TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_INDICATION_SECTION_RE = re.compile(
    r"(?:therapeutic\s+indications?|indications?)\s*[:\-]?\s*(.*?)(?=<h|contraindication|$)",
    re.IGNORECASE | re.DOTALL,
)
_CONTRAINDICATION_RE = re.compile(
    r"contraindication[s]?\s*[:\-]?\s*(.*?)(?=<h|special\s+warning|$)",
    re.IGNORECASE | re.DOTALL,
)
_PREPARATION_RE = re.compile(
    r"(?:pharmaceutical\s+form|preparation[s]?)\s*[:\-]?\s*(.*?)(?=<h|posology|$)",
    re.IGNORECASE | re.DOTALL,
)
_WELL_ESTABLISHED_RE = re.compile(r"well.?established\s+use", re.IGNORECASE)
_TRADITIONAL_USE_RE = re.compile(r"traditional\s+use", re.IGNORECASE)

# Strip HTML tags for text extraction.
_TAG_RE = re.compile(r"<[^>]+>")

# ── PDF link discovery and classification (FCV-202b) ──────────
# EMA detail pages link to multiple PDFs per herb.  We classify by URL:
_PDF_LINK_RE = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)

# Classification priority (first match wins — most specific substrings first).
_PDF_CLASSES = [
    ("list-of-references", "references"),
    ("list-references", "references"),
    ("assessment-report", "secondary"),
    ("public-statement", "secondary"),
    ("community-herbal-monograph", "primary"),
    ("herbal-monograph", "primary"),
]

# Section extraction patterns for PDF text (no HTML tags — plain text).
# Each pattern captures from section header to the next known header or end of text.
# DOTALL so `.` matches newlines; the lookahead anchors on known section headers.
_PDF_SECTION_BOUNDARY = (
    r"(?=\n(?:Therapeutic\s+indication|Contraindication|Special\s+warning|"
    r"Undesirable|Interaction|Posology|Pharmaceutical\s+form|Preparation|"
    r"Method\s+of\s+administration|Clinical\s+particular|Pharmacological)"
    r"|\Z)"
)

EMA_PDF_SECTION_PATTERNS = [
    SectionPattern(
        name="title",
        pattern=re.compile(
            r"^(.+?)(?=\n)",
            re.MULTILINE,
        ),
    ),
    SectionPattern(
        name="indications",
        pattern=re.compile(
            r"[Tt]herapeutic\s+indications?\s*\n(.*?)" + _PDF_SECTION_BOUNDARY,
            re.DOTALL,
        ),
    ),
    SectionPattern(
        name="contraindications",
        pattern=re.compile(
            r"[Cc]ontraindications?\s*\n(.*?)" + _PDF_SECTION_BOUNDARY,
            re.DOTALL,
        ),
    ),
    SectionPattern(
        name="preparations",
        pattern=re.compile(
            r"[Pp]harmaceutical\s+form\s*\n(.*?)" + _PDF_SECTION_BOUNDARY,
            re.DOTALL,
        ),
    ),
]


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    cleaned = _TAG_RE.sub(" ", text)
    return " ".join(cleaned.split()).strip()


def _split_list_items(text: str) -> list[str]:
    """Split semicolon/bullet-separated text into a list of items."""
    text = _strip_html(text)
    items = re.split(r"[;•\n]+", text)
    return [item.strip() for item in items if item.strip()]


class EmaHmpcScraper:
    """Async EMA HMPC scraper with rate limiting and caching."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rate_per_sec: float = 1 / 3,
        worker_id: int | None = None,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._bucket = TokenBucket(rate_per_sec, capacity=1)
        self.worker_id = worker_id

    async def __aenter__(self) -> EmaHmpcScraper:
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

    # ─── HTTP primitive (cassette-aware) ───────────────────────
    async def _get(self, url: str) -> dict[str, Any]:
        """Fetch a URL, respecting cassette mode and rate limit."""
        request = {"method": "GET", "url": url}
        mode = cassettes.get_mode()
        if mode == "replay":
            return cassettes.replay(SCRAPER_ID, request)
        await self._bucket.acquire()
        assert self._client is not None  # noqa: S101
        resp = await self._client.get(url)
        body: dict[str, Any] = {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "text": resp.text,
        }
        if mode == "record":
            cassettes.record(SCRAPER_ID, request, body)
        return body

    # ─── Phase 1: Listing scrape (FCV-201) ─────────────────────
    async def scrape_listing(self, pool: asyncpg.Pool) -> list[str]:
        """Scrape EMA herbal listing and enqueue monograph URLs.

        Returns the list of discovered monograph URLs.
        """
        discovered: list[str] = []
        page = 0
        while True:
            url = f"{BASE_URL}{LISTING_PATH}?page={page}"
            logger.info("ema_hmpc.listing", url=url, page=page)

            # Check cache first.
            cache_key = cache.make_key(SCRAPER_ID, {"type": "listing", "page": page})
            cached = await cache.get(pool, cache_key, scraper_id=SCRAPER_ID)
            if cached is not None:
                html = cached.get("text", "")
            else:
                resp = await self._get(url)
                if resp.get("status") != 200:
                    logger.warning(
                        "ema_hmpc.listing.failed",
                        status=resp.get("status"),
                        page=page,
                    )
                    break
                html = resp.get("text", "")
                # Cache the listing page.
                await cache.set(
                    pool,
                    cache_key,
                    scraper_id=SCRAPER_ID,
                    query_payload={"type": "listing", "page": page},
                    response_payload={"text": html},
                )

            # Extract monograph links.
            links = _MONOGRAPH_LINK_RE.findall(html)
            if not links:
                break

            for link in links:
                full_url = f"{BASE_URL}{link}" if link.startswith("/") else link
                if full_url not in discovered:
                    discovered.append(full_url)

            page += 1

        # Enqueue all discovered URLs.
        if discovered:
            await self._enqueue_urls(pool, discovered)

        logger.info("ema_hmpc.listing.done", total_urls=len(discovered))
        return discovered

    async def _enqueue_urls(self, pool: asyncpg.Pool, urls: list[str]) -> int:
        """Insert URLs into scrape_queue (idempotent — ON CONFLICT DO NOTHING)."""
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO scrape_queue (scraper_id, url, worker_id, metadata)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (scraper_id, url) DO NOTHING
                """,
                [(SCRAPER_ID, url, self.worker_id, '{"source": "listing"}') for url in urls],
            )
        # executemany doesn't return count — query to confirm.
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT count(*) AS cnt FROM scrape_queue WHERE scraper_id = $1",
                SCRAPER_ID,
            )
        count = int(row["cnt"]) if row else 0
        return count

    # ─── PDF helpers (FCV-202b) ─────────────────────────────────
    def _classify_pdf_links(self, html: str) -> dict[str, list[str]]:
        """Find all PDF links on a detail page and classify them.

        Returns dict mapping class ('primary', 'secondary', 'references')
        to list of absolute URLs.  All linked PDFs are captured; unknown
        types go into 'other'.
        """
        raw_links = _PDF_LINK_RE.findall(html)
        classified: dict[str, list[str]] = {}
        for link in raw_links:
            url = f"{BASE_URL}{link}" if link.startswith("/") else link
            pdf_class = "other"
            for substring, cls in _PDF_CLASSES:
                if substring in link.lower():
                    pdf_class = cls
                    break
            classified.setdefault(pdf_class, []).append(url)
        return classified

    async def _download_pdf(self, url: str) -> bytes | None:
        """Download a PDF, returning raw bytes or None on failure."""
        request = {"method": "GET", "url": url}
        mode = cassettes.get_mode()
        if mode == "replay":
            try:
                resp_data = cassettes.replay(SCRAPER_ID, request)
                # Cassette stores PDF content as base64 in 'pdf_b64' field.
                b64 = resp_data.get("pdf_b64", "")
                return base64.b64decode(b64) if b64 else None
            except cassettes.CassetteMissError:
                return None

        await self._bucket.acquire()
        assert self._client is not None  # noqa: S101
        try:
            resp = await self._client.get(url)
            if resp.status_code != 200:
                logger.warning("ema_hmpc.pdf_download.failed", url=url, status=resp.status_code)
                return None
            pdf_bytes = resp.content
            if mode == "record":
                cassettes.record(
                    SCRAPER_ID,
                    request,
                    {"status": 200, "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii")},
                )
            return pdf_bytes
        except httpx.HTTPError as exc:
            logger.warning("ema_hmpc.pdf_download.error", url=url, error=str(exc))
            return None

    # ─── Phase 2: Detail parser (FCV-202b) ────────────────────
    async def process_queue(
        self,
        pool: asyncpg.Pool,
        *,
        batch_size: int = 10,
    ) -> int:
        """Claim and process queued monograph URLs. Returns count processed."""
        processed = 0
        while True:
            # Claim a batch.
            rows = await self._claim_batch(pool, batch_size)
            if not rows:
                break
            for row in rows:
                url = row["url"]
                queue_id = row["id"]
                try:
                    monograph = await self._parse_monograph(pool, url)
                    if monograph:
                        await self._upsert_monograph(pool, monograph)
                    await self._mark_done(pool, queue_id)
                    processed += 1
                except Exception as exc:
                    logger.error(
                        "ema_hmpc.detail.error",
                        url=url,
                        error=str(exc),
                    )
                    await self._mark_failed(pool, queue_id, str(exc))

        logger.info("ema_hmpc.process_queue.done", processed=processed)
        return processed

    async def _claim_batch(self, pool: asyncpg.Pool, batch_size: int) -> list[dict[str, Any]]:
        """Claim pending rows for processing (atomic)."""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE scrape_queue
                   SET status = 'processing',
                       claimed_at = NOW(),
                       attempts = attempts + 1
                 WHERE id IN (
                     SELECT id FROM scrape_queue
                      WHERE scraper_id = $1
                        AND status = 'pending'
                        AND attempts < max_attempts
                      ORDER BY priority DESC, created_at ASC
                      LIMIT $2
                      FOR UPDATE SKIP LOCKED
                 )
                RETURNING id, url, metadata
                """,
                SCRAPER_ID,
                batch_size,
            )
        return [dict(r) for r in rows]

    async def _parse_monograph(self, pool: asyncpg.Pool, url: str) -> dict[str, Any] | None:
        """Fetch detail page, discover PDFs, parse.  PDF primary, HTML fallback."""
        # Fetch the detail HTML page (always needed for PDF link discovery).
        cache_key = cache.make_key(SCRAPER_ID, {"type": "detail", "url": url})
        cached = await cache.get(pool, cache_key, scraper_id=SCRAPER_ID)
        if cached is not None:
            html = cached.get("text", "")
        else:
            resp = await self._get(url)
            if resp.get("status") != 200:
                logger.warning("ema_hmpc.detail.http_error", url=url, status=resp.get("status"))
                return None
            html = resp.get("text", "")
            await cache.set(
                pool,
                cache_key,
                scraper_id=SCRAPER_ID,
                query_payload={"type": "detail", "url": url},
                response_payload={"text": html},
            )

        # ── PDF primary path (FCV-202b) ──────────────────────────
        pdf_links = self._classify_pdf_links(html)
        primary_pdfs = pdf_links.get("primary", [])

        if primary_pdfs:
            for pdf_url in primary_pdfs:
                pdf_bytes = await self._download_pdf(pdf_url)
                if pdf_bytes:
                    result = await self._parse_pdf_monograph(pdf_bytes, url, pdf_url)
                    if result:
                        logger.info(
                            "ema_hmpc.detail.pdf_parsed",
                            url=url,
                            pdf_url=pdf_url,
                            sections=list(result.get("_parsed", {}).sections.keys())
                            if result.get("_parsed")
                            else [],
                        )
                        return result
            # All primary PDFs failed — log and try secondary.
            logger.warning("ema_hmpc.detail.primary_pdf_failed", url=url)

        # Try secondary (assessment-report) PDFs.
        secondary_pdfs = pdf_links.get("secondary", [])
        for pdf_url in secondary_pdfs:
            pdf_bytes = await self._download_pdf(pdf_url)
            if pdf_bytes:
                result = await self._parse_pdf_monograph(pdf_bytes, url, pdf_url)
                if result:
                    # Secondary evidence → cap at tier B.
                    result["evidence_tier"] = "B"
                    logger.info("ema_hmpc.detail.secondary_pdf_parsed", url=url, pdf_url=pdf_url)
                    return result

        # ── HTML fallback (FCV-202 legacy) ───────────────────────
        logger.info("ema_hmpc.detail.html_fallback", url=url)
        return self._extract_monograph_data(html, url)

    async def _parse_pdf_monograph(
        self,
        pdf_bytes: bytes,
        source_url: str,
        pdf_url: str,
    ) -> dict[str, Any] | None:
        """Parse a downloaded PDF into monograph data."""
        parser = PdfMonographParser()
        parsed = await parser.parse(pdf_bytes, pdf_url, EMA_PDF_SECTION_PATTERNS)

        if not parsed.sections:
            logger.warning("ema_hmpc.pdf.no_sections", pdf_url=pdf_url)
            return None

        # Build monograph dict from parsed sections.
        title = parsed.sections.get("title", "").strip()
        if not title:
            # Try first non-empty line of full text.
            for line in parsed.full_text.split("\n"):
                line = line.strip()
                if len(line) > 5:
                    title = line
                    break
        if not title:
            return None

        # Evidence tier from full text.
        full_text = parsed.full_text
        evidence_tier = "B"
        if _WELL_ESTABLISHED_RE.search(full_text):
            evidence_tier = "A"

        # Indications.
        indications_raw = parsed.sections.get("indications", "")
        indications = _split_list_items(indications_raw) if indications_raw else []

        # Contraindications.
        contra_raw = parsed.sections.get("contraindications", "")
        contraindications = _split_list_items(contra_raw) if contra_raw else []

        # Preparations.
        prep_raw = parsed.sections.get("preparations", "")
        preparations = _split_list_items(prep_raw) if prep_raw else []

        # Derive native ID from URL slug.
        slug = source_url.rstrip("/").split("/")[-1]
        monograph_native_id = f"ema_hmpc_{slug}"

        result: dict[str, Any] = {
            "tradition_code": TRADITION_CODE,
            "source_id": "ema_hmpc",
            "monograph_native_id": monograph_native_id,
            "title_en": title,
            "title_native": title,
            "monograph_lang": "en",
            "evidence_tier": evidence_tier,
            "indications_native": indications,
            "contraindications_native": contraindications,
            "preparations": preparations,
            "full_text": full_text,
            "source_url": source_url,
            "_parsed": parsed,  # attached for logging; stripped before DB insert
        }
        return result

    def _extract_monograph_data(self, html: str, url: str) -> dict[str, Any] | None:
        """Extract structured monograph data from HTML."""
        # Title.
        title_match = _TITLE_RE.search(html)
        title = _strip_html(title_match.group(1)) if title_match else ""
        if not title:
            return None

        # Determine evidence tier based on content.
        evidence_tier = "B"  # default: traditional use
        if _WELL_ESTABLISHED_RE.search(html):
            evidence_tier = "A"
        elif _TRADITIONAL_USE_RE.search(html):
            evidence_tier = "B"

        # Indications.
        indications: list[str] = []
        ind_match = _INDICATION_SECTION_RE.search(html)
        if ind_match:
            indications = _split_list_items(ind_match.group(1))

        # Contraindications.
        contraindications: list[str] = []
        contra_match = _CONTRAINDICATION_RE.search(html)
        if contra_match:
            contraindications = _split_list_items(contra_match.group(1))

        # Preparations.
        preparations: list[str] = []
        prep_match = _PREPARATION_RE.search(html)
        if prep_match:
            preparations = _split_list_items(prep_match.group(1))

        # Derive a native ID from the URL slug.
        slug = url.rstrip("/").split("/")[-1]
        monograph_native_id = f"ema_hmpc_{slug}"

        return {
            "tradition_code": TRADITION_CODE,
            "source_id": "ema_hmpc",
            "monograph_native_id": monograph_native_id,
            "title_en": title,
            "title_native": title,
            "monograph_lang": "en",
            "evidence_tier": evidence_tier,
            "indications_native": indications,
            "contraindications_native": contraindications,
            "preparations": preparations,
            "full_text": _strip_html(html)[:50000],
            "source_url": url,
        }

    async def _upsert_monograph(self, pool: asyncpg.Pool, data: dict[str, Any]) -> None:
        """Insert or update a monograph row."""
        import json

        # Strip internal metadata not destined for DB.
        data = {k: v for k, v in data.items() if not k.startswith("_")}
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO monographs (
                    tradition_code, source_id, monograph_native_id,
                    title_en, title_native, monograph_lang,
                    evidence_tier, indications_native,
                    contraindications_native, preparations,
                    full_text, source_url, scraped_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8::text[], $9::text[],
                    $10::jsonb, $11, $12, NOW()
                )
                ON CONFLICT (tradition_code, source_id, monograph_native_id)
                DO UPDATE SET
                    title_en = EXCLUDED.title_en,
                    title_native = EXCLUDED.title_native,
                    evidence_tier = EXCLUDED.evidence_tier,
                    indications_native = EXCLUDED.indications_native,
                    contraindications_native = EXCLUDED.contraindications_native,
                    preparations = EXCLUDED.preparations,
                    full_text = EXCLUDED.full_text,
                    source_url = EXCLUDED.source_url,
                    scraped_at = NOW()
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
                data.get("full_text", ""),
                data["source_url"],
            )

    async def _mark_done(self, pool: asyncpg.Pool, queue_id: int) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scrape_queue SET status = 'done', completed_at = NOW() WHERE id = $1",
                queue_id,
            )

    async def _mark_failed(self, pool: asyncpg.Pool, queue_id: int, error: str) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scrape_queue SET status = CASE WHEN attempts >= max_attempts "
                "THEN 'failed' ELSE 'pending' END, last_error = $2 WHERE id = $1",
                queue_id,
                error[:500],
            )


__all__ = ["EMA_PDF_SECTION_PATTERNS", "EmaHmpcScraper", "SCRAPER_ID", "TRADITION_CODE"]
