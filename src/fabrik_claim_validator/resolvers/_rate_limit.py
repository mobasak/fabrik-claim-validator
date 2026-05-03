"""Shared async token-bucket rate limiter (used by Sprint 1 resolvers).

Kept here (not in `services/`) because rate-limiting is a resolver concern —
scrapers use the captcha/proxy wrappers + budget module for their flow
control, not this limiter.

Design: classic token bucket. Capacity = burst allowance. Refill rate
enforces the steady-state limit. Acquiring blocks (sleeps) until a token is
available; never raises.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """Async token bucket. Thread-unsafe — one instance per event loop."""

    def __init__(self, rate_per_sec: float, capacity: int | None = None) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        self.rate = rate_per_sec
        self.capacity = float(capacity if capacity is not None else max(1, int(rate_per_sec)))
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Block until ``tokens`` are available, then consume them."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last_refill = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit / self.rate
            await asyncio.sleep(wait)
