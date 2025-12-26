#!/bin/bash
# Real-World Integration Verification Script
# This script MUST pass before UAT presentation
# DO NOT use mocks - this tests REAL services

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS_COUNT=0
FAIL_COUNT=0
RESULTS=""

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASS_COUNT=$((PASS_COUNT + 1))
    RESULTS+="[PASS] $1\n"
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    RESULTS+="[FAIL] $1\n"
}

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

echo "========================================"
echo "Real-World Integration Verification"
echo "========================================"
echo ""

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env if exists
if [ -f "$PROJECT_ROOT/implementation/mcp-server/.env" ]; then
    export $(grep -v '^#' "$PROJECT_ROOT/implementation/mcp-server/.env" | xargs)
fi

MCP_PORT=${MCP_PORT:-3000}
CHROMA_PORT=${CHROMA_PORT:-8001}

log_info "MCP Server expected on port: $MCP_PORT"
log_info "ChromaDB expected on port: $CHROMA_PORT"
echo ""

# ============================================
# CHECK 1: MCP Server Health
# ============================================
echo "--- Check 1: MCP Server Health ---"
HEALTH_RESPONSE=$(curl -s "http://localhost:$MCP_PORT/health" 2>&1 || echo "FAILED")
if echo "$HEALTH_RESPONSE" | grep -q '"status"'; then
    log_pass "MCP Server health endpoint responding"
    echo "  Response: $HEALTH_RESPONSE"
else
    log_fail "MCP Server not responding on port $MCP_PORT"
    echo "  Response: $HEALTH_RESPONSE"
fi
echo ""

# ============================================
# CHECK 2: ChromaDB Health
# ============================================
echo "--- Check 2: ChromaDB Health ---"
CHROMA_RESPONSE=$(curl -s "http://localhost:$CHROMA_PORT/api/v2/heartbeat" 2>&1 || echo "FAILED")
if echo "$CHROMA_RESPONSE" | grep -q "heartbeat"; then
    log_pass "ChromaDB heartbeat responding"
else
    log_fail "ChromaDB not responding on port $CHROMA_PORT"
    echo "  Response: $CHROMA_RESPONSE"
fi
echo ""

# ============================================
# CHECK 3: Port Consistency
# ============================================
echo "--- Check 3: Port Consistency ---"
ENV_FILE="$PROJECT_ROOT/implementation/mcp-server/.env"
COMPOSE_FILE="$PROJECT_ROOT/implementation/mcp-server/docker-compose.yml"

if [ -f "$ENV_FILE" ]; then
    ENV_PORT=$(grep "CHROMA_PORT" "$ENV_FILE" | cut -d'=' -f2)
    log_info ".env CHROMA_PORT=$ENV_PORT"

    # Check if ChromaDB is accessible on configured port
    if curl -s "http://localhost:$ENV_PORT/api/v2/heartbeat" 2>/dev/null | grep -q "heartbeat"; then
        log_pass "Port configuration consistent (.env port $ENV_PORT is accessible)"
    else
        log_fail "Port mismatch: .env says $ENV_PORT but ChromaDB not accessible there"
    fi

    # Also check container if running
    CONTAINER_PORT=$(docker ps --format '{{.Ports}}' 2>/dev/null | grep chroma | grep -o "0.0.0.0:[0-9]*" | head -1 | cut -d':' -f2 || echo "")
    if [ -n "$CONTAINER_PORT" ]; then
        log_info "Docker container exposing ChromaDB on port: $CONTAINER_PORT"
        if [ "$ENV_PORT" != "$CONTAINER_PORT" ]; then
            log_fail "WARNING: .env port ($ENV_PORT) differs from container port ($CONTAINER_PORT)"
        fi
    else
        log_info "No Docker container found, checking direct connection"
        if curl -s "http://localhost:$ENV_PORT/api/v2/heartbeat" | grep -q "heartbeat"; then
            log_pass "ChromaDB accessible on configured port $ENV_PORT"
        else
            log_fail "ChromaDB NOT accessible on configured port $ENV_PORT"
        fi
    fi
else
    log_fail ".env file not found at $ENV_FILE"
fi
echo ""

# ============================================
# CHECK 4: MCP Protocol Test
# ============================================
echo "--- Check 4: MCP Protocol Test ---"
MCP_INIT=$(curl -s -X POST "http://localhost:$MCP_PORT/mcp/" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    --data '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"verify-script","version":"1.0"},"capabilities":{}}}' 2>&1 || echo "FAILED")

if echo "$MCP_INIT" | grep -q "protocolVersion"; then
    log_pass "MCP protocol initialization works"
    # Extract server name
    SERVER_NAME=$(echo "$MCP_INIT" | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
    log_info "Server: $SERVER_NAME"
else
    log_fail "MCP protocol initialization failed"
    echo "  Response: $MCP_INIT"
fi
echo ""

# ============================================
# CHECK 5: OpenAI API Test (if configured)
# ============================================
echo "--- Check 5: OpenAI API Test ---"
if echo "$HEALTH_RESPONSE" | grep -q '"openai"'; then
    OPENAI_STATUS=$(echo "$HEALTH_RESPONSE" | grep -o '"openai":{[^}]*}' | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    if [ "$OPENAI_STATUS" = "healthy" ]; then
        log_pass "OpenAI API connection healthy"
    else
        log_fail "OpenAI API unhealthy: $OPENAI_STATUS"
    fi
else
    log_info "OpenAI status not in health response (may need detailed endpoint)"
fi
echo ""

# ============================================
# CHECK 6: Client Config (Cursor)
# ============================================
echo "--- Check 6: Cursor MCP Config ---"
CURSOR_CONFIG="$HOME/.cursor/mcp.json"
if [ -f "$CURSOR_CONFIG" ]; then
    if grep -q "localhost:$MCP_PORT/mcp" "$CURSOR_CONFIG"; then
        log_pass "Cursor config has correct MCP URL"
    else
        log_fail "Cursor config missing or wrong MCP URL"
        echo "  Expected: localhost:$MCP_PORT/mcp/"
        echo "  Found: $(grep -o '"url":"[^"]*"' "$CURSOR_CONFIG" | head -3)"
    fi
else
    log_info "Cursor config not found (may not be using Cursor)"
fi
echo ""

# ============================================
# CHECK 7: Client Config (Claude Desktop)
# ============================================
echo "--- Check 7: Claude Desktop Config ---"
CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
if [ -f "$CLAUDE_CONFIG" ]; then
    if grep -q "localhost:$MCP_PORT/mcp" "$CLAUDE_CONFIG"; then
        log_pass "Claude Desktop config has correct MCP URL"
    else
        log_fail "Claude Desktop config missing or wrong MCP URL"
    fi
else
    log_info "Claude Desktop config not found"
fi
echo ""

# ============================================
# SUMMARY
# ============================================
echo "========================================"
echo "VERIFICATION SUMMARY"
echo "========================================"
echo -e "Passed: ${GREEN}$PASS_COUNT${NC}"
echo -e "Failed: ${RED}$FAIL_COUNT${NC}"
echo ""

# Save results
RESULTS_FILE="$PROJECT_ROOT/tests/integration/real_service_results.md"
mkdir -p "$(dirname "$RESULTS_FILE")"
cat > "$RESULTS_FILE" << EOF
# Real-World Integration Test Results

**Date**: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
**Passed**: $PASS_COUNT
**Failed**: $FAIL_COUNT

## Results

$(echo -e "$RESULTS")

## Configuration Tested

- MCP Port: $MCP_PORT
- ChromaDB Port: $CHROMA_PORT

## Verdict

$(if [ $FAIL_COUNT -eq 0 ]; then echo "**PASS** - Ready for UAT"; else echo "**FAIL** - Fix issues before UAT"; fi)
EOF

echo "Results saved to: $RESULTS_FILE"
echo ""

if [ $FAIL_COUNT -gt 0 ]; then
    echo -e "${RED}VERIFICATION FAILED${NC}"
    echo "Fix the above issues before proceeding to UAT."
    exit 1
else
    echo -e "${GREEN}VERIFICATION PASSED${NC}"
    echo "Ready for UAT presentation."
    exit 0
fi
