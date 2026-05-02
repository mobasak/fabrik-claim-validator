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

-- =============================================================================
-- CHANGE LOG
-- =============================================================================
-- 2026-05-03: Initial schema created
