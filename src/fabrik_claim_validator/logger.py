"""Structured logging module for fabrik-claim-validator.

Pre-configured structlog logger with JSON output and service name binding.
Usage: from fabrik_claim_validator.logger import get_logger
"""

import os

import structlog


def _setup_logging() -> None:
    """Configure structlog with JSON output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_setup_logging()


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound with service name."""
    return structlog.get_logger(name, service=os.getenv("SERVICE_NAME", "fabrik_claim_validator"))  # type: ignore[no-any-return]
