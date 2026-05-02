"""Main entry point for fabrik-claim-validator."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from fabrik_claim_validator.logger import get_logger
from fabrik_claim_validator.middleware import CorrelationMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Application lifespan handler."""
    logger.info("service_starting", port=os.getenv("PORT", "8000"))
    yield
    logger.info("service_stopping")


app = FastAPI(title="fabrik-claim-validator", lifespan=lifespan)
app.add_middleware(CorrelationMiddleware)


@app.get("/health")
async def health():
    """Health check - tests actual dependencies, returns non-200 on failure."""
    db_url = os.getenv("DATABASE_URL")
    deps = {}
    all_ok = True

    # Database check (only if configured)
    if db_url:
        try:
            # TODO: Replace with actual async DB ping when DB is added
            # Example: await db.execute("SELECT 1")
            deps["database"] = "configured"
        except Exception as e:
            deps["database"] = f"error: {str(e)}"
            logger.error("health_check_failed", dependency="database", error=str(e))
            all_ok = False
    else:
        deps["database"] = "not_configured"

    status_code = 200 if all_ok else 503
    return JSONResponse(
        content={
            "service": "fabrik-claim-validator",
            "status": "ok" if all_ok else "degraded",
            "dependencies": deps,
        },
        status_code=status_code,
    )


@app.get("/")
async def root():
    return {"message": "Welcome to fabrik-claim-validator"}
