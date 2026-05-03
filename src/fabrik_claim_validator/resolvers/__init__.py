"""External-source resolvers for Sprint 1 (FCV-101..104).

Each resolver is a thin async HTTP client against a public data source that
normalises rows into our schema (`compounds`, `taxa_aliases`, `cache_entries`).

Rate limits are per-resolver (token bucket) because the upstream politeness
budget differs: PubChem tolerates 5 req/s, herb.ac.cn wants ~1 req/2s.
"""
