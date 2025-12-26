# Mandatory Testing Requirements

## Problem Statement

Unit tests with mocks pass but real-world integration fails. This document defines **mandatory real-world testing** that must pass before UAT.

## The User Simulation Tests (REQUIRED)

### Test 1: HTTP Client Simulation
**Location**: `.claude-workspace/tests/e2e/full_user_simulation.py`

This script simulates exactly what a real user would do:
1. Connects to MCP server (like Cursor/Claude Desktop)
2. Calls EVERY tool with real data
3. Verifies data persists and retrieves correctly
4. Tests complete user workflows

**Run Before Every UAT**:
```bash
python3 .claude-workspace/tests/e2e/full_user_simulation.py
```

**Must show**: `ALL TESTS PASSED - Ready for user`

### Test 2: Browser UI Automation (MCP Inspector)
**Location**: `.claude-workspace/tests/e2e/browser_mcp_test.js`

This script automates the MCP Inspector browser UI to validate the visual user experience:
1. Launches MCP Inspector at localhost:6274
2. Configures Streamable HTTP transport
3. Connects to server and verifies connection status
4. Navigates to Tools tab and lists all tools
5. Selects and executes a tool (memory_store)
6. Verifies successful response
7. Takes screenshots as evidence

**Prerequisites**:
```bash
# Install Playwright (one-time setup)
cd .claude-workspace/tests/e2e
npm install playwright
npx playwright install chromium

# Start MCP Inspector
npx @modelcontextprotocol/inspector node /path/to/server.js
```

**Run Before Every UAT**:
```bash
cd .claude-workspace/tests/e2e
MCP_AUTH_TOKEN="<token_from_inspector>" node browser_mcp_test.js
```

**Must show**: `Passed: 11` and `Failed: 0`

**Screenshots saved to**: `.claude-workspace/tests/e2e/screenshots/`

### Failure Policy
**If ANY test fails**: Fix the bug. Do NOT present to user.

---

## Rule 1: No UAT Without Real Service Tests

Before presenting to user, the following MUST be verified against **running services** (not mocks):

### Infrastructure Verification
```bash
# These commands MUST succeed before UAT
curl http://localhost:3000/health    # MCP Server
curl http://localhost:8001/api/v2/heartbeat  # ChromaDB (actual port)
```

### Configuration Validation
- [ ] `.env` ports match actual running services
- [ ] API keys are valid (test with real API call)
- [ ] All environment variables are set correctly

---

## Rule 2: Real MCP Client Test

Before UAT, test with an actual MCP client (not curl):

```bash
# Must verify ALL tools are exposed
curl -s -X POST http://localhost:3000/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","method":"tools/list","id":1}' | grep -c '"name"'
# Expected: 12 tools for v2
```

### Tool Count Verification
| Version | Expected Tools |
|---------|----------------|
| v1 | 6 tools |
| v2 | 12 tools |

If tool count doesn't match, **FAIL the review**.

---

## Rule 3: End-to-End Tool Execution

At least ONE tool from each category must be called with real services:

### Memory Tools
```python
# Actually call memory_store and verify in ChromaDB
memory_store("Test memory", "fact", 0.9)
# Verify: Check ChromaDB collection has the record
```

### Artifact Tools (v2)
```python
# Actually call artifact_ingest and verify chunking works
artifact_ingest("doc", "test", "Long content...", title="Test")
# Verify: Check artifacts and artifact_chunks collections
```

### Search Tools
```python
# Actually call hybrid_search and verify results
hybrid_search("test query")
# Verify: Results returned with RRF scores
```

---

## Rule 4: Client Configuration Test

Before UAT, verify the client config works:

### For Claude Desktop
```bash
# Check config exists and has correct URL
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json | grep "localhost:3000/mcp"
```

### For Cursor
```bash
# Check config exists and has correct URL
cat ~/.cursor/mcp.json | grep "localhost:3000/mcp"
```

---

## Rule 5: Port Consistency Check

**CRITICAL**: Verify all port references are consistent:

```bash
# All these must show the SAME ports
grep -r "CHROMA_PORT" .env
grep -r "8001\|8000" docker-compose.yml
docker ps --format '{{.Ports}}' | grep chroma
```

If ports don't match, **FAIL the review**.

---

## Pre-UAT Checklist (Mandatory)

The Chief of Staff MUST verify ALL items before presenting to user:

### Infrastructure
- [ ] Server health endpoint returns 200
- [ ] ChromaDB heartbeat returns 200
- [ ] OpenAI API test embedding succeeds
- [ ] Port configuration is consistent across all files
- [ ] Server logs show no errors on startup

### Automated Tests (BLOCKING)
- [ ] HTTP Client Simulation: `python3 .claude-workspace/tests/e2e/full_user_simulation.py` → "ALL TESTS PASSED"
- [ ] Browser UI Automation: `node browser_mcp_test.js` → "Passed: 11, Failed: 0"
- [ ] All expected tools are listed (12 for v2)
- [ ] At least one tool from each category executes successfully

### Client Configuration
- [ ] Cursor config (`~/.cursor/mcp.json`) has correct URL: `http://localhost:3000/mcp/`
- [ ] Claude Desktop config has correct URL (if applicable)

**If ANY item fails, do NOT proceed to UAT.**

---

## Test Script Location

A real E2E test script MUST exist at:
`.claude-workspace/tests/e2e/real_service_test.py`

This script:
1. Connects to actual running services
2. Executes real tool calls
3. Verifies data in ChromaDB
4. Reports pass/fail for each check

---

## Failure Examples to Prevent

| Issue | How We Catch It |
|-------|-----------------|
| Wrong ChromaDB port | Port consistency check |
| Mocked tests pass, real fails | Mandatory real service tests |
| Tools not loading in client | Client config verification |
| API key invalid | Real embedding test |
| Missing tools | Tool count verification |
