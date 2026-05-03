"""Main entry point for fabrik-claim-validator (FCV-008).

Responsibilities:

- Manage the asyncpg pool lifecycle on app startup/shutdown.
- Expose ``/health`` (db + verifier + captcha + proxy reachability),
  ``/health/scraping_infra`` (captcha + proxy detail), and
  ``/health/proxy_budget`` (today's budget row).
- Apply correlation-ID middleware so every request gets a traceable id.

Schema-changing work and the validator/discovery endpoints are owned by
later sprints (FCV-507/508). This module stays small and dependency-injects
the pool via ``app.state.pool`` instead of using globals.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from fabrik_claim_validator import db as db_module
from fabrik_claim_validator.logger import get_logger
from fabrik_claim_validator.middleware import CorrelationMiddleware
from fabrik_claim_validator.services import budget as budget_service
from fabrik_claim_validator.services.captcha import CaptchaClient
from fabrik_claim_validator.services.citation_verifier import CitationVerifierClient
from fabrik_claim_validator.services.proxy import ProxyClient

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the asyncpg pool at startup; close it at shutdown.

    Pool creation failures are logged and the app boots without a pool —
    ``/health`` will then surface ``database: not_configured`` and return 503.
    This keeps liveness probes useful even when the DB is unreachable.
    """
    logger.info("service_starting", port=os.getenv("PORT", "8002"))
    app.state.pool = None
    if os.getenv("DATABASE_URL"):
        try:
            app.state.pool = await db_module.create_pool()
            logger.info("db_pool_ready")
        except Exception as exc:  # noqa: BLE001 — surface to /health, not to logs only
            logger.error("db_pool_failed", error=str(exc))
    yield
    if app.state.pool is not None:
        await app.state.pool.close()
        logger.info("db_pool_closed")
    logger.info("service_stopping")


app = FastAPI(title="fabrik-claim-validator", lifespan=lifespan)
app.add_middleware(CorrelationMiddleware)


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Aggregate health: db + verifier + captcha + proxy. 503 if DB is down."""
    deps: dict[str, str] = {}
    all_critical_ok = True

    # Database — CRITICAL: failure -> 503.
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        deps["database"] = "not_configured"
        all_critical_ok = False
    else:
        try:
            ok = await db_module.ping(pool)
            deps["database"] = "ok" if ok else "error: ping_failed"
            all_critical_ok = all_critical_ok and ok
        except Exception as exc:  # noqa: BLE001
            deps["database"] = f"error: {exc}"
            all_critical_ok = False

    # Verifier / captcha / proxy — non-critical: surface status, don't 503.
    verifier_health = await CitationVerifierClient().health()
    deps["verifier"] = "ok" if verifier_health.get("ok") else "unreachable"
    captcha_health = await CaptchaClient().health()
    deps["captcha"] = "ok" if captcha_health.get("ok") else "unreachable"
    proxy_health = await ProxyClient(service_name="claim_validator").health()
    deps["proxy"] = "ok" if proxy_health.get("ok") else "unreachable"

    status_code = 200 if all_critical_ok else 503
    return JSONResponse(
        content={
            "service": "fabrik-claim-validator",
            "status": "ok" if all_critical_ok else "degraded",
            "dependencies": deps,
        },
        status_code=status_code,
    )


@app.get("/health/scraping_infra")
async def health_scraping_infra() -> JSONResponse:
    """Captcha + proxy reachability detail (FCV-006)."""
    captcha_health = await CaptchaClient().health()
    proxy_health = await ProxyClient(service_name="claim_validator").health()
    ok = captcha_health.get("ok") and proxy_health.get("ok")
    return JSONResponse(
        content={
            "captcha": captcha_health,
            "proxy": proxy_health,
            "status": "ok" if ok else "degraded",
        },
        status_code=200 if ok else 503,
    )


@app.get("/health/proxy_budget")
async def health_proxy_budget(request: Request) -> JSONResponse:
    """Today's proxy bandwidth budget row (FCV-010)."""
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        return JSONResponse(
            content={"status": "degraded", "error": "db_not_configured"},
            status_code=503,
        )
    return JSONResponse(content=await budget_service.status(pool), status_code=200)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Welcome to fabrik-claim-validator"}
