"""Residential-proxy client (FCV-006).

HTTP wrapper around the ``/opt/proxy`` service. We do NOT directly import
its ``ProxyClient`` Python class because its module layout (and the
underlying ``DbProxyManager`` Postgres-backed singleton) is private to that
project; we hit the documented HTTP API instead.

Worker-id sticky-session model (per plan §0):

- ``acquire(service_name, worker_id)`` — returns a proxy URL bound to that
  worker for at least ``min_reuse_interval`` (set per-tradition).
- ``mark_success(proxy, response_time_ms)`` / ``mark_failure(proxy, error_type)``
  — feeds back to the proxy manager's health scoring.

URL configurable via ``PROXY_URL`` env var.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class ProxyError(RuntimeError):
    """Raised when the proxy service returns a non-success status."""


class ProxyClient:
    """Async HTTP wrapper around the proxy-management service."""

    def __init__(
        self,
        service_name: str,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.service_name = service_name
        url = base_url if base_url is not None else os.getenv("PROXY_URL", "http://localhost:18013")
        self.base_url = url.rstrip("/")
        self.timeout = timeout

    async def acquire(self, worker_id: int | None = None) -> dict[str, Any]:
        """Acquire a proxy for this service. Returns ``{proxy_url, worker_id, ...}``.

        Caller passes the same ``worker_id`` on subsequent acquires to keep
        the sticky session.
        """
        body: dict[str, Any] = {"service_name": self.service_name}
        if worker_id is not None:
            body["worker_id"] = worker_id
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/proxy/acquire", json=body)
        if resp.status_code >= 400:
            raise ProxyError(f"acquire HTTP {resp.status_code}: {resp.text[:200]}")
        result: dict[str, Any] = resp.json()
        return result

    async def mark_success(self, proxy_url: str, response_time_ms: int) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await client.post(
                f"{self.base_url}/proxy/feedback",
                json={
                    "service_name": self.service_name,
                    "proxy_url": proxy_url,
                    "outcome": "success",
                    "response_time_ms": response_time_ms,
                },
            )

    async def mark_failure(self, proxy_url: str, error_type: str) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await client.post(
                f"{self.base_url}/proxy/feedback",
                json={
                    "service_name": self.service_name,
                    "proxy_url": proxy_url,
                    "outcome": "failure",
                    "error_type": error_type,
                },
            )

    async def health(self) -> dict[str, Any]:
        """Liveness probe; never raises."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
            return {"ok": resp.status_code == 200, "status_code": resp.status_code}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}
