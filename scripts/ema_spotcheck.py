#!/usr/bin/env python3
"""EMA HMPC 5-monograph spot-check runner (FCV-254).

Reads hardcoded monograph URLs from ``tests/fixtures/ema_spotcheck_urls.json``,
inserts them into ``scrape_queue``, runs the EMA scraper's ``process_queue``,
and generates a structured spot-check report at
``docs/operations/sprint_2_5_ema_spotcheck.md``.

Usage::

    export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/fabrik_claim_validator_dev"
    export CASSETTE_MODE=record
    python scripts/ema_spotcheck.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure project src is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import asyncpg  # noqa: E402

from fabrik_claim_validator.scrapers.ema_hmpc import EmaHmpcScraper  # noqa: E402

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ema_spotcheck_urls.json"
)
REPORT_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "operations" / "sprint_2_5_ema_spotcheck.md"
)
SCRAPER_ID = "ema_hmpc"


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    urls_data = json.loads(FIXTURE_PATH.read_text())
    print(f"Loaded {len(urls_data)} monograph URLs from fixture")

    pool = await asyncpg.create_pool(dsn=db_url)

    # Step 1: Insert URLs into scrape_queue (idempotent).
    async with pool.acquire() as conn:
        for entry in urls_data:
            await conn.execute(
                """
                INSERT INTO scrape_queue (scraper_id, url, worker_id, metadata)
                VALUES ($1, $2, 1, $3::jsonb)
                ON CONFLICT (scraper_id, url) DO UPDATE SET
                    status = 'pending',
                    attempts = 0,
                    last_error = NULL,
                    claimed_at = NULL,
                    completed_at = NULL
                """,
                SCRAPER_ID,
                entry["url"],
                json.dumps({"source": "spotcheck", "herb": entry["herb"]}),
            )
        print(f"Enqueued {len(urls_data)} URLs into scrape_queue")

    # Step 2: Run the scraper's process_queue.
    async with EmaHmpcScraper(rate_per_sec=0.25) as scraper:
        processed = await scraper.process_queue(pool, batch_size=5)
        print(f"Processed {processed} monographs")

    # Step 3: Verify DB rows and generate report.
    rows = await pool.fetch(
        """
        SELECT monograph_native_id, title_en, evidence_tier,
               length(full_text) as full_text_len,
               indications_native, contraindications_native,
               preparations, source_url
        FROM monographs
        WHERE tradition_code = 'ema_hmpc'
        ORDER BY monograph_native_id
        """
    )
    print(f"\nDB rows with tradition_code='ema_hmpc': {len(rows)}")

    # Step 4: Build comparison report.
    report_lines = [
        "# EMA HMPC 5-Monograph Spot-Check Report",
        "",
        f"**Generated:** {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "**Ticket:** FCV-254",
        f"**Environment:** WSL dev ({os.uname().nodename})",
        f"**Cassette mode:** {os.environ.get('CASSETTE_MODE', 'not set')}",
        "",
        "## Summary",
        "",
        "| # | Herb | Slug | Title Match | Evidence Tier | Full Text | Indications | Contra | Preps | Verdict |",
        "|---|------|------|-------------|---------------|-----------|-------------|--------|-------|---------|",
    ]

    verdicts = []
    for i, entry in enumerate(urls_data, 1):
        slug = entry["slug"]
        native_id = f"ema_hmpc_{slug}"
        row = next((r for r in rows if r["monograph_native_id"] == native_id), None)

        if row is None:
            report_lines.append(
                f"| {i} | {entry['herb']} | `{slug}` | ❌ missing | — | — | — | — | — | **missing-content** |"
            )
            verdicts.append("missing-content")
            continue

        # Title match.
        title = row["title_en"] or ""
        title_verdict = "exact" if title else "missing-content"

        # Evidence tier.
        tier = row["evidence_tier"]
        _ = "exact" if tier == entry["expected_tier"] else "cosmetic-deviation"  # used in verdict

        # Full text.
        ft_len = row["full_text_len"] or 0
        ft_verdict = f"{ft_len} chars" if ft_len > 0 else "❌ empty"

        # Indications.
        ind = row["indications_native"] or []
        ind_verdict = f"{len(ind)} items" if ind else "❌ empty"

        # Contraindications.
        contra = row["contraindications_native"] or []
        contra_verdict = f"{len(contra)} items" if contra else "❌ empty"

        # Preparations.
        preps = row["preparations"]
        if isinstance(preps, str):
            try:
                preps = json.loads(preps)
            except json.JSONDecodeError:
                preps = []
        preps = preps or []
        preps_verdict = f"{len(preps)} items" if preps else "❌ empty"

        # Overall verdict.
        if ft_len == 0 or not title:
            verdict = "missing-content"
        elif not ind and not contra:
            verdict = "structural-deviation"
        elif tier != entry["expected_tier"]:
            verdict = "cosmetic-deviation"
        else:
            verdict = "exact"

        verdicts.append(verdict)
        report_lines.append(
            f"| {i} | {entry['herb']} | `{slug}` | {title_verdict} | {tier} (expect {entry['expected_tier']}) | {ft_verdict} | {ind_verdict} | {contra_verdict} | {preps_verdict} | **{verdict}** |"
        )

    report_lines.extend(
        [
            "",
            "## Verdict Summary",
            "",
            f"- **exact:** {verdicts.count('exact')}",
            f"- **cosmetic-deviation:** {verdicts.count('cosmetic-deviation')}",
            f"- **structural-deviation:** {verdicts.count('structural-deviation')}",
            f"- **missing-content:** {verdicts.count('missing-content')}",
            "",
        ]
    )

    if any(v in ("structural-deviation", "missing-content") for v in verdicts):
        report_lines.append(
            "⚠️ **Action required:** structural-deviation or missing-content findings trigger FCV-254b."
        )
    else:
        report_lines.append("✅ All monographs passed — no FCV-254b needed.")

    report_lines.extend(
        [
            "",
            "## Detail Rows",
            "",
        ]
    )
    for row in rows:
        report_lines.append(f"### `{row['monograph_native_id']}`")
        report_lines.append("")
        report_lines.append(f"- **Title:** {row['title_en']}")
        report_lines.append(f"- **Evidence tier:** {row['evidence_tier']}")
        report_lines.append(f"- **Full text length:** {row['full_text_len'] or 0} chars")
        report_lines.append(f"- **Source URL:** {row['source_url']}")
        ind = row["indications_native"] or []
        report_lines.append(
            f"- **Indications ({len(ind)}):** {'; '.join(ind[:5])}{'...' if len(ind) > 5 else ''}"
        )
        contra = row["contraindications_native"] or []
        report_lines.append(
            f"- **Contraindications ({len(contra)}):** {'; '.join(contra[:5])}{'...' if len(contra) > 5 else ''}"
        )
        report_lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(report_lines) + "\n")
    print(f"\nReport written to {REPORT_PATH}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
