"""PubChem PUG-REST resolver (FCV-101).

Public API, no key. Endpoints used:

- name → CID:        ``/compound/name/<q>/cids/JSON``
- CAS → CID:         ``/compound/xref/RegistryID/<cas>/cids/JSON``
- InChIKey → CID:    ``/compound/inchikey/<key>/cids/JSON``
- CID → properties:  ``/compound/cid/<cid>/property/<props>/JSON``
- CID → synonyms:    ``/compound/cid/<cid>/synonyms/JSON``  (for CAS)

Politeness: 5 requests per second, burst 5 (``TokenBucket(5, 5)``). PubChem
publishes a soft 5 rps / 400 req/min limit; we stay under both.

Offline CI: every ``_get`` call is routed through ``services.cassettes``
when ``CASSETTE_MODE!=passthrough``.
"""

from __future__ import annotations

from typing import Any

import asyncpg
import httpx

from ..services import cassettes
from ._rate_limit import TokenBucket

BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
SCRAPER_ID = "pubchem"
_PROPS = (
    "MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,IUPACName,Title"
)


class PubChemResolver:
    """Async PubChem client. One instance per event loop (owns the bucket)."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rate_per_sec: float = 5.0,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._bucket = TokenBucket(rate_per_sec, capacity=int(rate_per_sec))

    async def __aenter__(self) -> PubChemResolver:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
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
            "json": resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else None,
            "text": None
            if resp.headers.get("content-type", "").startswith("application/json")
            else resp.text,
        }
        if mode == "record":
            cassettes.record(SCRAPER_ID, request, body)
        return body

    # ───────────── Lookup: identifier → CID ────────────────────
    async def cid_from_name(self, name: str) -> int | None:
        resp = await self._get(f"/compound/name/{name}/cids/JSON")
        return _first_cid(resp)

    async def cid_from_cas(self, cas: str) -> int | None:
        resp = await self._get(f"/compound/xref/RegistryID/{cas}/cids/JSON")
        return _first_cid(resp)

    async def cid_from_inchikey(self, inchikey: str) -> int | None:
        resp = await self._get(f"/compound/inchikey/{inchikey}/cids/JSON")
        return _first_cid(resp)

    # ───────────── CID → canonical record ──────────────────────
    async def properties(self, cid: int) -> dict[str, Any] | None:
        """Return normalised property dict or None if upstream 404."""
        resp = await self._get(f"/compound/cid/{cid}/property/{_PROPS}/JSON")
        if resp.get("status") != 200:
            return None
        payload = resp.get("json") or {}
        rows = payload.get("PropertyTable", {}).get("Properties") or []
        if not rows:
            return None
        row = rows[0]
        return {
            "pubchem_cid": cid,
            "canonical_name": row.get("Title") or row.get("IUPACName") or "",
            "iupac_name": row.get("IUPACName"),
            "inchi": row.get("InChI"),
            "inchi_key": row.get("InChIKey"),
            "smiles": row.get("IsomericSMILES") or row.get("CanonicalSMILES"),
            "molecular_formula": row.get("MolecularFormula"),
            "molecular_weight": _as_float(row.get("MolecularWeight")),
        }

    async def cas_number(self, cid: int) -> str | None:
        """Pull the first CAS-looking synonym for the CID (best-effort)."""
        resp = await self._get(f"/compound/cid/{cid}/synonyms/JSON")
        payload = resp.get("json") or {}
        info = payload.get("InformationList", {}).get("Information") or []
        if not info:
            return None
        for syn in info[0].get("Synonym") or []:
            if _looks_like_cas(syn):
                return str(syn)
        return None

    # ───────────── Persistence ─────────────────────────────────
    async def upsert(self, pool: asyncpg.Pool, cid: int) -> dict[str, Any] | None:
        """Resolve + upsert into ``compounds``. Returns the stored row dict."""
        props = await self.properties(cid)
        if props is None:
            return None
        props["cas_number"] = await self.cas_number(cid)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO compounds (
                    pubchem_cid, canonical_name, iupac_name, inchi, inchi_key,
                    smiles, molecular_formula, molecular_weight, cas_number,
                    fetched_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9, NOW())
                ON CONFLICT (pubchem_cid) DO UPDATE SET
                    canonical_name    = EXCLUDED.canonical_name,
                    iupac_name        = EXCLUDED.iupac_name,
                    inchi             = EXCLUDED.inchi,
                    inchi_key         = EXCLUDED.inchi_key,
                    smiles            = EXCLUDED.smiles,
                    molecular_formula = EXCLUDED.molecular_formula,
                    molecular_weight  = EXCLUDED.molecular_weight,
                    cas_number        = EXCLUDED.cas_number,
                    fetched_at        = NOW()
                """,
                props["pubchem_cid"],
                props["canonical_name"],
                props["iupac_name"],
                props["inchi"],
                props["inchi_key"],
                props["smiles"],
                props["molecular_formula"],
                props["molecular_weight"],
                props["cas_number"],
            )
        return props


# ───────────── Helpers ────────────────────────────────────────
def _first_cid(resp: dict[str, Any]) -> int | None:
    if resp.get("status") != 200:
        return None
    payload = resp.get("json") or {}
    cids = payload.get("IdentifierList", {}).get("CID") or []
    return int(cids[0]) if cids else None


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _looks_like_cas(s: str) -> bool:
    """CAS numbers have the shape ``<digits 2-7>-<2 digits>-<1 digit>``."""
    parts = s.split("-")
    if len(parts) != 3:
        return False
    a, b, c = parts
    return (
        a.isdigit()
        and 2 <= len(a) <= 7
        and b.isdigit()
        and len(b) == 2
        and c.isdigit()
        and len(c) == 1
    )


__all__ = ["PubChemResolver", "SCRAPER_ID", "BASE_URL"]
