# fabrik-claim-validator

**Last Updated:** 2026-05-03

> **Purpose:** PRIMARY ENTRY POINT — OVERVIEW, TECH STACK, REQUIREMENTS.

Multi-tradition claim validation + substance discovery service. Sibling to fabrik-citation-verifier. Validates substance/indication claims across 11 medical traditions with peer-equal evidence weighting; surfaces convergent substances via discovery endpoint.

**Type:** {python-api | node-api | saas-skeleton | chrome-extension | mobile-app | desktop-app | static-site}
**Port:** {PORT}

---

## Overview

<!-- 2–3 sentences: what this project does, who it's for, what problem it solves. -->

## Tech Stack

<!-- Replace with actual stack. Delete lines that don't apply. -->

- **Runtime:** Python 3.12 / Node 22
- **Framework:** FastAPI / Next.js / Hono
- **Database:** PostgreSQL (shared `postgres-main:5432`)
- **Cache:** Redis (`redis:6379`)
- **Deployment:** Docker → Coolify → VPS

## Requirements

- Docker + Docker Compose
- `.env` configured from `.env.example`

## Documentation

See [INDEX.md](INDEX.md) for master file index and documentation links.
