# Strategic Backlog

**Last Updated:** 2026-05-03

> **Purpose:** ISSUE PREVENTION — CAPTURES ISSUES FROM KILO CLI SESSIONS TO PREVENT FUTURE OCCURRENCES.

Filled by Cascade agent watching active Kilo CLI terminal. Detects issues faced by AI coder and fixer to prevent them happening in the future.

---

## Now — Ready for Focus Window

| Effort | Item | Why Priority | Ready When |
| :--- | :--- | :--- | :--- |
| **S** | EMA listing route fix (FCV-202c) | Sprint 4 scrapers need working listing discovery | Sprint 4 kickoff |
| **M** | HERB Pinyin alias expansion | Current 10-herb alias table won't scale to full TCM corpus (~800 herbs) | Sprint 4 TCM scraper |
| **M** | Proxy client API alignment | `services/proxy.py` uses `POST /proxy/acquire` but VPS API is `GET /proxy?service=&worker_id=` | Before any scraper needs proxy |

---

## Later

- [ ] **Discovery API** (`/api/v1/discover`): HTTP endpoint that surfaces convergent substances across traditions. Blocked by Sprint 5 start (needs all 11 tradition sources ingested).
- [ ] **Full NHPID import**: Current run covers 600 ingredients (test batch). Full 15K run takes ~8h at polite rate. Schedule as overnight VPS job.
- [ ] **Vision LLM PDF parsing**: Some pharmacopoeia PDFs have table-as-image layouts that pdfplumber can't handle. Needs OpenRouter + Claude Vision. Blocked by Sprint 4 JP18/KP12 tickets.

---

## Context

- ⚠️ **HERB search**: HERB 2.0 indexes by Chinese/Pinyin names, NOT Latin binomials. Always use `_PINYIN_ALIASES` or search by English common name. Latin names like `Astragalus membranaceus` return empty.
- ⚠️ **EMA listing**: `/en/medicines/herbal` returns 404 as of 2026-05-03. Individual monograph URLs still work. Tracked as FCV-202c.
- 💡 **Cassette architecture**: Record once with `CASSETTE_MODE=record`, replay forever in CI. Hash is `sha256(scraper_id + canonical_json(request))`. Cassettes are scraper-specific subdirectories under `tests/cassettes/`.
- 💡 **SPA scraping pattern**: When a site is an SPA, use Browserless `/function` endpoint to intercept XHR/fetch requests and discover the underlying JSON API. Then call the API directly — never scrape rendered HTML.

---

## Activation

Items move to active development when:
1. **Focus window opens**: A block of 4+ hours of uninterrupted time is identified.
2. **Resource/budget availability**: External tools, APIs, or budget tiers become accessible.
3. **Measurable failure**: A "functional but fragile" component begins causing repeated issues.
