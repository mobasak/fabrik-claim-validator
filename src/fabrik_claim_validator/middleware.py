"""Correlation ID middleware for fabrik-claim-validator.

Binds X-Request-ID to structlog context via contextvars.
Usage: app.add_middleware(CorrelationMiddleware)
"""

import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Attach X-Request-ID to every request and bind to structlog context."""

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        """Process request with correlation ID."""
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        correlation_id.set(req_id)
        structlog.contextvars.bind_contextvars(correlation_id=req_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response  # type: ignore[no-any-return]
        finally:
            structlog.contextvars.unbind_contextvars("correlation_id")
