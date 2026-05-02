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
| TBD | Main service | Add your allocations here |

---

## Notes

- Register all ports in this file before using them
- Check this file before adding new services to avoid conflicts
