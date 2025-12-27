-- migrations/001_enable_extensions.sql
-- Enable required PostgreSQL extensions

-- UUID generation (built-in for Postgres 13+)
-- gen_random_uuid() is available by default

-- Enable pgcrypto for additional crypto functions if needed
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Confirm extensions
SELECT 'Extensions enabled successfully' AS status;
