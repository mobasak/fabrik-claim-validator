"""World Flora Online Plant List seed loader (FCV-102).

Ingests the WFO classification dump (TSV or JSON from Zenodo) and populates
``compounds.is_botanical=true`` + ``compounds.wfo_id`` for every accepted
plant taxon.

Design decisions:

- **Accepted-only.** WFO ships synonyms + accepted names interleaved; we
  seed only rows where ``taxonomicStatus == 'Accepted'``. Synonyms are
  surfaced later via `taxa_aliases` in dedicated loaders.
- **No PubChem CID yet.** WFO has no chemistry; rows are inserted with
  ``pubchem_cid`` left NULL-compatible. But ``compounds.pubchem_cid`` is
  our PK, so we cannot store a botanical-only row there directly. **We
  therefore use the negative-WFO convention**: ``pubchem_cid = -<wfo_id numeric>``
  for plant-only rows so they coexist with chemistry-resolved compounds.
  When a PubChem CID later resolves for the taxon, the resolver promotes
  the row (see ``PubChemResolver.upsert`` — matches on ``taxon_canonical``).
- **Fixture-friendly.** The CI test feeds a 10-row TSV; the DoD's
  ≥100K-row real-data run is an operator-side task (documented in PLAN.md).

CLI usage (operator):

    # JSON format (Zenodo - recommended for production)
    python -m fabrik_claim_validator.loaders.wfo_seed \
        --file /path/to/plant_list_2022-12.json.zip

    # TSV format (legacy fixture)
    python -m fabrik_claim_validator.loaders.wfo_seed \
        --file /path/to/wfo-plant-list.tsv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
from pathlib import Path
from typing import Any

import asyncpg

from .. import db as db_module
from ..logger import get_logger

logger = get_logger(__name__)

# Expected WFO columns; we tolerate extras.
_REQUIRED_COLS = ("taxonID", "scientificName", "taxonomicStatus")


def _wfo_numeric_id(wfo_id: str) -> int:
    """Extract the integer suffix from a WFO ID like ``wfo-0000000123``."""
    digits = "".join(ch for ch in wfo_id if ch.isdigit())
    if not digits:
        raise ValueError(f"Cannot extract numeric ID from WFO id {wfo_id!r}")
    return int(digits)


def iter_accepted_rows(data_path: Path) -> list[dict[str, str]]:
    """Read WFO data (TSV or JSON) and return only ``taxonomicStatus='Accepted'`` rows."""
    # Zenodo files are named plant_list_YYYY-MM.json.zip or .json.gz
    if data_path.suffix in (".json", ".zip", ".gz") or "json" in data_path.name:
        return _iter_accepted_json(data_path)
    # TSV format (legacy fixture)
    with data_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames is None or not all(c in reader.fieldnames for c in _REQUIRED_COLS):
            raise ValueError(
                f"WFO TSV missing required columns {_REQUIRED_COLS}; got {reader.fieldnames}"
            )
        return [row for row in reader if row.get("taxonomicStatus") == "Accepted"]


def _iter_accepted_json(json_path: Path) -> list[dict[str, str]]:
    """Read WFO JSON format (Zenodo plant_list_YYYY-MM.json.zip or .json.gz).

    The Zenodo WFO JSON is a ~5.6 GB array of Solr-style objects.
    We stream-parse it to avoid loading the entire file into memory.

    Solr field mapping:
        wfo_id_s                             → taxonID
        role_s                               → taxonomicStatus  (lowercase "accepted")
        full_name_string_no_authors_plain_s  → scientificName
    """
    import gzip
    import io
    import json
    import zipfile

    def _open_stream(path: Path) -> io.IOBase:
        if path.suffix == ".gz":
            return gzip.open(path, "rb")
        # Zip file (Zenodo default)
        zf = zipfile.ZipFile(path, "r")
        json_files = [n for n in zf.namelist() if n.endswith(".json")]
        if not json_files:
            raise ValueError(f"No JSON file found in {path}")
        return zf.open(json_files[0])

    accepted: list[dict[str, str]] = []
    decoder = json.JSONDecoder()

    with _open_stream(json_path) as raw_f:
        # Wrap in a text reader for incremental decoding
        f = io.TextIOWrapper(raw_f, encoding="utf-8")
        buf = ""
        # Skip leading whitespace / '['
        while True:
            ch = f.read(1)
            if not ch:
                return accepted
            if ch == "[":
                break

        # Stream-parse individual JSON objects
        CHUNK = 64 * 1024
        while True:
            # Read more data if buffer is small
            if len(buf) < CHUNK:
                new = f.read(CHUNK)
                if new:
                    buf += new

            # Skip whitespace and commas
            buf = buf.lstrip(" \t\r\n,")
            if not buf:
                new = f.read(CHUNK)
                if not new:
                    break
                buf = new.lstrip(" \t\r\n,")

            if buf[0] == "]":
                break

            try:
                taxon, end = decoder.raw_decode(buf)
                buf = buf[end:]
            except json.JSONDecodeError:
                # Need more data
                new = f.read(CHUNK)
                if not new:
                    break
                buf += new
                continue

            if taxon.get("role_s") == "accepted":
                sci_name = taxon.get("full_name_string_no_authors_plain_s", "").strip()
                wfo_id = taxon.get("wfo_id_s", "")
                if sci_name and wfo_id:
                    accepted.append(
                        {
                            "taxonID": wfo_id,
                            "scientificName": sci_name,
                            "taxonomicStatus": "Accepted",
                        }
                    )

    logger.info("wfo_json_parsed", accepted=len(accepted))
    return accepted


async def load(pool: asyncpg.Pool, tsv_path: Path) -> dict[str, int]:
    """Load + upsert accepted WFO rows. Returns ``{seen, inserted, updated}``."""
    rows = iter_accepted_rows(tsv_path)
    inserted = 0
    updated = 0
    async with pool.acquire() as conn:
        for row in rows:
            wfo_id = row["taxonID"]
            try:
                numeric = _wfo_numeric_id(wfo_id)
            except ValueError:
                logger.warning("wfo_row_skipped", wfo_id=wfo_id, reason="non_numeric_id")
                continue
            synthetic_cid = -numeric  # negative-space reservation for botanicals
            result = await conn.execute(
                """
                INSERT INTO compounds (
                    pubchem_cid, canonical_name, is_botanical, taxon_canonical,
                    wfo_id, fetched_at
                ) VALUES ($1, $2, TRUE, $2, $3, NOW())
                ON CONFLICT (pubchem_cid) DO UPDATE SET
                    canonical_name  = EXCLUDED.canonical_name,
                    is_botanical    = TRUE,
                    taxon_canonical = EXCLUDED.taxon_canonical,
                    wfo_id          = EXCLUDED.wfo_id,
                    fetched_at      = NOW()
                """,
                synthetic_cid,
                row["scientificName"],
                wfo_id,
            )
            if result.endswith("1") and "INSERT" in result:
                inserted += 1
            else:
                updated += 1
    logger.info("wfo_seed_complete", seen=len(rows), inserted=inserted, updated=updated)
    return {"seen": len(rows), "inserted": inserted, "updated": updated}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed WFO plant taxa into compounds.")
    parser.add_argument(
        "--file", type=Path, required=True, help="Path to WFO data file (.tsv or .json.zip)"
    )
    return parser.parse_args(argv)


async def _run_cli(argv: list[str] | None = None) -> dict[str, int]:
    args = _parse_args(argv)
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL must be set to run the WFO seed loader")
    pool = await db_module.create_pool()
    try:
        return await load(pool, args.file)
    finally:
        await pool.close()


def main(argv: list[str] | None = None) -> None:
    result = asyncio.run(_run_cli(argv))
    logger.info("wfo_seed_cli_complete", **result)


__all__: tuple[str, ...] = ("load", "iter_accepted_rows", "main")

# Silence unused-import linters when the module is evaluated without CLI use.
_ = Any

if __name__ == "__main__":
    main()
