# fabrik-claim-validator Port Allocations

**Last Updated:** 2026-05-03

This document tracks port allocations for fabrik-claim-validator services to prevent conflicts.

---

## Port Ranges

| Range | Purpose | Environment |
|-------|---------|-------------|
| 3000-3099 | Frontend apps (Node.js) | WSL & VPS |
| 5000-5099 | Python services (misc) | WSL only |
| 8000-8099 | Python APIs (FastAPI) | WSL & VPS |
| 8100-8199 | Workers & background services | WSL & VPS |

---

## Current Allocations

| Port | Service | URL/Purpose |
|------|---------|-------------|
| 8002 | fabrik-claim-validator | FastAPI main — `http://localhost:8002` (registered in `/opt/fabrik/PORTS.md`) |
| 8032 | fabrik-citation-verifier | Sibling service — citation verification (upstream dependency) |
| 18011 | /opt/captcha | Captcha solver (Anti-Captcha-backed HTTP service) — upstream dep for scrapers |
| 18013 | /opt/proxy | Residential-proxy manager (Webshare) — upstream dep for scrapers |

---

## Notes

- Register all ports in this file before using them
- Check this file before adding new services to avoid conflicts
