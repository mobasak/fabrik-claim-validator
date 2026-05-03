"""One-shot data loaders (FCV-102, FCV-103).

These modules ingest large public datasets (WFO Plant List, WHO ICTM TM2)
into our schema. They are designed to be run once in production via the
CLI entry-points below; CI tests exercise them against small fixtures.

Both loaders are idempotent (ON CONFLICT DO UPDATE) — re-running them
after a partial failure will pick up where they left off.
"""
