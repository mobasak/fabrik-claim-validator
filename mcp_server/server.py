"""Fabrik Claim Validator — MCP server (Sprint 0 stub, FCV-009).

Exposes 5 placeholder tools so Claude Code shows the server as
``Connected`` immediately and Sprint 5 (FCV-509) can swap stubs for the
real implementations without touching agent registrations.

Pattern lifted from ``fabrik-citation-verifier/mcp_server/server.py``.

Run via:
    /opt/fabrik-claim-validator/.venv/bin/python -m mcp_server.server

Register with Claude Code:
    claude mcp add --scope user fabrik-claim-validator \\
        /opt/fabrik-claim-validator/.venv/bin/python \\
        -- -m mcp_server.server
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

VALIDATOR_URL = os.environ.get("FABRIK_CLAIM_VALIDATOR_URL", "http://localhost:8002")

_STUB = {"status": "not_implemented_yet", "sprint": "0"}

mcp = FastMCP(
    name="fabrik-claim-validator",
    instructions=(
        "Multi-tradition claim validation + substance discovery. "
        "Validates substance/indication claims across 11 medical traditions "
        "with peer-equal evidence weighting; surfaces convergent substances "
        "via the discovery endpoint. Sibling to fabrik-citation-verifier. "
        "Sprint 0 ships stub tools — real wiring lands in Sprint 5 (FCV-509)."
    ),
)


@mcp.tool()
async def validate_claim(
    substance: str,
    indication: str,
    traditions: list[str] | None = None,  # noqa: ARG001
) -> dict[str, Any]:
    """Validate a (substance, indication) claim across traditions [STUB].

    Sprint 5 will wire this to ``POST /validate/claim`` (FCV-507).
    """
    return {**_STUB, "tool": "validate_claim", "substance": substance, "indication": indication}


@mcp.tool()
async def discover_substance(
    indication: str,
    min_traditions: int = 3,  # noqa: ARG001
) -> dict[str, Any]:
    """Discover substances with convergent evidence for an indication [STUB].

    Sprint 5 will wire this to ``POST /discover/substance`` (FCV-508).
    """
    return {**_STUB, "tool": "discover_substance", "indication": indication}


@mcp.tool()
async def tradition_health(tradition_code: str | None = None) -> dict[str, Any]:
    """Per-tradition scraper / monograph-corpus health [STUB].

    Sprint 5 surfaces ``GET /health/scraper/<tradition_code>`` (FCV-307).
    """
    return {**_STUB, "tool": "tradition_health", "tradition_code": tradition_code}


@mcp.tool()
async def validator_health() -> dict[str, Any]:
    """Aggregate validator health (db + verifier + captcha + proxy) [STUB]."""
    return {**_STUB, "tool": "validator_health", "validator_url": VALIDATOR_URL}


@mcp.tool()
async def check_proxy_budget() -> dict[str, Any]:
    """Today's proxy bandwidth budget consumption [STUB]."""
    return {**_STUB, "tool": "check_proxy_budget"}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
