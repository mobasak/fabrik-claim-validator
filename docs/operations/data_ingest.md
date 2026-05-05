# Data Ingest Operations — Sprint 2.5

> **Purpose:** Step-by-step operator runbooks for FCV-252..255 (live data loads).
> These commands require network access to external services. Run from VPS or a
> machine with unrestricted outbound HTTPS.
>
> **Environment Matrix (2026-05-03 findings):**
>
> | Source | WSL dev env | VPS network | /opt/proxy needed | Working environment |
> |--------|-------------|-----------|-----------------|-------------------|
> | Zenodo (WFO) | ❌ SSL timeout | ✅ | ❌ | Windows PowerShell or VPS |
> | HERB 2.0 (`47.92.70.12`) | ✅ Direct | ✅ | ❌ | WSL or VPS (JSON API, no proxy) |
> | ema.europa.eu | ❌ 404/blocked | ✅ | ✅ as fallback | VPS (preferred) or WSL+proxy |
> | health-products.canada.ca (LNHPD) | ⚠️ returns [] | ⚠️ same | ❌ | **Broken** - pivot to NHPID web UI |
> | webprod.hc-sc.gc.ca (NHPID UI) | ✅ 200 OK | ✅ | ❌ | WSL or VPS (no proxy needed) |

---

## FCV-252: WFO Bulk Seed (≥100K botanical compounds)

### Prerequisites
- `DATABASE_URL` set and pointing to the target PostgreSQL instance
- ~3 GB free disk space for the unpacked TSV
- Migrations up to date: `alembic upgrade head`

### Steps

```bash
# 1. Download WFO classification dump from Zenodo (~578 MB JSON zip)
# From Windows PowerShell (unrestricted network access):
#   mkdir C:\temp\fabric-wfo
#   cd C:\temp\fabric-wfo
#   curl -L -o plant_list_2025-06.json.zip 'https://zenodo.org/api/records/15704590/files/plant_list_2025-06.json.zip/content'
#   scp plant_list_2025-06.json.zip root@172.93.160.197:/var/lib/fabrik-claim-validator/wfo/
# Fallback (2022-12 release, 401 MB):
#   curl -L -o plant_list_2022-12.json.zip 'https://zenodo.org/api/records/7467360/files/plant_list_2022-12.json.zip/content'
mkdir -p /var/lib/fabrik-claim-validator/wfo
# Unzip on VPS (the JSON file is inside the zip)
cd /var/lib/fabrik-claim-validator/wfo
unzip plant_list_2025-06.json.zip

# 2. Run the seed loader
cd /opt/fabrik-claim-validator
python -m fabrik_claim_validator.loaders.wfo_seed \
    --file /var/lib/fabrik-claim-validator/wfo/plant_list_2025-06.json.zip \
    2>&1 | tee logs/wfo_seed.$(date +%Y%m%d_%H%M%S).log

# 3. Verify DoD
psql "$DATABASE_URL" -c "SELECT count(*) FROM compounds WHERE is_botanical=true;"
# Expected: ≥ 100,000
psql "$DATABASE_URL" -c "SELECT count(DISTINCT wfo_id) FROM compounds WHERE wfo_id IS NOT NULL;"
# Expected: ≥ 100,000

# 4. Idempotency check (re-run should produce 0 new inserts)
python -m fabrik_claim_validator.loaders.wfo_seed \
    --file /var/lib/fabrik-claim-validator/wfo/plant_list_2025-06.json.zip \
    2>&1 | tail -1
# Expected: inserted=0 in the log line
```

### If >1% of rows fail to parse
Check the structured log for `wfo_row_skipped` events. Common causes:
- Non-numeric WFO IDs (rare, ~0.01%)
- Missing `scientificName` column (data format change — file a bug)
If failure rate exceeds 1%, inspect the TSV header and compare against
`_REQUIRED_COLS` in `loaders/wfo_seed.py`.

---

## FCV-253: HERB 2.0 Live Cassette Refresh

### Prerequisites

- `CASSETTE_MODE=record` in environment
- **No proxy needed** — HERB 2.0 JSON API at `http://47.92.70.12/chedi/api/` is callable directly
- `HERB_BASE_URL` env var (optional, default: `http://47.92.70.12`)

### Architecture

HERB 2.0 is a React SPA backed by a JSON-RPC endpoint at `POST /chedi/api/`.
Two `func_name` values: `search_api` (keyword → herb IDs) and `detail_api` (herb ID → full data).
The resolver calls these directly with `httpx` — no Browserless or proxy in the loop.

**Key finding:** HERB 2.0 indexes by Chinese/Pinyin names. Latin binomials (e.g.
`Astragalus membranaceus`) often return empty. The resolver has a `_PINYIN_ALIASES` dict
that maps Latin names to Pinyin search terms (e.g. `Huang Qi`).

### Steps

```bash
cd /opt/fabrik-claim-validator

# 1. Record cassettes for 10-herb corpus (+ 2 short-name test herbs)
CASSETTE_MODE=record python3 -c "
import asyncio
from fabrik_claim_validator.resolvers.herb_ac_cn import HerbAcCnResolver

HERBS = [
    'Ginseng', 'Astragalus',  # simple names for unit tests
    'Panax ginseng', 'Astragalus membranaceus', 'Glycyrrhiza uralensis',
    'Bupleurum chinense', 'Salvia miltiorrhiza', 'Rehmannia glutinosa',
    'Angelica sinensis', 'Atractylodes macrocephala', 'Codonopsis pilosula',
    'Schisandra chinensis',
]

async def run():
    async with HerbAcCnResolver() as resolver:
        for herb in HERBS:
            result = await resolver.fetch_detail(herb)
            if result:
                print(f'OK  {herb}: id={result[\"herb_id\"]} '
                      f'ingr={len(result[\"ingredients\"])} '
                      f'tgt={len(result[\"targets\"])} '
                      f'dis={len(result.get(\"diseases\", []))}')
            else:
                print(f'FAIL {herb}')

asyncio.run(run())
" 2>&1 | tee logs/herb_cassette_refresh.\$(date +%Y%m%d_%H%M%S).log

# 2. Verify cassettes were written (expect ~24 files: 12 search + 12 detail)
ls -la tests/cassettes/herb_ac_cn/

# 3. Run tests in replay mode
CASSETTE_MODE=replay pytest tests/test_resolvers.py -v -k herb

# 4. Spot-check — see docs/operations/sprint_2_5_herb_discovery.md for full results
```

### Environment Matrix Update

| Source | WSL dev env | VPS network | Proxy needed | Working environment |
|--------|-------------|-------------|--------------|---------------------|
| HERB 2.0 (`47.92.70.12`) | ✅ Direct | ✅ Direct | ❌ No | WSL or VPS (both work) |

### Verified Corpus (2026-05-03, 10/10 OK)

| Herb | HERB ID | Ingredients | Targets | Diseases |
|------|---------|-------------|---------|----------|
| Panax ginseng | HERB004615 | 11 | 0 | 0 |
| Astragalus membranaceus | HERB002560 | 162 | 52 | 228 |
| Glycyrrhiza uralensis | HERB001780 | 11 | 24 | 0 |
| Bupleurum chinense | HERB000638 | 419 | 44 | 2 |
| Salvia miltiorrhiza | HERB001193 | 306 | 119 | 124 |
| Rehmannia glutinosa | HERB005974 | 10 | 0 | 269 |
| Angelica sinensis | HERB001210 | 251 | 0 | 0 |
| Atractylodes macrocephala | HERB000309 | 142 | 0 | 0 |
| Codonopsis pilosula | HERB005809 | 26 | 0 | 0 |
| Schisandra chinensis | HERB005762 | 158 | 0 | 164 |

---

## FCV-254: Real EMA 5-Monograph Spot-Check

### Prerequisites
- `DATABASE_URL` set
- Migrations current (`alembic upgrade head`)
- `CASSETTE_MODE=record` for initial run

### Target monographs
| # | Herb | Expected tier | Type |
|---|------|--------------|------|
| 1 | Valeriana officinalis | A (well-established) | Standard |
| 2 | Hedera helix | A (well-established) | Standard |
| 3 | Echinacea purpurea | B (traditional) | Traditional |
| 4 | Passiflora incarnata | B (traditional) | Traditional |
| 5 | Crataegus spp. | A (well-established) | Image-heavy |

### Steps

```bash
cd /opt/fabrik-claim-validator

# 1. Run listing scrape (populates scrape_queue)
CASSETTE_MODE=record python3 -c "
import asyncio
from fabrik_claim_validator.scrapers.ema_hmpc import EmaHmpcScraper
from fabrik_claim_validator import db

async def run():
    pool = await db.create_pool()
    scraper = EmaHmpcScraper()
    await scraper.scrape_listing(pool)
    await pool.close()

asyncio.run(run())
"

# 2. Filter queue to target 5 monographs only
psql "$DATABASE_URL" -c "
    UPDATE scrape_queue SET status = 'done'
    WHERE scraper_id = 'ema_hmpc'
      AND url NOT LIKE '%valerian%'
      AND url NOT LIKE '%hedera%'
      AND url NOT LIKE '%echinacea-purpurea%'
      AND url NOT LIKE '%passiflora%'
      AND url NOT LIKE '%crataegus%';
"

# 3. Process the 5 queued monographs
CASSETTE_MODE=record python3 -c "
import asyncio
from fabrik_claim_validator.scrapers.ema_hmpc import EmaHmpcScraper
from fabrik_claim_validator import db

async def run():
    pool = await db.create_pool()
    scraper = EmaHmpcScraper()
    await scraper.process_queue(pool)
    await pool.close()

asyncio.run(run())
"

# 4. Verify and spot-check
psql "$DATABASE_URL" -c "
    SELECT title, tradition_code, evidence_tier
    FROM monographs
    WHERE tradition_code = 'ema_hmpc'
    ORDER BY title;
"
# Expected: 5 rows with non-empty full_text

# 5. Document deviations in docs/operations/sprint_2_5_ema_spotcheck.md
```

---

## FCV-255: NHPID Live Import (Web UI Pivot)

### Prerequisites
- `DATABASE_URL` set
- Migrations current (`alembic upgrade head`)
- **No proxy needed** - NHPID web UI works from WSL and VPS

### Pivot Note (2026-05-03)
The original LNHPD JSON API at `health-products.canada.ca/api/natural-licences/` returns empty arrays (backing DB detached or endpoint shape changed). FCV-255 pivots to scraping the NHPID web UI at `https://webprod.hc-sc.gc.ca/nhpid-bdipsn/` instead, which provides the actual ingredient monograph data we need. NHPID ≠ LNHPD — NHPID is the ingredient database, LNHPD is licensed products (less useful).

### Steps

```bash
cd /opt/fabrik-claim-validator
export DATABASE_URL="postgresql://postgres:$(grep POSTGRES_PASSWORD /opt/fabrik/.env | cut -d= -f2)@postgres-main:5432/fabrik_claim_validator"
export CASSETTE_MODE=record

# Run the web UI scraper
python3 -c "
import asyncio
from fabrik_claim_validator.scrapers.nhpid import NhpidScraper
from fabrik_claim_validator import db

async def run():
    pool = await db.create_pool()
    scraper = NhpidScraper()
    result = await scraper.scrape(pool)
    print(f'Result: {result}')
    await pool.close()

asyncio.run(run())
" 2>&1 | tee logs/nhpid_import.$(date +%Y%m%d_%H%M%S).log

# Verify
psql "$DATABASE_URL" -c "SELECT count(*) FROM monographs WHERE tradition_code='nhpid';"
# Expected: ≥ 500 (target ~800; any range 500-2000 acceptable)

psql "$DATABASE_URL" -c "
    SELECT
        count(*) AS total,
        count(title_native) AS with_fr_title,
        round(100.0 * count(title_native) / count(*), 1) AS fr_pct
    FROM monographs
    WHERE tradition_code = 'nhpid';
"
```

### Filter Logic
The web UI scraper extracts:
- **Ingredient name** (title_en)
- **CAS number** (where present)
- **Role classification** (medicinal/non-medicinal)
- **Monograph reference** (where available)
- **Indications** (if present in structured format)
- **Contraindications** (if present)

All ingredients from the search results are included (no "licensed" filter needed — NHPID is a pre-cleared ingredient database, not a product registry).

---

## Verification Queries (run after all loads)

```sql
-- Sprint 2.5 summary
SELECT 'compounds (botanical)' AS entity,
       count(*) AS rows
  FROM compounds WHERE is_botanical = true
UNION ALL
SELECT 'monographs (ema_hmpc)', count(*)
  FROM monographs WHERE tradition_code = 'ema_hmpc'
UNION ALL
SELECT 'monographs (nhpid)', count(*)
  FROM monographs WHERE tradition_code = 'nhpid'
UNION ALL
SELECT 'taxa_aliases (total)', count(*)
  FROM taxa_aliases;
```
