-- migrations/006_triggers.sql
-- Create triggers for automatic timestamp updates

-- Auto-update updated_at column on event_jobs
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER IF NOT EXISTS update_event_jobs_updated_at
BEFORE UPDATE ON event_jobs
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- Confirm triggers created
SELECT 'Triggers created successfully' AS status;
