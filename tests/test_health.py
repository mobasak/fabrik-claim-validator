"""Health endpoint tests."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from fabrik_claim_validator.main import app

client = TestClient(app)


def test_health_returns_503_without_db():
    """Health returns 503 when DB is unreachable — .windsurfrules requires
    health endpoints to test real deps, not just acknowledge configuration.
    """
    with patch.dict(os.environ, {}, clear=True):
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["service"] == "fabrik-claim-validator"
        assert data["status"] == "degraded"
        assert data["dependencies"]["database"] == "not_configured"


def test_health_returns_503_when_db_url_set_but_unreachable():
    """With a bogus DSN, the lifespan still boots but /health surfaces the
    DB error and returns 503 — critical-dep failures must not 200.
    """
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://nope@127.0.0.1:1/x"}):
        # Use a fresh TestClient so the lifespan re-runs with the patched env.
        from fastapi.testclient import TestClient

        with TestClient(app) as fresh_client:
            response = fresh_client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["dependencies"]["database"] != "ok"


def test_root_endpoint():
    """Root endpoint returns welcome message."""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()


def test_health_returns_correlation_id():
    """Health response includes X-Request-ID header."""
    response = client.get("/health")
    assert "x-request-id" in response.headers


def test_health_preserves_provided_request_id():
    """Health response preserves client-provided X-Request-ID."""
    response = client.get("/health", headers={"X-Request-ID": "test-123"})
    assert response.headers["x-request-id"] == "test-123"
