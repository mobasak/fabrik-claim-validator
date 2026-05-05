# Configuration — fabrik-claim-validator

**Last Updated:** 2026-05-03

> **Purpose:** ENVIRONMENT VARIABLES AND SETTINGS.
> For the variable list itself, see `.env.example` — it's self-documenting.

---

## Quick Setup

```bash
cp .env.example .env
# Edit .env — fill required values (port is pre-assigned in .env.example)
docker compose up -d
curl http://localhost:$PORT/health
```

---

## Environment Variables

<!-- This is the authoritative reference for all variables.
     .env.example has the same list with inline comments, but this doc explains WHY and HOW.
     Port is auto-assigned by scaffold and recorded in project.yaml and .env.example — do not hardcode. -->

### Required

| Variable | Example | Description |
|----------|---------|-------------|
| `PORT` | `8002` | Service port (registered in `PORTS.md`) |
| `DATABASE_URL` | `postgresql://ozgur@localhost:5432/fabrik_claim_validator_dev` | PostgreSQL connection string. WSL: peer auth. VPS: `postgres-main:5432` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `CASSETTE_MODE` | `replay` | HTTP test recording mode: `replay` (CI), `record` (live capture), `passthrough` (dev) |
| `CASSETTE_DIR` | `tests/cassettes` | Directory for cassette JSON files |
| `HERB_BASE_URL` | `http://47.92.70.12` | HERB 2.0 API base URL. Override for local dev or alternate mirrors |
| `BROWSERLESS_URL` | `https://browser.vps1.ocoron.com` | Browserless v2 (headless Chrome). Required for DTAM scraper (FCV-305) |
| `BROWSERLESS_TOKEN` | *(secret)* | Auth token for Browserless v2. Append `?token=` to all requests |
| `CAPTCHA_URL` | `http://localhost:18011` | Anti-Captcha service URL (Sprint 3+) |
| `PROXY_URL` | `http://localhost:18013` | Proxy management service URL. Supports `?country_code=IR&sticky=true` for geo-targeting |
| `CITATION_VERIFIER_URL` | `http://localhost:8032` | Sibling citation verifier service |
| `KILO_VISION_AGENT_ID` | `anthropic/claude-opus-4.6` | Vision LLM for PDF table-as-image extraction (Sprint 4) |
| `OPENROUTER_API_KEY` | *(empty in dev)* | OpenRouter key for vision LLM. Cassette replay in CI |
| `SERVICE_NAME` | `fabrik-claim-validator` | Identity for structured JSON logs |

---

## Getting Credentials

### OpenRouter (Vision LLM — Sprint 4+)

**Why needed:** PDF table-as-image extraction for pharmacopoeia monographs with complex layouts.

**How to get:**
1. Go to `https://openrouter.ai/`
2. Create API key
3. Add to `.env`: `OPENROUTER_API_KEY=your_key_here`

**Limits:** Pay-per-token. Not needed for CI (cassette replay). Not needed until Sprint 4.

### Database

**Shared postgres-main (recommended for Fabrik services):**

```bash
DATABASE_URL=postgresql://[project]:password@postgres-main:5432/[project]
```

**Local PostgreSQL (dev only):**

```bash
DATABASE_URL=postgresql://localhost:5432/[project]_dev
```

---

## Environment Profiles

### Development (WSL)

```bash
PORT=8002
LOG_LEVEL=DEBUG
DATABASE_URL=postgresql://ozgur@localhost:5432/fabrik_claim_validator_dev
CASSETTE_MODE=replay
HERB_BASE_URL=http://47.92.70.12
```

### Production (VPS / Coolify)

```bash
PORT=8002
LOG_LEVEL=INFO
DATABASE_URL=postgresql://fabrik_claim_validator:${POSTGRES_PASSWORD}@postgres-main:5432/fabrik_claim_validator
CASSETTE_MODE=passthrough
HERB_BASE_URL=http://47.92.70.12
```

**Production rules:**
- No `localhost` or `127.0.0.1` — use Docker service names (`postgres-main`, `redis`)
- No hardcoded credentials — use `${VARIABLE}` references
- Use `${VAR:?required}` in compose.yaml for critical vars to fail fast

---

## Port Allocation

Port is auto-assigned during scaffolding and stored in `project.yaml` and `.env.example`.

Ranges: Python APIs 8000–8099, Frontend 3000–3099, Workers 8100–8199.

Before adding new ports, check `PORTS.md` for conflicts:

```bash
cat PORTS.md
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Config validation failed | Missing required env var | Check `.env` against `.env.example` |
| Port already in use | Another service on same port | Check `PORTS.md`, pick next available |
| Database unreachable | Wrong `DATABASE_URL` or network | Verify: `psql $DATABASE_URL` |
| Service starts but unhealthy | Dependency not ready | Check `/health` response for failing deps |

```bash
# Debug commands
psql $DATABASE_URL              # Test DB connection
lsof -i :$PORT                  # Check port availability
cat .env | grep -v '^#|^$'      # Show active env vars
```

## Configuration Checklist

Before deploying:

- [ ] `.env` created from `.env.example`
- [ ] All required credentials obtained
- [ ] **Port registered in `PORTS.md`** (MANDATORY — deployment may fail otherwise)
- [ ] Database accessible (if used)
- [ ] Health endpoint returns 200 AND tests DB: `curl http://localhost:${PORT}/health`
- [ ] No hardcoded `localhost` in `compose.yaml` (use service names)
- [ ] Logs writing to expected location
- [ ] Environment-specific settings verified (dev vs prod)
- [ ] amd64 compatibility confirmed (base images use `-slim-bookworm`, not Alpine)
