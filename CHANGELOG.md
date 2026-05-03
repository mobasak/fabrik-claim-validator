# Changelog — fabrik-claim-validator

**Last Updated:** 2026-05-03

All notable changes to this project are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Fixed — Tier-2 gate doc-structure findings (2026-05-03)

- Move `AFCL.md` from project root to `docs/reference/AFCL.md` (gate: forbidden md in root)
- Add `## docs/ Files` section to `INDEX.md` (gate: required section missing)
- Add `## Quick Start` section to `README.md` with WSL dev bring-up commands
  (alembic upgrade, pytest, uvicorn) (gate: required section missing)
- Update `README.md` Type/Port from scaffold placeholders to `python-api (FastAPI)` / `8002`

### Changed — PLAN.md ticket status indicators (2026-05-03)

- Add per-ticket status legend (✅ done · 🟡 partial · ⬜ not started) and prefix all 54
  Sprint 0–6 tickets with their status icon in `docs/development/PLAN.md`
- Mark FCV-001 / FCV-002 as ✅ done (with implementer + artefact references); FCV-011 as
  🟡 partial (port allocation registered, AGENTS.md self-validation contract still pending);
  remaining 51 tickets as ⬜ not started

### Added — Sprint 0 foundation: schema migrations + traditions seed (2026-05-03)

- Add `alembic.ini` + `alembic/env.py` (psycopg3 sync driver, `.env.local` loader) (FCV-001 scaffolding)
- Add alembic migrations `0001_traditions` through `0010_ingest_log` implementing plan §4 DDL
  (10 tables, indexes, FK + CHECK constraints enforcing tri-state `direction` enum and
  evidence-quality grades at the schema level) (FCV-001)
- Add migration `0011_traditions_seed` inserting 12 peer-equal traditions per plan §5.2,
  with parent-tradition FKs (kampo/dong_y → tcm, tpm → unani) and per-tradition
  `evidence_tier_map` JSONB for Sprint 5 aggregator (FCV-002)
- Add `tests/test_migrations.py` round-trip test (downgrade → upgrade → assert tables, seed
  count, parent FKs, tri-state CHECK) — one-test-rule regression for FCV-001/002

### Changed — Port allocation (2026-05-03)

- Change `.env.example` PORT 8000 → 8002 (matches `/opt/fabrik/PORTS.md` assignment;
  plan's 8033 was stale — collides with ComplianceOps)
- Change `.env.local` DATABASE_URL to socket-auth DSN (`postgresql://ozgur@/...`)
- Fill in `PORTS.md` current-allocations table (was `TBD`)
- Add `sqlalchemy`, `asyncpg`, `alembic`, `psycopg[binary]`, `structlog` to `pyproject.toml`
  core dependencies (were commented out)

### Added — (2026-05-03)

- Initial project scaffolded

---

<!-- Entry format:

### Category — Title (2026-05-03)
- Action verb + file/function/endpoint + what changed

Categories: Added, Changed, Fixed, Removed, Security

Examples:
  ### Added — DNS provisioning endpoint (2026-04-09)
  - Add `POST /api/v1/zones/{domain}/provision` with DNSSEC and WAF support
  - Add `DnsManagerClient` Python SDK module

  ### Fixed — Health check false positives (2026-04-09)
  - Fix `/health` returning 200 when Redis is unreachable

  ### Security — API key validation (2026-04-09)
  - Add rate limiting on auth endpoints to prevent brute force

  ### Changed — Response format update (2026-04-09)
  - Change error responses from flat strings to `{"error": {"code", "message", "details"}}` shape
  - BREAKING: Remove `status_text` field from all responses

-->

## Versioning

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** (X.0.0): Incompatible API changes
- **MINOR** (0.X.0): New functionality, backwards compatible
- **PATCH** (0.0.X): Bug fixes, backwards compatible

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| X.Y.Z | 2026-05-03 | Brief summary |
| X.Y.Y | 2026-05-03 | Brief summary |

---

## Versioning

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** (X.0.0): Incompatible API changes
- **MINOR** (0.X.0): New functionality, backwards compatible
- **PATCH** (0.0.X): Bug fixes, backwards compatible

---

## Workflow Integration

**Step 3: CHANGELOG** in the agent completion contract requires one entry per task.

**Enforcement:** `python scripts/final_gate.py --lean --json` checks for changelog presence (Tier 1).

**Format required:**
```
### Category — Title (2026-05-03)
- Action verb + function/file + description
```

**Categories:** Added, Changed, Fixed, Removed, Security

Agents write entries manually. Gate enforces presence but not content quality.
