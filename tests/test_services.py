"""One-Test-Rule regressions for Sprint 0 services FCV-003..010.

Each test exercises the highest-risk path of one ticket. DB-backed tests
use the ``pool`` fixture (skipped without ``DATABASE_URL``).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from fabrik_claim_validator.services import (
    budget,
    cache,
    cassettes,
    discovery_cache,
    ingest_log,
)
from fabrik_claim_validator.services.captcha import CaptchaClient
from fabrik_claim_validator.services.citation_verifier import CitationVerifierClient
from fabrik_claim_validator.services.proxy import ProxyClient

from .conftest import pg_required


# ─── FCV-003: cache write → read → expire → re-read ─────────────────────
@pg_required
async def test_cache_write_read_expire(pool):
    key = cache.make_key("test_scraper", {"q": "ginseng"})
    await cache.set(
        pool,
        key,
        scraper_id="test_scraper",
        query_payload={"q": "ginseng"},
        response_payload={"hits": 7},
        ttl=timedelta(seconds=60),
    )
    hit = await cache.get(pool, key, scraper_id="test_scraper")
    assert hit == {"hits": 7}

    # Force-expire by overwriting expires_at, then re-read returns None.
    async with pool.acquire() as conn:
        await conn.execute("UPDATE cache_entries SET expires_at = NOW() - INTERVAL '1 minute'")
    miss = await cache.get(pool, key, scraper_id="test_scraper")
    assert miss is None

    swept = await cache.sweep_expired(pool)
    assert swept == 1


# ─── FCV-004: discovery_cache invalidate_by_indication flips the flag ──
@pg_required
async def test_discovery_cache_invalidate_by_indication(pool):
    key = discovery_cache.make_key("8B20", {"min_traditions": 3})
    await discovery_cache.set(
        pool,
        key,
        indication="8B20",
        request_payload={"min_traditions": 3},
        response_payload={"substances": ["ginseng"]},
    )
    assert await discovery_cache.get(pool, key) == {"substances": ["ginseng"]}

    flipped = await discovery_cache.invalidate_by_indication(pool, "8B20")
    assert flipped == 1
    assert await discovery_cache.get(pool, key) is None  # invalidated row treated as miss


# ─── FCV-005: cassette record→replay round-trip + miss raises ──────────
def test_cassette_record_then_replay(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CASSETTE_DIR", str(tmp_path))
    request = {"method": "GET", "url": "https://example.test/herbs/ginseng"}
    response = {"status": 200, "json": {"name": "Panax ginseng"}}

    written = cassettes.record("test_scraper", request, response)
    assert written.exists()

    replayed = cassettes.replay("test_scraper", request)
    assert replayed == response

    with pytest.raises(cassettes.CassetteMissError):
        cassettes.replay("test_scraper", {"method": "GET", "url": "no/such/path"})


# ─── FCV-006: captcha + proxy clients return structured health on outage ─
async def test_captcha_health_unreachable_does_not_raise(monkeypatch):
    # Point at a port nothing listens on; client must return ok=False, not raise.
    monkeypatch.setenv("CAPTCHA_URL", "http://127.0.0.1:1")
    result = await CaptchaClient().health()
    assert result["ok"] is False
    assert "error" in result


async def test_proxy_health_unreachable_does_not_raise(monkeypatch):
    monkeypatch.setenv("PROXY_URL", "http://127.0.0.1:1")
    result = await ProxyClient(service_name="test").health()
    assert result["ok"] is False


# ─── FCV-007: citation-verifier client returns verifier_unreachable on 5xx ─
async def test_citation_verifier_unreachable_returns_structured_error(monkeypatch):
    monkeypatch.setenv("CITATION_VERIFIER_URL", "http://127.0.0.1:1")
    result = await CitationVerifierClient().verify(doi="10.0/test")
    assert result["verified"] is False
    assert result["error"] == "verifier_unreachable"


# ─── FCV-010: budget hard-stop + @track_fetch consumes & logs ──────────
@pg_required
async def test_budget_hard_stop_raises_and_decorator_logs(pool, monkeypatch):
    monkeypatch.setenv("PROXY_DAILY_BUDGET_BYTES", "1000")

    @ingest_log.track_fetch("tcm", "test_scraper")
    async def fake_fetch(*, pool, kb):
        return {"bytes": kb * 1000, "http_status": 200, "request_url": "http://t.test"}

    # First call within budget OK.
    result = await fake_fetch(pool=pool, kb=1)
    assert result["bytes"] == 1000

    # Second call: previous call already consumed the full budget -> hard stop.
    with pytest.raises(budget.ProxyBudgetExceeded):
        await fake_fetch(pool=pool, kb=1)

    # ingest_log row exists for the successful call (track_fetch records before raising).
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT scraper_id, http_status, error_class FROM ingest_log")
    assert any(r["scraper_id"] == "test_scraper" for r in rows)


# ─── FCV-009: MCP server registers 5 stub tools ────────────────────────
async def test_mcp_server_exposes_five_stub_tools():
    from mcp_server.server import mcp

    tool_list = await mcp.list_tools()
    names = {t.name for t in tool_list}
    assert names == {
        "validate_claim",
        "discover_substance",
        "tradition_health",
        "validator_health",
        "check_proxy_budget",
    }


# ─── FCV-008: /health/scraping_infra + /health/proxy_budget endpoints ──
def test_health_scraping_infra_and_proxy_budget_endpoints(monkeypatch):
    """Routes are registered; with no upstream they return 503 (degraded)."""
    monkeypatch.setenv("CAPTCHA_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("PROXY_URL", "http://127.0.0.1:1")
    from fastapi.testclient import TestClient

    from fabrik_claim_validator.main import app

    with TestClient(app) as client:
        r = client.get("/health/scraping_infra")
        assert r.status_code == 503
        body = r.json()
        assert body["captcha"]["ok"] is False
        assert body["proxy"]["ok"] is False

        # When DB pool is None (no DATABASE_URL), endpoint returns 503 with error.
        r2 = client.get("/health/proxy_budget")
        assert r2.status_code in (200, 503)  # 200 if pool came up, 503 otherwise
        assert r2.json()  # non-empty
