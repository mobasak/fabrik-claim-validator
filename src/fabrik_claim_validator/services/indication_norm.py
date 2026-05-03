"""Indication normalizer v0 (FCV-204).

Maps free-form indication strings (en/fr/de/es) → ICD-11 codes using the
WHO ICD-11 Coding Tool API with ICTM TM2 fallback.

Flow:
    1. Normalize input text (lowercase, strip, transliterate accents).
    2. Try exact match against local ``indications_map`` (fast path).
    3. Try WHO ICD-11 Coding Tool API (``/icd/release/11/*/mms/search``).
    4. If no match → try ICTM TM2 codes from ``taxa_aliases`` table.
    5. If no match → return None (caller stores raw string in
       ``indications_native``, leaves ``indications_normalized`` empty).

WHO ICD API: requires OAuth2 token from https://icdaccessmanagement.who.int/
Environment vars:
    - ``ICD_CLIENT_ID``
    - ``ICD_CLIENT_SECRET``

Rate limit: 1 req/sec (WHO API is lenient but undocumented).
Caches results in ``cache_entries`` with scraper_id='indication_norm'.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

import asyncpg
import httpx

from ..logger import get_logger
from ..resolvers._rate_limit import TokenBucket
from ..services import cache, cassettes
from ..services.cassettes import CassetteMissError

logger = get_logger(__name__)

SCRAPER_ID = "indication_norm"
ICD_API_BASE = "https://id.who.int"
ICD_TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
ICD_SEARCH_URL = f"{ICD_API_BASE}/icd/release/11/2024-01/mms/search"

# Common indication mappings (fast local path).
# Maps normalized indication text → ICD-11 code.
_LOCAL_MAP: dict[str, str] = {
    "headache": "8A80",
    "migraine": "8A80.0",
    "nausea": "MD90.0",
    "vomiting": "MD90.1",
    "insomnia": "7A00",
    "anxiety": "6B00",
    "depression": "6A70",
    "hypertension": "BA00",
    "diabetes": "5A10",
    "diabetes mellitus": "5A10",
    "cough": "MD12",
    "common cold": "CA00",
    "influenza": "1E30",
    "diarrhea": "MD91.0",
    "diarrhoea": "MD91.0",
    "constipation": "MD31.0",
    "pain": "MG30",
    "chronic pain": "MG30.0",
    "arthritis": "FA20",
    "rheumatoid arthritis": "FA21",
    "osteoarthritis": "FA01",
    "inflammation": "4A44",
    "fever": "MG26",
    "fatigue": "MG22",
    "asthma": "CA23",
    "bronchitis": "CA20",
    "eczema": "EA80",
    "dermatitis": "EA80",
    "urinary tract infection": "GC08",
    "dyspepsia": "MD30.0",
    "gastritis": "DA42",
    "peptic ulcer": "DA43",
    "menstrual pain": "GA34.3",
    "dysmenorrhea": "GA34.3",
    "menopausal symptoms": "GA31",
    "benign prostatic hyperplasia": "GA90.0",
    "erectile dysfunction": "HA01",
    "hepatitis": "DB90",
    "liver disease": "DB90",
    "wound healing": "EH90",
    "burns": "NF0Y",
    "allergic rhinitis": "CA08",
    "sinusitis": "CA01",
    "tinnitus": "AB5Y",
    "vertigo": "AB31",
    "obesity": "5B81",
    "hyperlipidemia": "5C80",
    "hypercholesterolemia": "5C80",
    "anemia": "3A00",
    "anaemia": "3A00",
    # ── German (DE) ──────────────────────────────────────────────
    "kopfschmerzen": "8A80",
    "migrane": "8A80.0",
    "ubelkeit": "MD90.0",
    "schlaflosigkeit": "7A00",
    "angst": "6B00",
    "husten": "MD12",
    "durchfall": "MD91.0",
    "verstopfung": "MD31.0",
    "fieber": "MG26",
    "gelenkschmerzen": "ME82",
    "bluthochdruck": "BA00",
    "entzundung": "4A44",
    "asthma bronchiale": "CA23",
    "ekzem": "EA80",
    # ── French (FR) ──────────────────────────────────────────────
    "cephalee": "8A80",
    "mal de tete": "8A80",
    "nausee": "MD90.0",
    "insomnie": "7A00",
    "anxiete": "6B00",
    "toux": "MD12",
    "diarrhee": "MD91.0",
    "fievre": "MG26",
    "douleur articulaire": "ME82",
    "hypertension arterielle": "BA00",
    "diabete": "5A10",
    "bronchite": "CA20",
    # ── Spanish (ES) ─────────────────────────────────────────────
    "dolor de cabeza": "8A80",
    "nauseas": "MD90.0",
    "insomnio": "7A00",
    "ansiedad": "6B00",
    "tos": "MD12",
    "diarrea": "MD91.0",
    "estrenimiento": "MD31.0",
    "dolor articular": "ME82",
    "hipertension": "BA00",
    "inflamacion": "4A44",
    "obesidad": "5B81",
    "artritis": "FA20",
    # ── Chinese (ZH) — pinyin for local map matching ─────────────
    "tou tong": "8A80",  # headache
    "shi mian": "7A00",  # insomnia
    "fa re": "MG26",  # fever
    "ke sou": "MD12",  # cough
    "fu xie": "MD91.0",  # diarrhea
    "gao xue ya": "BA00",  # hypertension
    "tang niao bing": "5A10",  # diabetes
    "guan jie yan": "FA20",  # arthritis
    "qi guan yan": "CA20",  # bronchitis
    "xiao chuan": "CA23",  # asthma
}


def _normalize_text(text: str) -> str:
    """Normalize indication text for matching."""
    # Remove accents.
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase + strip + collapse whitespace.
    clean = re.sub(r"\s+", " ", ascii_text.lower().strip())
    # Remove common noise words.
    clean = re.sub(r"\b(for|of|the|and|or|with|to|in)\b", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


class IndicationNormalizer:
    """Maps free-form indications to ICD-11 codes."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rate_per_sec: float = 1.0,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._bucket = TokenBucket(rate_per_sec, capacity=2)
        self._token: str | None = None
        self._token_expires: float = 0.0

    async def __aenter__(self) -> IndicationNormalizer:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ─── Public API ────────────────────────────────────────────
    async def normalize(
        self,
        indication: str,
        pool: asyncpg.Pool | None = None,
        *,
        lang: str = "en",
    ) -> NormResult:
        """Normalize a single indication string.

        Returns NormResult with code and source. Code is None if no match.
        """
        text = _normalize_text(indication)
        if not text:
            return NormResult(original=indication, code=None, source="empty")

        # Step 1: Local map (instant).
        code = _LOCAL_MAP.get(text)
        if code:
            return NormResult(original=indication, code=code, source="local_map")

        # Step 2: Cache check.
        if pool:
            cache_key = cache.make_key(SCRAPER_ID, {"text": text, "lang": lang})
            cached = await cache.get(pool, cache_key, scraper_id=SCRAPER_ID)
            if cached is not None:
                return NormResult(
                    original=indication,
                    code=cached.get("code"),
                    source=cached.get("source", "cache"),
                )

        # Step 3: WHO ICD-11 API.
        icd_code = await self._search_icd(text, lang)
        if icd_code:
            result = NormResult(original=indication, code=icd_code, source="who_icd_api")
            if pool:
                await self._cache_result(pool, text, lang, result)
            return result

        # Step 4: ICTM TM2 fallback (search taxa_aliases for TM2-like codes).
        if pool:
            tm2_code = await self._search_ictm(pool, text)
            if tm2_code:
                result = NormResult(original=indication, code=tm2_code, source="ictm_tm2")
                await self._cache_result(pool, text, lang, result)
                return result

        # Step 5: No match.
        result = NormResult(original=indication, code=None, source="no_match")
        if pool:
            await self._cache_result(pool, text, lang, result)
        logger.debug("indication_norm.no_match", text=text, lang=lang)
        return result

    async def normalize_batch(
        self,
        indications: list[str],
        pool: asyncpg.Pool | None = None,
        *,
        lang: str = "en",
    ) -> list[NormResult]:
        """Normalize a list of indications."""
        return [await self.normalize(ind, pool, lang=lang) for ind in indications]

    # ─── WHO ICD-11 API ────────────────────────────────────────
    async def _get_token(self) -> str | None:
        """Obtain OAuth2 token for WHO ICD API."""
        import time

        if self._token and time.time() < self._token_expires:
            return self._token

        client_id = os.getenv("ICD_CLIENT_ID")
        client_secret = os.getenv("ICD_CLIENT_SECRET")
        if not client_id or not client_secret:
            return None

        assert self._client is not None  # noqa: S101
        try:
            resp = await self._client.post(
                ICD_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                    "scope": "icdapi_access",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                self._token = data.get("access_token")
                self._token_expires = time.time() + data.get("expires_in", 3600) - 60
                return self._token
        except httpx.HTTPError as exc:
            logger.warning("indication_norm.token_error", error=str(exc))
        return None

    async def _search_icd(self, text: str, lang: str) -> str | None:
        """Search WHO ICD-11 coding tool API."""
        request = {"method": "GET", "url": ICD_SEARCH_URL, "params": {"q": text, "lang": lang}}
        mode = cassettes.get_mode()
        if mode == "replay":
            try:
                resp_data = cassettes.replay(SCRAPER_ID, request)
            except CassetteMissError:
                return None
            return self._extract_icd_code(resp_data)

        token = await self._get_token()
        if not token:
            # No credentials — skip API call (dev/CI mode).
            return None

        await self._bucket.acquire()
        assert self._client is not None  # noqa: S101
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Language": lang,
                "API-Version": "v2",
            }
            resp = await self._client.get(
                ICD_SEARCH_URL,
                params={"q": text, "subtreeFilterUsesFoundationDescendants": "false"},
                headers=headers,
            )
            body: dict[str, Any] = {
                "status": resp.status_code,
                "json": resp.json() if resp.status_code == 200 else None,
            }
            if mode == "record":
                cassettes.record(SCRAPER_ID, request, body)
            return self._extract_icd_code(body)
        except httpx.HTTPError as exc:
            logger.warning("indication_norm.icd_search_error", error=str(exc))
            return None

    def _extract_icd_code(self, resp: dict[str, Any]) -> str | None:
        """Extract the best ICD-11 code from search results."""
        if resp.get("status") != 200:
            return None
        data = resp.get("json") or {}
        entities = data.get("destinationEntities") or []
        if not entities:
            return None
        # Take the first (highest-scoring) match.
        entity = entities[0]
        # The ICD API returns a theCode field or we can extract from the ID.
        code = entity.get("theCode")
        if code:
            return str(code)
        # Fallback: extract from stem URI.
        stem = entity.get("id") or ""
        if "/" in stem:
            return stem.rstrip("/").split("/")[-1]
        return None

    # ─── ICTM TM2 fallback ────────────────────────────────────
    async def _search_ictm(self, pool: asyncpg.Pool, text: str) -> str | None:
        """Search taxa_aliases for TM2-equivalent indication codes."""
        # Look for aliases that match the indication text.
        # TM2 codes are stored with source='ictm' in taxa_aliases.
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT source_record_id
                  FROM taxa_aliases
                 WHERE LOWER(alias_name) = $1
                   AND source = 'ictm'
                 LIMIT 1
                """,
                text.lower(),
            )
        if row and row["source_record_id"]:
            return str(row["source_record_id"])
        return None

    # ─── Cache helpers ─────────────────────────────────────────
    async def _cache_result(
        self, pool: asyncpg.Pool, text: str, lang: str, result: NormResult
    ) -> None:
        cache_key = cache.make_key(SCRAPER_ID, {"text": text, "lang": lang})
        await cache.set(
            pool,
            cache_key,
            scraper_id=SCRAPER_ID,
            query_payload={"text": text, "lang": lang},
            response_payload={"code": result.code, "source": result.source},
        )


class NormResult:
    """Result of indication normalization."""

    __slots__ = ("original", "code", "source")

    def __init__(self, original: str, code: str | None, source: str) -> None:
        self.original = original
        self.code = code
        self.source = source

    def __repr__(self) -> str:
        return f"NormResult(code={self.code!r}, source={self.source!r})"

    def to_dict(self) -> dict[str, Any]:
        return {"original": self.original, "code": self.code, "source": self.source}


__all__ = ["IndicationNormalizer", "NormResult", "SCRAPER_ID"]
