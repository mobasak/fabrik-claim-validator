# fabrik-claim-validator

**Last Updated:** 2026-05-03

> **Purpose:** PRIMARY ENTRY POINT — OVERVIEW, TECH STACK, REQUIREMENTS.

Multi-tradition claim validation + substance discovery service. Sibling to fabrik-citation-verifier. Validates substance/indication claims across 11 medical traditions with peer-equal evidence weighting; surfaces convergent substances via discovery endpoint.

**Type:** python-api (FastAPI)
**Port:** 8002 (registered in `/opt/fabrik/PORTS.md`)

---

## Quick Start

WSL dev (PostgreSQL via Unix socket, peer auth as `ozgur`):

```bash
cd /opt/fabrik-claim-validator
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # adjust if needed; .env.local is git-tracked for WSL defaults

# Apply schema migrations
set -a && source .env.local && set +a
alembic upgrade head

# Run tests
pytest

# Run service
uvicorn fabrik_claim_validator.main:app --port 8002 --reload
curl http://localhost:8002/health
```

VPS prod is Coolify-managed; see `compose.yaml`.

## Overview

Multi-tradition herbal medicine claim validator. Ingests substance, indication, and evidence data from 11 medical traditions (EMA, NHPID, HERB/TCM, Ayurveda, Kampo, etc.), normalises it into a common schema, and exposes a discovery API that surfaces convergent substances — herbs where multiple independent traditions agree on the same therapeutic use.

**Current data sources (Sprint 2.5):** WFO botanical taxonomy (449K+ taxa), EMA HMPC monographs (PDF-parsed), Health Canada NHPID ingredients, HERB 2.0 (TCM herbs via JSON API — ingredients, gene targets, diseases, clinical trials).

## Tech Stack

- **Runtime:** Python 3.12
- **Framework:** FastAPI + Uvicorn
- **Database:** PostgreSQL 16 (shared `postgres-main:5432`, schema via Alembic migrations)
- **HTTP client:** httpx (async) with cassette-based test recording/replay
- **PDF parsing:** pdfplumber + custom `PdfMonographParser`
- **Deployment:** Docker → Coolify → VPS (amd64, bookworm-slim base)

## Requirements

- Python 3.12+ with venv
- PostgreSQL (local dev via peer auth, VPS via `postgres-main`)
- `.env` configured from `.env.example`

## Documentation

See [INDEX.md](INDEX.md) for master file index and documentation links.
