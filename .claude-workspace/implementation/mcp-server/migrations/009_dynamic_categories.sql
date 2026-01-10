-- migrations/009_dynamic_categories.sql
-- V7.3: Remove fixed category constraint to allow dynamic categories

-- Drop the existing CHECK constraint on category
-- Note: Postgres requires knowing the constraint name to drop it
-- We'll alter the column to remove all constraints and add a simpler one

-- Step 1: Create new column without constraint
ALTER TABLE semantic_event ADD COLUMN IF NOT EXISTS category_new TEXT;

-- Step 2: Copy data (for upgrades, not needed for fresh install)
UPDATE semantic_event SET category_new = category WHERE category_new IS NULL;

-- Step 3: Drop old column and rename (will also drop its constraints)
ALTER TABLE semantic_event DROP COLUMN IF EXISTS category;
ALTER TABLE semantic_event RENAME COLUMN category_new TO category;

-- Step 4: Add simple NOT NULL constraint and index
ALTER TABLE semantic_event ALTER COLUMN category SET NOT NULL;

-- Step 5: Add length check (prevent garbage) - category must be 1-100 chars
ALTER TABLE semantic_event ADD CONSTRAINT category_length CHECK (
    length(category) >= 1 AND length(category) <= 100
);

-- Step 6: Recreate the category index
DROP INDEX IF EXISTS idx_semantic_event_category_time;
CREATE INDEX IF NOT EXISTS idx_semantic_event_category_time
    ON semantic_event (category, event_time DESC NULLS LAST);

-- Step 7: Create category_stats table for tracking usage (ACT-R inspired)
CREATE TABLE IF NOT EXISTS category_stats (
    category VARCHAR(100) PRIMARY KEY,
    occurrence_count INTEGER DEFAULT 1,
    first_seen TIMESTAMP DEFAULT NOW(),
    last_seen TIMESTAMP DEFAULT NOW(),
    last_accessed TIMESTAMP,
    access_count INTEGER DEFAULT 0
);

-- Confirm migration completed
SELECT 'V7.3 dynamic categories migration completed' AS status;
