# NHPID Filter Criteria (FCV-255) — Web UI Pivot

> **Source:** `scrapers/nhpid.py` — `NhpidScraper._fetch_ingredient_list()` + `_scrape_ingredient_detail()`
> **Last updated:** 2026-05-03 (pivot from LNHPD JSON API to NHPID web UI)

## Pivot Rationale (2026-05-03)

The original FCV-255 targeted Health Canada's LNHPD JSON API (`health-products.canada.ca/api/natural-licences/`). Two problems:

1. **The API returns empty arrays `[]`** for known-good queries — the backing DB is detached or endpoint shape changed. Earlier IIS error `Configuration Error: Unrecognized attribute 'refreshCallback'` confirms a server-side deploy issue.
2. **NHPID ≠ LNHPD** — these are different databases:
   - **LNHPD** = licensed *products* (commercial registrations, less useful for the validator)
   - **NHPID** = ingredients (the monograph-equivalent data we actually want)

**Pivot:** Scrape `https://webprod.hc-sc.gc.ca/nhpid-bdipsn/` (NHPID web UI) using HTML parsing. No proxy needed — the web UI works from both WSL and VPS.

## Filter Logic

The web UI scraper has **no "licensed" filter** — NHPID is a pre-cleared ingredient database, not a product registry. All ingredients from the search results are included.

### Extraction Strategy

The scraper extracts the following fields from each ingredient monograph page:

| Monograph field | NHPID web UI source | Fallback |
|-----------------|---------------------|----------|
| `title` | Ingredient name from search result | — |
| `title_native` | Same as title (EN-only by default) | — |
| `tradition_code` | `'nhpid'` (hardcoded) | — |
| `evidence_tier` | `'A'` (Health Canada pre-cleared monographs are regulatory-pharmacopoeia tier) | — |
| `metadata.cas` | CAS number field (where present) | None |
| `metadata.role` | Role classification (medicinal/non-medicinal) | "unknown" |
| `metadata.monograph_reference` | Monograph reference link (where available) | None |
| `indications_native` | Indications section (structured HTML table) | Empty list |
| `contraindications_native` | Contraindications section (structured HTML table) | Empty list |
| `preparations` | Not typically listed on ingredient pages | Empty list |

### Field Completeness Threshold

An ingredient is considered "monograph-equivalent" if:
- It has a non-empty ingredient name from the search results
- The ingredient detail page loads successfully (HTTP 200)

Ingredients missing the name field are silently skipped (logged as debug).

## Accepted vs Rejected — Examples

### Accepted (Valid ingredient)
```json
{
  "name": "Vitamin C",
  "detail_url": "https://webprod.hc-sc.gc.ca/nhpid-bdipsn/atnReq.do?mname=Vitamin+C",
  "cas": "50-81-5",
  "role": "medicinal",
  "monograph_reference": "HPFB monograph"
}
```

### Rejected (Missing name)
```json
{
  "name": "",
  "detail_url": "https://webprod.hc-sc.gc.ca/nhpid-bdipsn/atnReq.do?mname="
}
```

## EN+FR Title Coverage

To be measured after live import:
```sql
SELECT
    count(*) AS total,
    count(title_native) AS with_fr_title,
    round(100.0 * count(title_native) / count(*), 1) AS fr_pct
FROM monographs
WHERE tradition_code = 'nhpid';
```

Expected: FR coverage is low (NHPID is EN-only by default; FR would require using the `lang=fr` query parameter in a separate scrape pass).
