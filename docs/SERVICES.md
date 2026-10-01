# fabrik-claim-validator — Services

<!--
  CANONICAL SERVICE REGISTRY. Auto-seeded 2026-06-04 from project.yaml + compose.yaml +
  .env.example. STRUCTURED data (services, ports, detected vendors) is filled in;
  PROSE fields ([purpose], capabilities, why-it-exists, status) are TODO — complete them.
  Keep current: check_compose_services.py requires every compose service documented here.
-->

## Services This Project Runs

| Service | Port | Health Endpoint | Purpose |
|---------|------|-----------------|---------|
| fabrik-claim-validator | 8000 | `/health` | [purpose] |

Deployed via **SSH + Docker Compose** direct to the VPS (no intermediary platform).
Traefik handles external HTTPS; container ports are **not** exposed publicly. DB and
cache use Docker DNS — `postgres-main:5432`, `redis-main:6379` — never `localhost`.

## External Dependencies

> Auto-detected from `.env.example`. Fill in the **Purpose** column and add the rich
> per-service block (Cost / Capabilities / Limitations / Why it exists / Status) for
> any dependency with real operational nuance.

| Service | Env Var | Purpose |
|---------|---------|---------|
| **OpenRouter** | `OPENROUTER_API_KEY` | [purpose] |
| **[BROWSERLESS — fill in]** | `BROWSERLESS_TOKEN` | [purpose] |

<!--
Rich block to add per nuanced dependency:

**[Service Name]** — [one-line role]
- Env: `ENV_VAR`
- Cost: [free · $X/mo]
- Capabilities: [...]
- Limitations: [...]
- Used in: [...]
- Why it exists: [...]
- Status: ✅ Working | ⚠️ Partial | ⏳ Pending | ❌ Blocked
-->

### Shared Fabrik Infrastructure (internal)

| Service | Env Var | Purpose |
|---------|---------|---------|
| postgres-main | `DATABASE_URL` | Shared PostgreSQL |

### Service Status Summary (2026-06-04)

| Service | Status | Notes |
|---------|--------|-------|
| OpenRouter | ⏳ TODO | |

## Service Details

### fabrik-claim-validator API

- **Port:** 8002
- **Health Check:** `curl http://localhost:8002/health`
- **API Docs:** `http://localhost:8002/docs`
- **Logs:** `/opt/fabrik-claim-validator/logs/` (local) · Loki → Grafana (VPS)
- **Project Path:** `/opt/fabrik-claim-validator`

## Service Management (Docker)

```bash
sudo docker ps | grep fabrik-claim-validator
cd /opt/fabrik-claim-validator && sudo docker compose restart
sudo docker compose logs -f
```

## Quick Verification

```bash
curl -sS https://fabrik-claim-validator.vps1.ocoron.com/health | jq .
curl -sS https://status.vps1.ocoron.com/api/v1/endpoints/statuses | jq '.[] | {name, ok: .results[-1].success}'
```

## Troubleshooting

### Service Returns 503
Health check failed — a dependency or config is missing. Hit `/health` to see which check failed.

### Dependency / Auth Errors
Check the env var for the failing service. On the VPS, secrets live in root-owned
`/opt/fabrik-claim-validator/.env` — update via `fabrik apply` / `fabrik redeploy --refresh-infra`, never by hand.

### Port Already In Use
Check `PORTS.md`, change the port, redeploy.
