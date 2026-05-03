"""fabrik-claim-validator services package.

Each service is a thin async module wrapping one external concern:

- ``cache``               — 90-day persistent scraper cache (FCV-003)
- ``discovery_cache``     — 24h convergence-query cache (FCV-004)
- ``cassettes``           — record/replay HTTP-fixture infra (FCV-005)
- ``captcha``             — wrapper around ``/opt/captcha`` HTTP service (FCV-006)
- ``proxy``               — wrapper around ``/opt/proxy`` HTTP service (FCV-006)
- ``citation_verifier``   — client for sibling ``fabrik-citation-verifier`` (FCV-007)
- ``budget``              — proxy_budget bookkeeping + hard-stop (FCV-010)
- ``ingest_log``          — per-fetch telemetry rows (FCV-010)
"""
