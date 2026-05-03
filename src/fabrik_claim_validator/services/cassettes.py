"""Test cassette infrastructure (FCV-005, plan §9).

Three modes governed by env var ``CASSETTE_MODE``:

- ``replay`` (default in CI): every HTTP-fetch helper call must hit a
  pre-recorded fixture; cache miss raises so tests can never silently
  exercise the network.
- ``record``: live fetch + write cassette JSON, then return the response.
- ``passthrough``: live fetch, no read/write (used for ad-hoc dev runs).

Cassette layout:  ``tests/cassettes/<scraper_id>/<query_hash>.json``

Each cassette JSON has a fixed shape:

```json
{
  "scraper_id": "ema_hmpc",
  "request":  {"method": "GET", "url": "...", "params": {...}, "body": null},
  "response": {"status": 200, "headers": {...}, "json": {...}, "text": null},
  "recorded_at": "2026-05-03T10:00:00Z"
}
```

The recorder/replayer are HTTP-method agnostic — the scraper supplies the
``scraper_id`` and the canonical request payload; the helper hashes both
deterministically into the filename.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

CassetteMode = Literal["record", "replay", "passthrough"]


class CassetteMissError(LookupError):
    """Raised when ``replay`` mode finds no fixture for a request."""


def get_mode() -> CassetteMode:
    raw = os.getenv("CASSETTE_MODE", "replay").lower()
    if raw not in {"record", "replay", "passthrough"}:
        raise ValueError(f"Invalid CASSETTE_MODE={raw!r}")
    return raw  # type: ignore[return-value]


def _cassette_dir() -> Path:
    return Path(os.getenv("CASSETTE_DIR", "tests/cassettes")).resolve()


def _request_hash(scraper_id: str, request: dict[str, Any]) -> str:
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{scraper_id}|{canonical}".encode()).hexdigest()[:16]


def cassette_path(scraper_id: str, request: dict[str, Any]) -> Path:
    """Resolve the on-disk cassette path for a scraper + request payload."""
    digest = _request_hash(scraper_id, request)
    return _cassette_dir() / scraper_id / f"{digest}.json"


def replay(scraper_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Load a fixture; raise ``CassetteMissError`` when missing."""
    path = cassette_path(scraper_id, request)
    if not path.exists():
        raise CassetteMissError(
            f"No cassette for scraper={scraper_id!r} at {path} "
            f"(run with CASSETTE_MODE=record to capture)"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    response: dict[str, Any] = payload["response"]
    return response


def record(
    scraper_id: str,
    request: dict[str, Any],
    response: dict[str, Any],
) -> Path:
    """Write a cassette to disk; returns the path. Creates parent dirs."""
    path = cassette_path(scraper_id, request)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scraper_id": scraper_id,
        "request": request,
        "response": response,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
