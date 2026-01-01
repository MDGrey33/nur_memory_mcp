# Mandatory Testing Requirements (V6.2)

## Problem Statement

Unit tests with mocks pass but real-world integration fails. This document defines **mandatory real-world testing** that must pass before UAT.

## V6 Tools (4 total)

| Tool | Description |
|------|-------------|
| `remember` | Store content with automatic chunking and event extraction |
| `recall` | Search/retrieve with semantic search and graph expansion |
| `forget` | Delete with cascade (chunks, events, entities) |
| `status` | Health check and job status |

## Port Configuration

| Environment | Port | Compose File |
|-------------|------|--------------|
| Default/Prod | 3000 | `docker-compose.yml` |
| Local Dev | 3001 | `docker-compose.local.yml` |
| Test | 3201 | `docker-compose.test.yml` |

---

## The User Simulation Tests (REQUIRED)

### Test: MCP Flow Test
**Location**: `.claude-workspace/implementation/mcp-server/test_mcp_flow.py`

This script simulates exactly what a real user would do:
1. Connects to MCP server
2. Calls ALL V6 tools (remember, recall, forget, status)
3. Verifies data persists and retrieves correctly

**Run Before Every UAT**:
```bash
cd .claude-workspace/implementation/mcp-server
MCP_URL="http://localhost:3001/mcp/" python test_mcp_flow.py
```

**Must show**: `ALL TESTS PASSED - MCP Server v6.2 is working!`

### Failure Policy
**If ANY test fails**: Fix the bug. Do NOT present to user.

---

## Rule 1: No UAT Without Real Service Tests

Before presenting to user, the following MUST be verified against **running services** (not mocks):

### Infrastructure Verification
```bash
# These commands MUST succeed before UAT
curl http://localhost:3001/health    # MCP Server
curl http://localhost:8001/api/v2/heartbeat  # ChromaDB
```

### Configuration Validation
- [ ] `.env` ports match actual running services
- [ ] API keys are valid (test with real API call)
- [ ] All environment variables are set correctly

---

## Rule 2: Real MCP Client Test

Before UAT, test with an actual MCP client:

```bash
# Must verify ALL 4 V6 tools are exposed
curl -s -X POST http://localhost:3001/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","method":"tools/list","id":1}' | grep -c '"name"'
# Expected: 4 tools for V6
```

### Tool Count Verification
| Version | Expected Tools |
|---------|----------------|
| V6.2 | 4 tools (remember, recall, forget, status) |

If tool count doesn't match, **FAIL the review**.

---

## Rule 3: End-to-End Tool Execution

All V6 tools must be tested with real services:

### Store with remember
```python
remember(content="Test memory", context="fact", importance=0.9)
# Verify: Check ChromaDB content collection has the record
```

### Search with recall
```python
recall(query="test query", limit=5)
# Verify: Results returned with semantic matches
```

### Check with status
```python
status()
# Verify: Health info and counts returned
```

### Delete with forget
```python
forget(id="art_xxx", confirm=True)
# Verify: Artifact and related data deleted
```

---

## Rule 4: Client Configuration Test

Before UAT, verify the client config works:

### For Claude Code
```bash
# Check .mcp.json has correct URL
cat .mcp.json | grep "localhost:3001/mcp"
```

### For Claude Desktop
```bash
# Check config exists and has correct URL
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json | grep "localhost:3001/mcp"
```

---

## Rule 5: Port Consistency Check

**CRITICAL**: Verify all port references are consistent:

```bash
# All these must show the SAME ports
grep -r "MCP_PORT\|MCP_EXTERNAL_PORT" .claude-workspace/deployment/.env*
docker ps --format '{{.Ports}}' | grep -E "300[01]|8001"
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
- [ ] MCP Flow Test: `python test_mcp_flow.py` → "ALL TESTS PASSED"
- [ ] All 4 V6 tools are listed (remember, recall, forget, status)
- [ ] Each tool executes successfully

### Client Configuration
- [ ] Config has correct URL: `http://localhost:3001/mcp/`

**If ANY item fails, do NOT proceed to UAT.**

---

## Test Script Location

V6 E2E test scripts:
- `.claude-workspace/implementation/mcp-server/test_mcp_flow.py` - Full MCP flow
- `.claude-workspace/tests/v6/e2e/` - Pytest E2E suite

---

## Failure Examples to Prevent

| Issue | How We Catch It |
|-------|-----------------|
| Wrong port (3100 vs 3001) | Port consistency check |
| Mocked tests pass, real fails | Mandatory real service tests |
| Tools not loading in client | Client config verification |
| API key invalid | Real embedding test |
| Missing tools | Tool count verification (expect 4) |
