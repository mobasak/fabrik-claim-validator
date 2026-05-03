"""WHO ICTM / ICD-11 TM2 seed loader (FCV-103).

Ingests the WHO International Classification of Traditional Medicine
(ICD-11 Chapter 26, TM2 module) codes plus their native-name aliases into
``taxa_aliases``.

Input format (JSON, matches what the WHO ICTM export produces after
normalisation — the plan calls for a curated top-500 subset):

```json
[
  {
    "ictm_code": "TM2.PA00",
    "canonical_name": "Ginseng root",
    "pubchem_cid": 9898,
    "aliases": [
      {"name": "人参",       "lang": "zh", "script": "Hans", "tradition": "tcm"},
      {"name": "朝鮮人参",   "lang": "ja", "script": "Jpan", "tradition": "kampo"},
      {"name": "인삼",       "lang": "ko", "script": "Hang", "tradition": "korean"},
      {"name": "Женьшень",   "lang": "ru", "script": "Cyrl", "tradition": "tpm"},
      {"name": "ginseng",    "lang": "en", "script": "Latn", "tradition": null},
      {"name": "جينسنغ",     "lang": "ar", "script": "Arab", "tradition": "unani"}
    ]
  },
  ...
]
```

Each alias row is upserted into ``taxa_aliases`` (unique on
``(pubchem_cid, alias_name, alias_lang, tradition_code)``) with
``alias_type='common'`` and ``source='ictm'``.

CLI usage (operator):

    python -m fabrik_claim_validator.loaders.ictm_seed \\
        --json /path/to/ictm_tm2.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import asyncpg

from .. import db as db_module
from ..logger import get_logger

logger = get_logger(__name__)


def _validate(entry: dict[str, Any], index: int) -> None:
    for key in ("ictm_code", "canonical_name", "aliases"):
        if key not in entry:
            raise ValueError(f"ictm entry [{index}] missing key {key!r}")
    if not isinstance(entry["aliases"], list):
        raise ValueError(f"ictm entry [{index}] 'aliases' must be a list")


async def _ensure_botanical_row(
    conn: asyncpg.Connection, canonical_name: str, pubchem_cid: int | None
) -> int:
    """Insert a placeholder ``compounds`` row if no CID is supplied.

    Mirrors the WFO loader's negative-space convention so the alias rows
    always have a valid ``pubchem_cid`` FK target.
    """
    if pubchem_cid is not None and pubchem_cid > 0:
        # Reserve the CID slot in compounds if not yet present.
        await conn.execute(
            """
            INSERT INTO compounds (pubchem_cid, canonical_name, is_botanical, fetched_at)
            VALUES ($1, $2, TRUE, NOW())
            ON CONFLICT (pubchem_cid) DO NOTHING
            """,
            pubchem_cid,
            canonical_name,
        )
        return pubchem_cid
    # No CID → use a stable negative hash of the canonical name.
    synthetic = -(abs(hash(canonical_name)) % (2**31))
    await conn.execute(
        """
        INSERT INTO compounds (pubchem_cid, canonical_name, is_botanical, fetched_at)
        VALUES ($1, $2, TRUE, NOW())
        ON CONFLICT (pubchem_cid) DO NOTHING
        """,
        synthetic,
        canonical_name,
    )
    return synthetic


async def load(pool: asyncpg.Pool, json_path: Path) -> dict[str, int]:
    """Load ICTM TM2 JSON. Returns ``{entries, aliases_inserted, langs_seen}``."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("ICTM JSON must be a top-level list of entries")

    aliases_inserted = 0
    langs_seen: set[str] = set()

    async with pool.acquire() as conn:
        for idx, entry in enumerate(data):
            _validate(entry, idx)
            cid = await _ensure_botanical_row(
                conn, entry["canonical_name"], entry.get("pubchem_cid")
            )
            for alias in entry["aliases"]:
                name = alias["name"]
                lang = alias["lang"]
                script = alias.get("script")
                tradition = alias.get("tradition")
                langs_seen.add(lang)
                if tradition is not None:
                    await conn.execute(
                        """
                        INSERT INTO taxa_aliases (
                            pubchem_cid, alias_name, alias_lang, alias_script,
                            tradition_code, alias_type, source, source_record_id
                        ) VALUES ($1, $2, $3, $4, $5, 'common', 'ictm', $6)
                        ON CONFLICT (pubchem_cid, alias_name, alias_lang, tradition_code)
                            WHERE tradition_code IS NOT NULL
                        DO NOTHING
                        """,
                        cid,
                        name,
                        lang,
                        script,
                        tradition,
                        entry["ictm_code"],
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO taxa_aliases (
                            pubchem_cid, alias_name, alias_lang, alias_script,
                            tradition_code, alias_type, source, source_record_id
                        ) VALUES ($1, $2, $3, $4, NULL, 'common', 'ictm', $5)
                        ON CONFLICT (pubchem_cid, alias_name, alias_lang)
                            WHERE tradition_code IS NULL
                        DO NOTHING
                        """,
                        cid,
                        name,
                        lang,
                        script,
                        entry["ictm_code"],
                    )
                aliases_inserted += 1

    logger.info(
        "ictm_seed_complete",
        entries=len(data),
        aliases=aliases_inserted,
        langs=sorted(langs_seen),
    )
    return {
        "entries": len(data),
        "aliases_inserted": aliases_inserted,
        "langs_seen": len(langs_seen),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed WHO ICTM TM2 aliases.")
    parser.add_argument("--json", type=Path, required=True, help="Path to ictm_tm2.json")
    return parser.parse_args(argv)


async def _run_cli(argv: list[str] | None = None) -> dict[str, int]:
    args = _parse_args(argv)
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL must be set to run the ICTM seed loader")
    pool = await db_module.create_pool()
    try:
        return await load(pool, args.json)
    finally:
        await pool.close()


def main(argv: list[str] | None = None) -> None:
    result = asyncio.run(_run_cli(argv))
    logger.info("ictm_seed_cli_complete", **result)


__all__: tuple[str, ...] = ("load", "main")


if __name__ == "__main__":
    main()
