"""Sibling ``fabrik-citation-verifier`` HTTP client (FCV-007).

Single concern: turn a citation reference (DOI/PMID/title) into a verified
record (Tier A/B/C, snippet, retraction status). The verifier handles the
13-resolver waterfall + caching internally — we just call ``/verify``.

URL via ``CITATION_VERIFIER_URL`` env var (defaults to ``http://localhost:8032``).

Failure mode is explicit: if the verifier is unreachable / returns 5xx, we
return ``{verified: False, error: 'verifier_unreachable'}`` rather than
raising — the aggregator must keep going on the other evidence sources.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class CitationVerifierClient:
    """Async client for the citation-verifier service."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        url = (
            base_url
            if base_url is not None
            else os.getenv("CITATION_VERIFIER_URL", "http://localhost:8032")
        )
        self.base_url = url.rstrip("/")
        self.timeout = timeout

    async def verify(self, **kwargs: Any) -> dict[str, Any]:
        """Verify a single citation. Forwards kwargs to ``POST /verify``.

        Common kwargs: ``doi``, ``pmid``, ``title``, ``authors``, ``year``,
        ``lang_hint``. See verifier API docs for full schema.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/verify", json=kwargs)
        except httpx.HTTPError as exc:
            return {"verified": False, "error": "verifier_unreachable", "detail": str(exc)}
        if resp.status_code >= 500:
            return {
                "verified": False,
                "error": "verifier_unreachable",
                "status_code": resp.status_code,
            }
        if resp.status_code >= 400:
            return {
                "verified": False,
                "error": "verifier_rejected",
                "status_code": resp.status_code,
                "detail": resp.text[:500],
            }
        result: dict[str, Any] = resp.json()
        return result

    async def verify_batch(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        """Verify up to ~100 citations in parallel via ``POST /verify/batch``."""
        try:
            async with httpx.AsyncClient(timeout=max(self.timeout, 180.0)) as client:
                resp = await client.post(
                    f"{self.base_url}/verify/batch", json={"citations": citations}
                )
        except httpx.HTTPError as exc:
            return {"verified": False, "error": "verifier_unreachable", "detail": str(exc)}
        if resp.status_code >= 400:
            return {
                "verified": False,
                "error": "verifier_unreachable",
                "status_code": resp.status_code,
            }
        batch_result: dict[str, Any] = resp.json()
        return batch_result

    async def health(self) -> dict[str, Any]:
        """Liveness probe; never raises."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
            return {"ok": resp.status_code == 200, "status_code": resp.status_code}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}
