"""Generic PDF monograph parser (FCV-202b).

Reused by Sprint 4 (FCV-402 JP18, FCV-405 KP12).  Zero tradition-specific
knowledge — callers pass section patterns.

Pipeline:
1. Extract text per page via pdfplumber.
2. Detect image-only pages (< ``IMAGE_PAGE_TEXT_THRESHOLD`` chars of text).
3. For image-only pages, call the canonical vision-LLM via ``_vision.py``.
4. Concatenate all page texts, run caller-provided section regex patterns.
5. Return ``ParsedMonograph`` with uniform section dict, warnings, refs.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

import pdfplumber

from ..logger import get_logger
from . import _vision

logger = get_logger(__name__)

# Pages with fewer characters than this are flagged as image-only.
IMAGE_PAGE_TEXT_THRESHOLD = 50

# Default vision prompt for monograph page extraction.
VISION_PROMPT = (
    "Extract all text from this pharmacopoeia monograph page.  Preserve section "
    "headings (e.g. 'Therapeutic indications', 'Contraindications', 'Pharmaceutical "
    "form').  Return plain text, no markdown."
)


@dataclass
class ImageRef:
    """Reference to a page where vision-LLM was used."""

    page_num: int
    model: str
    source: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedMonograph:
    """Uniform output of the PDF parser — shared by EMA, JP18, KP12."""

    pages_text: list[str]
    sections: dict[str, str]
    images_extracted: list[ImageRef]
    parse_warnings: list[str]
    cassette_id: str | None = None

    @property
    def full_text(self) -> str:
        """Concatenated text from all pages."""
        return "\n\n".join(t for t in self.pages_text if t.strip())


@dataclass
class SectionPattern:
    """A regex pattern for extracting a named section from monograph text."""

    name: str
    pattern: re.Pattern[str]


class PdfMonographParser:
    """Stateless PDF-to-structured-monograph parser.

    Usage::

        parser = PdfMonographParser()
        result = await parser.parse(pdf_bytes, source_url, section_patterns)
    """

    async def parse(
        self,
        pdf_bytes: bytes,
        source_url: str,
        section_patterns: list[SectionPattern],
        *,
        vision_prompt: str = VISION_PROMPT,
    ) -> ParsedMonograph:
        """Parse a PDF into a ``ParsedMonograph``.

        Args:
            pdf_bytes: Raw PDF file content.
            source_url: Origin URL (for logging / cassette keying).
            section_patterns: Caller-defined section extraction regexes.
            vision_prompt: Prompt sent to vision-LLM for image pages.

        Returns:
            ParsedMonograph with extracted text, sections, and warnings.
        """
        pages_text: list[str] = []
        images_extracted: list[ImageRef] = []
        warnings: list[str] = []

        # ── Extract text from each page ──────────────────────────
        try:
            pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        except Exception as exc:
            logger.error("pdf_parser.open_failed", source_url=source_url, error=str(exc))
            return ParsedMonograph(
                pages_text=[],
                sections={},
                images_extracted=[],
                parse_warnings=[f"Failed to open PDF: {exc}"],
            )

        try:
            for page_num, page in enumerate(pdf.pages):
                text = (page.extract_text() or "").strip()

                if len(text) < IMAGE_PAGE_TEXT_THRESHOLD:
                    # Image-only page — try vision-LLM.
                    logger.debug(
                        "pdf_parser.image_page",
                        page_num=page_num,
                        text_len=len(text),
                        source_url=source_url,
                    )
                    vision_text = await self._vision_extract(page, page_num, vision_prompt)
                    if vision_text.text:
                        pages_text.append(vision_text.text)
                        images_extracted.append(
                            ImageRef(
                                page_num=page_num,
                                model=vision_text.model,
                                source=vision_text.source,
                                warnings=vision_text.warnings,
                            )
                        )
                    else:
                        pages_text.append(text)  # keep whatever little text there was
                        warnings.append(
                            f"Page {page_num}: image-only, vision extraction "
                            f"returned empty ({'; '.join(vision_text.warnings)})"
                        )
                else:
                    pages_text.append(text)
        finally:
            pdf.close()

        # ── Run section extraction ───────────────────────────────
        full_text = "\n\n".join(t for t in pages_text if t.strip())
        sections = self._extract_sections(full_text, section_patterns, warnings)

        logger.info(
            "pdf_parser.done",
            source_url=source_url,
            total_pages=len(pages_text),
            image_pages=len(images_extracted),
            sections_found=len(sections),
        )

        return ParsedMonograph(
            pages_text=pages_text,
            sections=sections,
            images_extracted=images_extracted,
            parse_warnings=warnings,
        )

    async def _vision_extract(
        self,
        page: Any,
        page_num: int,
        prompt: str,
    ) -> _vision.VisionResult:
        """Render a page to PNG and send to vision-LLM."""
        try:
            img = page.to_image(resolution=200)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_bytes = buf.getvalue()
        except Exception as exc:
            logger.warning(
                "pdf_parser.render_failed",
                page_num=page_num,
                error=str(exc),
            )
            return _vision.VisionResult(
                text="",
                model="none",
                source="render_failed",
                page_num=page_num,
                warnings=[f"Page render failed: {exc}"],
            )

        return await _vision.extract_text_from_image(image_bytes, prompt, page_num=page_num)

    def _extract_sections(
        self,
        full_text: str,
        patterns: list[SectionPattern],
        warnings: list[str],
    ) -> dict[str, str]:
        """Run caller-provided regex patterns against concatenated text."""
        sections: dict[str, str] = {}
        for sp in patterns:
            match = sp.pattern.search(full_text)
            if match:
                sections[sp.name] = match.group(1).strip()
            else:
                warnings.append(f"Section '{sp.name}' not found in PDF text")
        return sections


__all__ = [
    "ImageRef",
    "ParsedMonograph",
    "PdfMonographParser",
    "SectionPattern",
]
