# QUICKSTART.md — fabrik-claim-validator

**Last Updated:** 2026-05-03

> **Purpose:** INTEGRATION CONTRACT — ENDPOINTS, SDKS, DOCKER WIRING. START HERE FOR INTEGRATION AND SETUP.
> **One-liner:** Multi-tradition herbal medicine claim validator — ingests evidence from 11 traditions, normalises it, and exposes a discovery API for convergent therapeutic substances.
> **Type:** python-api
> **Owner:** Özgür Başak
> **Last verified:** 2026-05-03

---

## Project Identity

| Key | Value |
|-----|-------|
| **Project** | `fabrik-claim-validator` |
| **Port** | `8002` |
| **Production URL** | `https://claim-validator.vps1.ocoron.com` |
| **Local dev URL** | `http://localhost:8002` |
| **Health endpoint** | `GET /health` |
| **OpenAPI docs** | `http://localhost:8002/docs` |
| **Depends on** | PostgreSQL (`postgres-main:5432`) |

---

## Prerequisites

- [ ] Python 3.12+ with project venv at `/opt/fabrik-claim-validator/.venv`
- [ ] PostgreSQL (local dev via peer auth as `ozgur`, VPS via `postgres-main`)
- [ ] `.env` file configured (copy from `.env.example`)
- [ ] Docker + Docker Compose (for VPS deployment only)

---

## Local Development (WSL)

<!-- This section applies if project uses PostgreSQL. Delete if stateless/API-only. -->

### Database Setup

**Database name:** `fabrik_claim_validator_dev`
**Connection:** `postgresql://ozgur@localhost:5432/fabrik_claim_validator_dev` (peer auth)

```bash
sudo -u postgres psql -c "CREATE DATABASE fabrik_claim_validator_dev OWNER ozgur;"
```

### Running Locally

```bash
cd /opt/fabrik-claim-validator
source .venv/bin/activate

# Use local development config
cp .env.local .env

# Apply schema migrations (13 through Sprint 2.5)
set -a && source .env.local && set +a
alembic upgrade head

# Run tests (cassette replay, no network)
pytest

# Start development server
uvicorn fabrik_claim_validator.main:app --port 8002 --reload
```

### Database Access

```bash
psql fabrik_claim_validator_dev

# Key tables
\dt              # List all tables
\d compounds     # 449K+ botanical taxa from WFO
\d monographs    # EMA HMPC + NHPID monographs
\d taxa_aliases  # Cross-tradition name mappings
\d cache_entries # Upstream API response cache (90d TTL)
\d scrape_queue  # Batch scraping job queue
```

---

## Quick Start (Docker - VPS Deployment)

```bash
# Clone and configure
git clone {repo_url} && cd {fabrik-claim-validator}
cp .env.example .env
# Edit .env — fill required values (see Environment Variables below)

# Start
docker compose up -d

# Verify
curl http://localhost:8002/health
```

<!-- For non-Docker projects, replace with the appropriate start command: -->
<!-- Python API: /opt/{project}/.venv/bin/uvicorn src.{package}.main:app --reload --port 8002 -->
<!-- Node: npm install && npm run dev -->
<!-- Static site: npm install && npm run build && npm run preview -->
<!-- Chrome extension: npm install && npm run build → load dist/ in chrome://extensions -->

---

## Health & Readiness

**Healthy:**
```bash
curl -sf http://localhost:8002/health
# → 200
```
```json
{
  "status": "ok",
  "version": "0.1.0",
  "dependencies": {
    "postgres": "connected"
  }
}
```

**Unhealthy:**
```
→ 503 — one or more dependencies unreachable. Check response body for details.
```

---

## Primary Workflows

### 1. Resolve a herb via HERB 2.0 API

```python
import asyncio
from fabrik_claim_validator.resolvers.herb_ac_cn import HerbAcCnResolver

async def main():
    async with HerbAcCnResolver() as resolver:
        result = await resolver.fetch_detail("Salvia miltiorrhiza")
        print(f"ID: {result['herb_id']}")
        print(f"Ingredients: {len(result['ingredients'])}")
        print(f"Targets: {len(result['targets'])}")
        print(f"Diseases: {len(result['diseases'])}")

asyncio.run(main())
```

Returns: `herb_id`, `targets` (gene symbols), `ingredients`, `diseases`, `clinical_trials` (NCT IDs), `related_papers` (PMIDs), `summary`.

### 2. Resolve a compound via PubChem

```python
import asyncio
from fabrik_claim_validator.resolvers.pubchem import PubChemResolver

async def main():
    async with PubChemResolver() as resolver:
        result = await resolver.name_to_properties("aspirin")
        print(result)  # CID, formula, CAS, SMILES, etc.

asyncio.run(main())
```

### 3. Run the EMA monograph scraper

```bash
cd /opt/fabrik-claim-validator
# See docs/operations/data_ingest.md § FCV-254 for full runbook
python scripts/ema_spotcheck.py
```

### 4. Record fresh cassettes

```bash
CASSETTE_MODE=record python -c "
import asyncio
from fabrik_claim_validator.resolvers.herb_ac_cn import HerbAcCnResolver

async def main():
    async with HerbAcCnResolver() as r:
        await r.fetch_detail('Ginseng')

asyncio.run(main())
"
# Cassettes written to tests/cassettes/herb_ac_cn/
```

---

## API Reference (Compact)

### Health & Diagnostics

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Service health — checks PostgreSQL connectivity (200 / 503) |

### Data Ingestion (Python API — not HTTP endpoints yet)

| Module | Class/Function | Purpose |
|--------|---------------|---------|
| `resolvers.herb_ac_cn` | `HerbAcCnResolver.fetch_detail(name)` | HERB 2.0 herb lookup (search + detail) |
| `resolvers.herb_ac_cn` | `HerbAcCnResolver.search_herb(keyword)` | HERB 2.0 keyword search |
| `resolvers.pubchem` | `PubChemResolver.name_to_properties(name)` | PubChem compound lookup |
| `scrapers.ema_hmpc` | `EmaHmpcScraper.process_queue(pool)` | EMA monograph batch processor |
| `scrapers.nhpid` | `NhpidScraper.scrape(pool)` | NHPID ingredient scraper |
| `loaders.wfo_seed` | CLI: `python -m ...wfo_seed --file <path>` | WFO botanical taxonomy bulk loader |

**Note:** HTTP API endpoints for discovery (`/api/v1/discover`) are planned for Sprint 5.

---

## Integration

<!-- How other services, agents, or automations connect to this project.
     Delete this entire section for user-facing-only projects (chrome extension, static site, desktop app)
     that are never called by other services. -->

### Authentication

<!-- State explicitly even if "none". -->

```text
No authentication required. Internal Docker network trust.
```
<!-- Or: X-API-Key: ${PROJECT_NAME_API_KEY} -->
<!-- Or: Authorization: Bearer ${TOKEN} -->

### Language Integration (copy-paste)

**Python:**

```python
import httpx, os

{PROJECT}_URL = os.getenv("{PROJECT_NAME}_URL", "http://{fabrik-claim-validator}:8002")

class {Project}Client:
    def __init__(self, base_url: str = {PROJECT}_URL):
        self.c = httpx.Client(base_url=base_url, timeout=30.0)

    def health(self) -> bool:
        return self.c.get("/health").status_code == 200

    def {primary_action}(self, payload: dict) -> dict:
        r = self.c.post("/api/v1/{resource}", json=payload)
        r.raise_for_status()
        return r.json()
```

**TypeScript:**

```typescript
const {PROJECT}_URL = process.env.{PROJECT_NAME}_URL ?? "http://{fabrik-claim-validator}:8002";

export const {project} = {
  health: async () => (await fetch(`${{{PROJECT}_URL}}/health`)).ok,
  {primaryAction}: async (payload: Record<string, unknown>) => {
    const r = await fetch(`${{{PROJECT}_URL}}/api/v1/{resource}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(`{fabrik-claim-validator} ${r.status}: ${await r.text()}`);
    return r.json();
  },
};
```

**cURL:**

```bash
curl -sf http://{fabrik-claim-validator}:8002/health | jq .

curl -X POST http://{fabrik-claim-validator}:8002/api/v1/{resource} \
  -H "Content-Type: application/json" \
  -d '{"field_1": "value"}'
```

### Docker Compose — Caller Wiring

**Same Coolify stack:**

```yaml
services:
  your-service:
    environment:
      - {PROJECT_NAME}_URL=http://{fabrik-claim-validator}:8002
    depends_on:
      {fabrik-claim-validator}:
        condition: service_healthy
    networks:
      - coolify
```

**Cross-stack (external network):**

```yaml
services:
  your-service:
    environment:
      - {PROJECT_NAME}_URL=http://{fabrik-claim-validator}:8002
    networks:
      - coolify

networks:
  coolify:
    external: true
```

### Rate Limits

<!-- State explicitly. "None" is valid. -->

| Scope | Limit | Behavior |
|-------|-------|----------|
| None | — | No rate limiting applied |

### Request Tracing

<!-- Delete if not supported. -->
Every response includes `X-Request-ID`. Pass it in requests to correlate across logs.

---

## Automation

<!-- Delete patterns that don't apply. Delete entire section for non-service projects. -->

### n8n

```text
HTTP Request node:
  Method: POST
  URL: http://{fabrik-claim-validator}:8002/api/v1/{resource}
  Body (JSON): { "field_1": "{{ $json.input }}" }
  → Route: 200 → continue | 429 → Wait 60s → Retry | 5xx → Error workflow
```

### Cron

```bash
0 2 * * * curl -sf -X POST http://{fabrik-claim-validator}:8002/api/v1/maintenance/cleanup
```

---

## Error Handling

| Status | Meaning | Recovery |
|--------|---------|----------|
| `400` | Validation failed | Check `error.details` in response |
| `404` | Not found | Verify resource exists |
| `429` | Rate limited | Retry after `Retry-After` header |
| `500` | Internal error | Retry once after 5s |
| `503` | Dependency down | Check `/health` for details |

<!-- Delete codes your project never returns. Add project-specific codes. -->

**Error response shape:**
```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Human-readable description",
    "details": {}
  }
}
```

**Retry pattern:**

```python
import time, httpx

def call_with_retry(fn, max_retries=3):
    for attempt in range(max_retries):
        try:
            return fn()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 503) and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise
```

---

## Environment Variables

### Project config

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORT` | No | `8002` | Service port |
| `DATABASE_URL` | {Yes/No} | — | PostgreSQL connection string |
| `LOG_LEVEL` | No | `info` | Logging level |

<!-- Add all project-specific variables. -->

### For callers (if this is a service)

```env
{PROJECT_NAME}_URL=http://{fabrik-claim-validator}:8002
```

---

## Agent Context Block

<!-- Copy-paste into Cascade / Kilo sessions that need to work WITH this project (not inside it).
     Must be fully self-contained — an agent reading only this block can make correct calls.
     Delete this section for projects that are never called by other services or agents. -->

```text
## {PROJECT_NAME}
- URL: http://{fabrik-claim-validator}:8002 (Docker) | https://{project}.vps1.ocoron.com (external)
- Auth: {None / X-API-Key header}
- Health: GET /health → 200 = ready, 503 = stop

Primary operations:
  - POST /api/v1/{resource} → {"field_1": "value", "field_2": 123}
  - GET /api/v1/{resource}/:id
  - DELETE /api/v1/{resource}/:id

Error shape: {"error": {"code": "...", "message": "...", "details": {...}}}
Env for callers: {PROJECT_NAME}_URL=http://{fabrik-claim-validator}:8002
```

## Agent Gotchas

| Gotcha | Why it fails | Correct approach |
|--------|-------------|------------------|
| Calling without checking `/health` | 503 during cold start | Poll `/health` first |
| Missing `Content-Type: application/json` | 400 on POST/PUT | Always include header |

<!-- Add project-specific gotchas as they surface. -->

---

## Local Development

→ Full setup: [`README.md`](../README.md)

```bash
git clone {repo_url} && cd {fabrik-claim-validator}
cp .env.example .env
docker compose up -d
curl http://localhost:8002/health
```

---

## Reference Links

<!-- Only link docs that exist. Delete unused rows. -->

| Document | Path |
|----------|------|
| Features | `./docs/FEATURES.md` |
| Configuration | `./docs/CONFIGURATION.md` |
| API reference | `./docs/reference/REST_API_REFERENCE.md` |
| Troubleshooting | `./docs/TROUBLESHOOTING.md` |
| Changelog | `./CHANGELOG.md` |
