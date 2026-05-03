-- Database Schema
-- Project: fabrik-claim-validator
-- Last Updated: 2026-05-03
--
-- This file tracks all database schema changes.
-- Agents MUST update this file when making database changes.
--
-- Usage:
--   - Add new tables/columns with CREATE statements
--   - Document changes with comments including date
--   - Keep this file as the source of truth for DB structure

-- =============================================================================
-- TABLES
-- =============================================================================

-- Example:
-- CREATE TABLE IF NOT EXISTS users (
--     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--     email VARCHAR(255) UNIQUE NOT NULL,
--     created_at TIMESTAMPTZ DEFAULT NOW(),
--     updated_at TIMESTAMPTZ DEFAULT NOW()
-- );

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Example:
-- CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Sprint 2: scrape_queue (FCV-201, migration 0012)
CREATE TABLE IF NOT EXISTS scrape_queue (
    id              BIGSERIAL PRIMARY KEY,
    scraper_id      TEXT NOT NULL,
    url             TEXT NOT NULL,
    priority        INT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    worker_id       INT,
    attempts        INT NOT NULL DEFAULT 0,
    max_attempts    INT NOT NULL DEFAULT 3,
    last_error      TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    CONSTRAINT scrape_queue_status_chk
        CHECK (status IN ('pending','processing','done','failed'))
);
CREATE INDEX IF NOT EXISTS scrape_queue_scraper_status_idx
    ON scrape_queue(scraper_id, status, priority DESC);
CREATE UNIQUE INDEX IF NOT EXISTS scrape_queue_url_uniq
    ON scrape_queue(scraper_id, url);

-- =============================================================================
-- CHANGE LOG
-- =============================================================================
-- 2026-05-03: Initial schema created
-- 2026-05-03: Sprint 2 — added scrape_queue table (migration 0012)
-- 2026-05-03: Sprint 2.5 FCV-251 — replaced taxa_aliases_uniq with two partial
--   unique indexes (migration 0013): taxa_aliases_uniq_with_tradition (WHERE
--   tradition_code IS NOT NULL) and taxa_aliases_uniq_null_tradition (WHERE
--   tradition_code IS NULL). Fixes NULL-tradition row duplication on re-seed.
