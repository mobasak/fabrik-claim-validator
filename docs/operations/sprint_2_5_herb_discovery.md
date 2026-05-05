# HERB 2.0 Discovery Report — FCV-253

**Date:** 2026-05-03
**Phase:** Sprint 2.5 — HERB resolver rewrite

## Phase 1 Findings

### 1a. Reachability

| Endpoint | Status | Notes |
|----------|--------|-------|
| `http://47.92.70.12/` (HERB 2.0) | ✅ HTTP 200 | Bare IP, no TLS |
| `http://herb.ac.cn/` (HERB 1.0) | ✅ HTTP 200 | Domain resolves to 47.92.70.12 |
| `http://herb.ac.cn/v2` | ✅ 301 → 2.0 | Redirect works |
| `http://herb.cuilab.cn/` | ❌ DNS fail | Old domain, defunct |

### 1b. Search Page — SPA (not server-rendered)

Both v1 and v2 serve a React SPA shell (`<div id="root"></div>` + `umi.js` bundle).
`grep -c "ginseng\|HERB[0-9]" search.html` → **0** for both versions.

### 1c. JSON API Discovery

Used **Browserless** (`browser.vps1.ocoron.com/function`) to render the SPA and intercept
XHR requests. Found:

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/chedi/api/` | POST | `{"keyword":"ginseng","label":"Herb","func_name":"search_api"}` | JSON with herb IDs, names, links |
| `/chedi/api/` | POST | `{"v":"HERB002319","label":"Herb","key_id":"HERB002319","func_name":"detail_api"}` | 480KB JSON (ingredients, targets, diseases, trials, papers) |

**No Browserless needed for production** — the JSON API is callable directly with `httpx`.

### 1d. HERB 2.0 Data Richness

Detail response for Red Ginseng (HERB002319) contains:
- `herb_ingredient`: 104 ingredients with SMILES, molecular formulas
- `herb_target`: 4 gene targets (with p-values)
- `herb_disease`: 431 diseases (with p-values, FDR)
- `drug_paper_target`: 37 paper-backed targets
- `drug_paper_disease`: 24 paper-backed diseases
- `clinical_herb`: 34 clinical trials (NCT IDs, phases, conditions)
- `meta_herb`: 6 meta-analyses (CRD IDs)
- `summary`: Pinyin, Chinese, English, Latin names, property, meridian, function, indication

## Decision: Target HERB 2.0 via JSON API (Phase 2B equivalent)

**Chosen path:** Direct `POST /chedi/api/` calls with `httpx`. No Browserless, no proxy needed.

**Key discovery:** HERB 2.0 search indexes by Chinese/Pinyin names. Latin binomials
(`Astragalus membranaceus`) often return empty. Solution: Pinyin alias lookup table
(`_PINYIN_ALIASES`) maps Latin names to Pinyin search terms.

## 10-Herb Corpus Results

| Latin Name | Pinyin | HERB ID | Ingredients | Targets | Diseases | Status |
|------------|--------|---------|-------------|---------|----------|--------|
| Panax ginseng | Ren Shen | HERB004615 | 11 | 0 | 0 | ✅ |
| Astragalus membranaceus | Huang Qi | HERB002560 | 162 | 52 | 228 | ✅ |
| Glycyrrhiza uralensis | Gan Cao | HERB001780 | 11 | 24 | 0 | ✅ |
| Bupleurum chinense | Chai Hu | HERB000638 | 419 | 44 | 2 | ✅ |
| Salvia miltiorrhiza | Dan Shen | HERB001193 | 306 | 119 | 124 | ✅ |
| Rehmannia glutinosa | Di Huang | HERB005974 | 10 | 0 | 269 | ✅ |
| Angelica sinensis | Dang Gui | HERB001210 | 251 | 0 | 0 | ✅ |
| Atractylodes macrocephala | Bai Zhu | HERB000309 | 142 | 0 | 0 | ✅ |
| Codonopsis pilosula | Dang Shen | HERB005809 | 26 | 0 | 0 | ✅ |
| Schisandra chinensis | Wu Wei Zi | HERB005762 | 158 | 0 | 164 | ✅ |

**10/10 resolved successfully.** 0 failures → no FCV-253b needed.

## Configuration

- `HERB_BASE_URL` env var (default: `http://47.92.70.12`)
- Rate limit: 1 req / 2s (TokenBucket 0.5 rps)
- Cassettes: 24 files recorded in `tests/cassettes/herb_ac_cn/`
