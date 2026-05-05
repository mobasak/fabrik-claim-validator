# fabrik-claim-validator — Features

**Last Updated:** 2026-05-03

> **Purpose:** FEATURE DOCUMENTATION.
> Complete feature reference for fabrik-claim-validator. Serves as both internal inventory and public-facing feature documentation.

---

## Core Features

### Data Ingestion

Multi-source scrapers and resolvers that populate the validator's evidence database.

| Feature | Description |
|---------|-------------|
| WFO botanical taxonomy seed | Bulk-loads 449K+ accepted plant taxa from World Flora Online Zenodo dumps |
| EMA HMPC monograph scraper | Fetches European herbal monographs, parses PDF assessment reports, extracts indications/contraindications/evidence tiers |
| NHPID ingredient scraper | Scrapes Health Canada's Natural Health Products Ingredients Database for ingredient monographs, CAS numbers, and role classifications |
| HERB 2.0 resolver | Resolves herb names to TCM data via HERB 2.0 JSON API — ingredients, gene targets, diseases, clinical trials, and PubMed references |
| PubChem resolver | Resolves compound names to PubChem CIDs, molecular formulas, CAS numbers, and canonical SMILES |

### Evidence Normalisation

| Feature | Description |
|---------|-------------|
| Indication normaliser | Maps free-text therapeutic claims to ICD-11 codes across 5 languages (EN, DE, FR, ES, ZH) |
| Evidence tier classification | Categorises monograph evidence as well-established (A), traditional use (B), or folk/ethnobotanical (C) |
| PDF monograph parser | Extracts structured data from EMA-style PDF assessment reports including dual-column well-established/traditional layouts |

### Infrastructure

| Feature | Description |
|---------|-------------|
| Cassette-based HTTP testing | Records and replays HTTP interactions for deterministic offline tests — no network calls in CI |
| Scrape queue | Priority-ordered, idempotent job queue for batch scraping with retry and failure tracking |
| Response cache | 90-day TTL cache in PostgreSQL for upstream API responses, keyed by scraper + query |

---

## Technical Capabilities

| Capability | Details |
|------------|---------|
| Health monitoring | `GET /health` — checks PostgreSQL connectivity |
| Async HTTP | All scrapers/resolvers use `httpx.AsyncClient` with `TokenBucket` rate limiting |
| Schema migrations | Alembic with hand-written DDL (13 migrations through Sprint 2.5) |
| Structured logging | JSON logs via `structlog` with correlation IDs |
| Cassette modes | `replay` (CI default), `record` (live capture), `passthrough` (dev) via `CASSETTE_MODE` env var |

---

## Feature Status

| Feature | Status | Notes |
|---------|--------|-------|
| WFO seed loader | ✅ Shipped | Sprint 2 — 449K+ taxa loaded |
| EMA HMPC scraper + PDF parser | ✅ Shipped | Sprint 2 + 2.5 spot-check |
| NHPID web UI scraper | ✅ Shipped | Sprint 2.5 — 600 ingredients |
| HERB 2.0 JSON API resolver | ✅ Shipped | Sprint 2.5 — 10/10 corpus herbs |
| PubChem resolver | ✅ Shipped | Sprint 1 |
| Indication normaliser (5-lang) | ✅ Shipped | Sprint 2.5 |
| Discovery API (`/api/v1/discover`) | 🔜 Planned | Sprint 5 |
| JP18 / KP12 pharmacopoeia scrapers | 🔜 Planned | Sprint 4 |
| Ayurveda / Unani scrapers | 🔜 Planned | Sprint 4 |

---

## Removed / Deprecated

| Feature | Removed | Reason | Migration |
|---------|---------|--------|-----------|
| LNHPD JSON API scraper | 2026-05-03 | API returns empty arrays; DB detached. NHPID ≠ LNHPD. | Use NHPID web UI scraper (`scrapers/nhpid.py`) |
| HERB v1 HTML regex parser | 2026-05-03 | HERB site is SPA; HTML regex never worked live. | Use HERB 2.0 JSON API resolver. `parse_detail_html` kept for legacy cassette compat. |
| `herb.cuilab.cn` base URL | 2026-05-03 | Domain defunct. | Use `HERB_BASE_URL` env var (default `http://47.92.70.12`) |
