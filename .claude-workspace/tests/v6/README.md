# V6 Test Suite

## Test Summary

| Category | Tests | Description |
|----------|-------|-------------|
| **Unit** | 19 | Collection helpers (ChromaDB storage) |
| **Integration** | 61 | remember/recall/forget/status tools |
| **E2E** | 11 | Full pipeline against live server |
| **Total** | **91** | |

## Running Tests

Tests must be run from the venv with dependencies installed:

```bash
# Navigate to MCP server directory
cd .claude-workspace/implementation/mcp-server

# Activate venv
source .venv/bin/activate

# Navigate to tests
cd ../../tests/v6

# Run unit + integration tests (no server required)
pytest unit/ integration/ -v

# Run E2E tests (requires running server)
pytest e2e/ --run-e2e -v

# Run all tests
pytest . --run-e2e -v
```

## Test Categories

### Unit Tests (`unit/`)
- `test_v5_collections.py` - Tests for ChromaDB collection helpers
- Uses mocked ChromaDB client
- No external dependencies required

### Integration Tests (`integration/`)
- `test_v5_remember.py` - Content storage, deduplication, chunking
- `test_v5_recall.py` - Semantic search, ID lookup, graph expansion
- `test_v5_forget.py` - Cascade deletion, safety flags
- `test_v5_status.py` - Health checks, collection counts
- Uses mocked services (no real server needed)

### E2E Tests (`e2e/`)
- `test_v5_e2e.py` - Full pipeline tests against live server
- Requires MCP server running at `http://localhost:3001/mcp/`
- Uses `lib/mcp_client.py` adapter (wraps official MCP SDK)

## E2E Test Requirements

1. Start the MCP server:
   ```bash
   cd .claude-workspace/deployment
   ./scripts/env-up.sh prod
   ```

2. Run E2E tests with `--run-e2e` flag:
   ```bash
   pytest e2e/ --run-e2e -v
   ```

## MCP Client Adapter

The `lib/mcp_client.py` module provides a synchronous wrapper around the official MCP Python SDK for E2E testing. It connects via HTTP to the MCP Memory Server.

```python
from mcp_client import MCPClient, MCPResponse

client = MCPClient()
client.initialize()

response = client.call_tool("status", {})
if response.success:
    print(response.data)

client.close()
```
