"""Captcha-solver client (FCV-006).

Wraps the ``/opt/captcha`` HTTP service. We do NOT ``import captcha.client``
directly — that would couple us to another project's source layout. Instead
we hit its documented HTTP contract (per plan §0):

- ``POST /api/v1/solve-sync``  — blocking solve, returns ``{token}``
- ``GET  /api/v1/balance``     — Anti-Captcha credits remaining
- ``GET  /health``             — liveness + provider status

URL is configured via ``CAPTCHA_URL`` env var. Defaults to the WSL-dev
local instance (``http://localhost:18011``); override on VPS via Coolify.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class CaptchaError(RuntimeError):
    """Raised when the captcha service returns a non-success status."""


class CaptchaClient:
    """Async HTTP wrapper around the captcha service."""

    def __init__(self, base_url: str | None = None, timeout: float = 200.0) -> None:
        url = (
            base_url if base_url is not None else os.getenv("CAPTCHA_URL", "http://localhost:18011")
        )
        self.base_url = url.rstrip("/")
        self.api_url = f"{self.base_url}/api/v1"
        self.timeout = timeout

    async def solve_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Block until captcha solved; returns the upstream response body.

        ``payload`` is forwarded verbatim to the upstream service — see
        ``/opt/captcha`` API docs for the per-captcha-type schema.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.api_url}/solve-sync", json=payload)
        if resp.status_code >= 400:
            raise CaptchaError(f"solve-sync HTTP {resp.status_code}: {resp.text[:200]}")
        result: dict[str, Any] = resp.json()
        return result

    async def balance(self) -> dict[str, Any]:
        """Return remaining Anti-Captcha credits (and provider status)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.api_url}/balance")
        if resp.status_code >= 400:
            raise CaptchaError(f"balance HTTP {resp.status_code}: {resp.text[:200]}")
        balance_result: dict[str, Any] = resp.json()
        return balance_result

    async def health(self) -> dict[str, Any]:
        """Liveness probe; never raises — returns ``{ok: bool, ...}`` shape."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
            return {"ok": resp.status_code == 200, "status_code": resp.status_code}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}
