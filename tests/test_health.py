"""Health endpoint tests."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from fabrik_claim_validator.main import app

client = TestClient(app)


def test_health_returns_200_without_db():
    """Health returns 200 when DB is not configured."""
    with patch.dict(os.environ, {}, clear=True):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "fabrik-claim-validator"
        assert data["status"] == "ok"
        assert data["dependencies"]["database"] == "not_configured"


def test_health_returns_200_with_db_configured():
    """Health returns 200 when DB is configured (mocked)."""
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test@localhost/test"}):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["dependencies"]["database"] == "configured"


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
