#!/bin/bash
# Quick test script for Chroma MCP Memory V1

set -e

echo "=== Chroma MCP Memory V1 Test ==="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Step 1: Start services
echo -e "${YELLOW}[1/5] Starting Docker services...${NC}"
docker compose up -d

# Wait for ChromaDB to be healthy
echo -e "${YELLOW}[2/5] Waiting for ChromaDB to be healthy...${NC}"
for i in {1..30}; do
    if docker compose exec -T chroma wget -qO- http://localhost:8000/api/v1/heartbeat 2>/dev/null | grep -q "nanosecond"; then
        echo -e "${GREEN}ChromaDB is ready!${NC}"
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 2
done

# Step 3: Test ChromaDB directly
echo ""
echo -e "${YELLOW}[3/5] Testing ChromaDB API...${NC}"

# Create test collection
echo "  Creating test collection..."
RESULT=$(curl -s -X POST http://localhost:8000/api/v1/collections \
    -H "Content-Type: application/json" \
    -d '{"name": "test_collection", "metadata": {"test": true}}')
echo "  Result: $RESULT"

# List collections
echo "  Listing collections..."
COLLECTIONS=$(curl -s http://localhost:8000/api/v1/collections)
echo "  Collections: $COLLECTIONS"

# Step 4: Test the agent-app
echo ""
echo -e "${YELLOW}[4/5] Testing agent-app...${NC}"
docker compose logs agent-app --tail=20

# Step 5: Cleanup test collection
echo ""
echo -e "${YELLOW}[5/5] Cleanup...${NC}"
curl -s -X DELETE http://localhost:8000/api/v1/collections/test_collection
echo "  Test collection deleted"

echo ""
echo -e "${GREEN}=== Test Complete ===${NC}"
echo ""
echo "Services running:"
docker compose ps
echo ""
echo "To view logs:  docker compose logs -f"
echo "To stop:       docker compose down"
echo "To stop+clean: docker compose down -v"
