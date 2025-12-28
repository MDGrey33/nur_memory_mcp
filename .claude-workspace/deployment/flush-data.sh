#!/bin/bash
# MCP Memory Server - Flush All Data
# Clears ChromaDB collections and PostgreSQL tables
# Use this for a fresh start during development

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.v3.yml"

echo "==================================="
echo "MCP Memory Server - Data Flush"
echo "==================================="
echo ""
echo "WARNING: This will delete ALL data:"
echo "  - All memories"
echo "  - All artifacts and chunks"
echo "  - All conversation history"
echo "  - All semantic events"
echo "  - All job queue entries"
echo ""
read -p "Are you sure? (type 'yes' to confirm): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Flushing data..."

# Check if containers are running
if ! docker compose -f "$COMPOSE_FILE" ps --status running | grep -q "mcp-server\|postgres\|chroma"; then
    echo "Error: Services not running. Start with: docker compose -f docker-compose.v3.yml up -d"
    exit 1
fi

# 1. Flush PostgreSQL tables (preserve schema)
echo ""
echo "[1/2] Flushing PostgreSQL tables..."
docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U events -d events << 'EOF'
-- Truncate all tables (CASCADE handles foreign keys)
TRUNCATE TABLE event_evidence CASCADE;
TRUNCATE TABLE semantic_event CASCADE;
TRUNCATE TABLE event_jobs CASCADE;
TRUNCATE TABLE artifact_revision CASCADE;

-- Verify
SELECT 'PostgreSQL flushed. Row counts:' AS status;
SELECT 'artifact_revision' AS table_name, COUNT(*) AS rows FROM artifact_revision
UNION ALL SELECT 'event_jobs', COUNT(*) FROM event_jobs
UNION ALL SELECT 'semantic_event', COUNT(*) FROM semantic_event
UNION ALL SELECT 'event_evidence', COUNT(*) FROM event_evidence;
EOF

# 2. Flush ChromaDB collections
echo ""
echo "[2/2] Flushing ChromaDB collections..."
docker compose -f "$COMPOSE_FILE" exec -T mcp-server python << 'EOF'
import chromadb
import os

host = os.environ.get("CHROMA_HOST", "chroma")
port = int(os.environ.get("CHROMA_PORT", 8000))

client = chromadb.HttpClient(host=host, port=port)

collections = ["memories", "artifacts", "artifact_chunks", "history"]
for name in collections:
    try:
        client.delete_collection(name)
        print(f"  Deleted collection: {name}")
    except Exception as e:
        print(f"  Collection {name} not found (OK)")

print("\nChromaDB flushed.")
EOF

echo ""
echo "==================================="
echo "Data flush complete!"
echo "==================================="
echo ""
echo "The system is ready for fresh data."
echo "All tables and collections are empty."
