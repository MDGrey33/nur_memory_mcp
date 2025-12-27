# E2E Test Cases: MCP Memory Server v3.0

## CRITICAL: Pre-UAT Testing Requirement

> **The user should NEVER be the first to test MCP tools in the browser.**
>
> Before presenting ANY work for User Acceptance Testing (UAT), you MUST:
>
> 1. Run the API E2E test: `python .claude-workspace/tests/e2e/full_user_simulation.py`
> 2. Run the browser test: `python .claude-workspace/tests/ui/playwright_mcp_inspector.py --headed`
> 3. Verify ALL 17 tools are listed in MCP Inspector
> 4. Execute at least `embedding_health` tool and verify response
> 5. Take screenshots as evidence
>
> **DO NOT proceed to UAT if any test fails.**

## Overview

The MCP Memory Server is a backend service that exposes tools via HTTP/SSE (Streamable HTTP transport).
Testing involves HTTP endpoint verification and MCP tool invocation.

### Available Tools (17 total)

**Core Tools (12):**
- `memory_store`, `memory_search`, `memory_list`, `memory_delete`
- `history_append`, `history_get`
- `artifact_ingest`, `artifact_search`, `artifact_get`, `artifact_delete`
- `hybrid_search`, `embedding_health`

**V3 Event Tools (5):**
- `event_search_tool`, `event_get_tool`, `event_list_for_artifact`
- `event_reextract`, `job_status`

---

## Test Case 1: Health Endpoint
**Priority**: High
**Type**: HTTP GET
**Endpoint**: `GET /health`
**Steps**:
1. Send GET request to http://localhost:3000/health
**Expected**:
- Status 200
- JSON response with `{"status": "ok", "service": "mcp-memory"}`

---

## Test Case 2: ChromaDB Connectivity
**Priority**: High
**Type**: HTTP GET
**Endpoint**: ChromaDB `GET /api/v2/heartbeat`
**Steps**:
1. Send GET request to http://localhost:8001/api/v2/heartbeat
**Expected**:
- Status 200
- JSON response with heartbeat timestamp

---

## Test Case 3: MCP Endpoint Availability
**Priority**: High
**Type**: HTTP OPTIONS/POST
**Endpoint**: `POST /mcp/`
**Steps**:
1. Send POST request to http://localhost:3000/mcp/
2. Include proper MCP protocol headers
**Expected**:
- Valid MCP response or connection upgrade

---

## Test Case 4: Memory Store Tool
**Priority**: High
**Type**: MCP Tool Call
**Tool**: `memory_store`
**Steps**:
1. Call memory_store with test content
2. Verify success response
3. Verify memory ID returned
**Expected**:
- Success message with memory ID (mem_XXXX format)

---

## Test Case 5: Memory Search Tool
**Priority**: High
**Type**: MCP Tool Call
**Tool**: `memory_search`
**Steps**:
1. Store a test memory
2. Search for related content
3. Verify result contains stored memory
**Expected**:
- Search results include the stored memory
- Results ranked by relevance

---

## Test Case 6: Artifact Ingest (Small)
**Priority**: High
**Type**: MCP Tool Call
**Tool**: `artifact_ingest`
**Steps**:
1. Ingest small content (<1200 tokens)
2. Verify artifact_id returned
3. Verify is_chunked=false
**Expected**:
- artifact_id in art_XXXX format
- is_chunked: false
- num_chunks: 0

---

## Test Case 7: Artifact Ingest (Large with Chunking)
**Priority**: High
**Type**: MCP Tool Call
**Tool**: `artifact_ingest`
**Steps**:
1. Ingest large content (>1200 tokens)
2. Verify artifact_id returned
3. Verify is_chunked=true
4. Verify num_chunks > 0
**Expected**:
- artifact_id in art_XXXX format
- is_chunked: true
- num_chunks matches expected chunk count

---

## Test Case 8: Hybrid Search
**Priority**: High
**Type**: MCP Tool Call
**Tool**: `hybrid_search`
**Steps**:
1. Store memories and ingest artifacts
2. Call hybrid_search with relevant query
3. Verify RRF-merged results
**Expected**:
- Results from multiple collections
- RRF scores present
- Results ranked by relevance

---

## Test Case 9: Embedding Health
**Priority**: Medium
**Type**: MCP Tool Call
**Tool**: `embedding_health`
**Steps**:
1. Call embedding_health tool
2. Verify OpenAI API connectivity
**Expected**:
- provider: "openai"
- model: "text-embedding-3-large"
- dimensions: 3072
- api_status: "healthy"

---

## Test Case 10: Artifact Delete Cascade
**Priority**: Medium
**Type**: MCP Tool Call
**Tool**: `artifact_delete`
**Steps**:
1. Ingest large artifact (creates chunks)
2. Delete artifact
3. Verify artifact and all chunks removed
**Expected**:
- Success message with chunk count
- No orphan chunks remaining

---

## Test Case 11: Idempotent Re-ingestion
**Priority**: Medium
**Type**: MCP Tool Call
**Tool**: `artifact_ingest`
**Steps**:
1. Ingest artifact with source_id
2. Re-ingest same content with same source_id
3. Verify no duplicate created
**Expected**:
- Same artifact_id returned
- status: "unchanged"

---

## Test Case 12: Error Handling - Invalid Input
**Priority**: Medium
**Type**: MCP Tool Call
**Tool**: Various
**Steps**:
1. Call tools with invalid parameters
2. Verify proper error responses
**Expected**:
- Descriptive error messages
- No server crashes
- Proper HTTP status codes
