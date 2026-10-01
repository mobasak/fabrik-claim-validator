"""
Canonical internal token auth — shared across all Fabrik Python services.
Header:  X-Internal-Token
Env var: SERVICE_INTERNAL_SECRET_KEY
"""
import hmac
import os

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

_HEADER = APIKeyHeader(name="X-Internal-Token", auto_error=False)


def require_internal_token(token: str = Security(_HEADER)) -> str:
    """FastAPI dependency — validates X-Internal-Token in constant time."""
    expected = os.getenv("SERVICE_INTERNAL_SECRET_KEY", "")
    if not token or not expected:
        raise HTTPException(status_code=403, detail="Missing or invalid token")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Missing or invalid token")
    return token
