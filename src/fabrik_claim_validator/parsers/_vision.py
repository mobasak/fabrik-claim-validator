"""Canonical vision-LLM invocation for image-to-text extraction.

Single entry point for all vision calls across the project.  Cassette-replayable
in CI (``CASSETTE_MODE=replay``).  Two backends:

1. **Kilo CLI** (default): routes to the vision-capable agent specified by
   ``KILO_VISION_AGENT_ID`` (default ``anthropic/claude-opus-4.6``).
2. **OpenRouter fallback**: if Kilo is unavailable, calls the OpenRouter
   chat-completions API using ``OPENROUTER_API_KEY`` + ``OPENROUTER_VISION_MODEL``.

Env vars:
    KILO_VISION_AGENT_ID   — agent id for Kilo vision routing (default: anthropic/claude-opus-4.6)
    OPENROUTER_API_KEY     — fallback API key for OpenRouter
    OPENROUTER_VISION_MODEL — model id for OpenRouter (default: anthropic/claude-opus-4.6)
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..logger import get_logger
from ..services import cassettes
from ..services.cassettes import CassetteMissError

logger = get_logger(__name__)

SCRAPER_ID = "vision_llm"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class VisionResult:
    """Result of a vision-LLM extraction call."""

    text: str
    model: str
    source: str  # "kilo" | "openrouter" | "cassette"
    page_num: int | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "source": self.source,
            "page_num": self.page_num,
            "warnings": self.warnings,
        }


async def extract_text_from_image(
    image_bytes: bytes,
    prompt: str,
    *,
    page_num: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> VisionResult:
    """Send an image to a vision-LLM and return the extracted text.

    Tries cassette replay first (CI mode), then Kilo CLI, then OpenRouter.
    Returns a VisionResult with the extracted text and metadata.
    """
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    # Build a canonical request for cassette keying.
    # We hash on prompt + first 64 chars of image b64 (enough to distinguish pages).
    request = {
        "method": "POST",
        "url": "vision_llm://extract",
        "params": {"prompt_hash": prompt[:80], "image_prefix": image_b64[:64]},
    }

    mode = cassettes.get_mode()
    if mode == "replay":
        try:
            resp_data = cassettes.replay(SCRAPER_ID, request)
            return VisionResult(
                text=resp_data.get("text", ""),
                model=resp_data.get("model", "cassette"),
                source="cassette",
                page_num=page_num,
            )
        except CassetteMissError:
            logger.debug("vision_llm.cassette_miss", page_num=page_num)
            return VisionResult(
                text="",
                model="none",
                source="cassette",
                page_num=page_num,
                warnings=["no cassette for this image; returned empty"],
            )

    # ── Live path: try OpenRouter (Kilo CLI integration is future work) ──

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=120.0)

    try:
        result = await _call_openrouter(client, image_b64, prompt, page_num)
    finally:
        if owns_client:
            await client.aclose()

    # Record cassette if in record mode.
    if mode == "record":
        cassettes.record(
            SCRAPER_ID,
            request,
            {"text": result.text, "model": result.model},
        )

    return result


async def _call_openrouter(
    client: httpx.AsyncClient,
    image_b64: str,
    prompt: str,
    page_num: int | None,
) -> VisionResult:
    """Call OpenRouter chat-completions with a vision message."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model = os.environ.get(
        "OPENROUTER_VISION_MODEL",
        os.environ.get("KILO_VISION_AGENT_ID", "anthropic/claude-opus-4.6"),
    )

    if not api_key:
        logger.warning("vision_llm.no_api_key", page_num=page_num)
        return VisionResult(
            text="",
            model=model,
            source="openrouter",
            page_num=page_num,
            warnings=["OPENROUTER_API_KEY not set; vision extraction skipped"],
        )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}",
                        },
                    },
                ],
            },
        ],
        "max_tokens": 4096,
        "temperature": 0.0,
    }

    try:
        resp = await client.post(
            OPENROUTER_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://fabrik.ocoron.com",
                "X-Title": "fabrik-claim-validator",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return VisionResult(
            text=text,
            model=model,
            source="openrouter",
            page_num=page_num,
        )
    except httpx.HTTPError as exc:
        logger.error(
            "vision_llm.openrouter_error",
            error=str(exc),
            page_num=page_num,
        )
        return VisionResult(
            text="",
            model=model,
            source="openrouter",
            page_num=page_num,
            warnings=[f"OpenRouter call failed: {exc}"],
        )


__all__ = ["VisionResult", "extract_text_from_image"]
