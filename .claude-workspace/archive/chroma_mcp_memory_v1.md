# Chroma MCP Memory V1 (Docker-First) – Build Notes

This document is a **handoff spec** for implementing **V1** of an LLM memory system using:
- **Chroma DB** for persistence (via Docker volume)
- **chroma-mcp** as the MCP gateway to Chroma
- **agent-app** (your LLM/agent) implementing memory policy + context assembly

V1 scope is intentionally small: **store history**, **store a few deliberate memories**, **retrieve both reliably**.

---

## 1) What V1 Allows (Executive Summary)

V1 enables an LLM to:

1. **Persist conversation history**
   - Store every user/assistant message turn into a `history` collection.
   - Retrieve the last *N* turns for a `conversation_id` to rebuild context.

2. **Create and recall long-term memory**
   - Store “worth remembering” items into a `memory` collection.
   - Retrieve relevant memories using **semantic search** (vector similarity), optionally filtered by metadata (e.g., confidence).

3. **Work across sessions and container restarts**
   - All persistence lives inside Docker volumes attached to the **Chroma** container.

---

## 2) V1 Architecture

### 2.1 Services

- **chroma** (DB)
  - Stores collections and vectors
  - Has a mounted Docker volume (persistence)

- **chroma-mcp** (gateway)
  - Exposes MCP tools for collections + documents + query
  - Stateless (no volume required)
  - Connects to chroma via HTTP

- **agent-app** (your code)
  - Calls MCP tools
  - Implements:
    - history append
    - memory write policy
    - context builder (history tail + memory recall)

### 2.2 Diagram

```
Agent / LLM App (MCP Client)
   |  MCP tool calls
   v
chroma-mcp (stateless)
   |  HTTP
   v
chroma (persistent volume)
```

---

## 3) Docker Compose Skeleton (V1)

> Adjust images/tags to what you standardize on internally.

```yaml
services:
  chroma:
    image: chromadb/chroma:latest
    container_name: chroma
    ports:
      - "8000:8000"   # optional: expose externally only if needed
    volumes:
      - chroma_data:/chroma/chroma
    environment:
      - IS_PERSISTENT=TRUE
      - ANONYMIZED_TELEMETRY=FALSE
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8000/api/v1/heartbeat"]
      interval: 10s
      timeout: 5s
      retries: 10

  chroma-mcp:
    # use the official chroma-mcp image if you publish it internally
    # otherwise build from the chroma-core/chroma-mcp repo Dockerfile
    image: ghcr.io/chroma-core/chroma-mcp:latest
    container_name: chroma-mcp
    depends_on:
      chroma:
        condition: service_healthy
    environment:
      - CHROMA_CLIENT_TYPE=http
      - CHROMA_HTTP_HOST=chroma
      - CHROMA_HTTP_PORT=8000
    # MCP can be stdio-driven or run as a service depending on your MCP client integration.
    # If you run it over HTTP for your agent, expose a port here.

  agent-app:
    build: ./agent-app
    container_name: agent-app
    depends_on:
      chroma-mcp:
        condition: service_started
    environment:
      - MCP_ENDPOINT=chroma-mcp   # or full URL if applicable
      - MEMORY_CONFIDENCE_MIN=0.7
      - HISTORY_TAIL_N=16
      - MEMORY_TOP_K=8
    # ports: expose only if you have an API/UI

volumes:
  chroma_data:
```

**Persistence rule:** Only `chroma_data` matters for V1.

---

## 4) Collections and Schema (V1)

V1 uses **two collections** only:

### 4.1 Collection: `history`
Stores every turn of the conversation.

**Document text**
- The raw message text (as-is)

**Metadata (minimum)**
- `conversation_id` (string)
- `role` (string: `user|assistant|system`)
- `ts` (string: ISO-8601)
- `turn_index` (int)

**Recommended additions (optional)**
- `message_id` (string, unique)
- `channel` (string: web/app/slack/etc.)

---

### 4.2 Collection: `memory`
Stores “deliberate” memories only (not every message).

**Document text**
- The memory statement or summary text

**Metadata (minimum)**
- `type` (string: `preference|fact|project|decision`)
- `confidence` (float: 0.0–1.0)
- `ts` (string: ISO-8601)
- `conversation_id` (string, optional)

**Recommended additions (optional)**
- `entities` (string list or comma-separated string)
- `source` (`chat|tool|import`)
- `tags` (string list)

---

## 5) MCP Operations Used in V1

V1 only needs a small subset of capabilities from chroma-mcp:

### 5.1 Startup / Bootstrap (one-time)
- Ensure collections exist:
  - `history`
  - `memory`

### 5.2 On every message
- Add document to `history`

### 5.3 On “remember-worthy” events
- Add document to `memory`

### 5.4 Before responding
- Retrieve last N turns from `history` (filter by `conversation_id`)
- Query `memory` using semantic search, optionally filtered by `confidence >= threshold`

> V1 does **not** require update/delete/decay/re-embedding.

---

## 6) Core Flows (V1)

### 6.1 Append History (always)
**Trigger:** every user and assistant message

Pseudo:
1. `add_document(collection="history", text=message_text, metadata={conversation_id, role, ts, turn_index})`

### 6.2 Write Memory (sometimes)
**Trigger:** assistant decides a memory is worth storing

V1 policy suggestion:
- store only if `confidence >= MEMORY_CONFIDENCE_MIN`
- store max **1–3** memories per “topic chunk” / short window

Pseudo:
1. if confidence >= threshold:
   - `add_document(collection="memory", text=memory_text, metadata={type, confidence, ts, conversation_id})`

### 6.3 Build Context (always)
**Trigger:** before generating the assistant reply

Pseudo:
1. `history_tail = get_last_n("history", conversation_id, n=HISTORY_TAIL_N)`
2. `memory_hits = semantic_query("memory", query=latest_user_text, k=MEMORY_TOP_K, filter={"confidence": {">=": threshold}})`
3. Construct prompt/context:
   - chronological history tail
   - top memory hits (short formatted bullet list)
   - latest user message

---

## 7) Minimal Code Layout (agent-app)

Keep it tiny. One boundary to MCP. One context builder.

```
agent-app/
  src/
    memory_gateway.py        # all MCP calls live here
    context_builder.py       # uses gateway to fetch history+memory and pack context
    memory_policy.py         # (small) should_store_memory(confidence, type)
    app.py                   # your agent entrypoint
```

### 7.1 `memory_gateway.py` responsibilities
- connect to MCP endpoint
- implement:
  - `append_history(conversation_id, role, text, turn_index, ts)`
  - `write_memory(text, type, confidence, ts, conversation_id=None)`
  - `tail_history(conversation_id, n)`
  - `recall_memory(query_text, k, min_confidence, conversation_id=None)`

No business policy inside. Just transport + mapping.

### 7.2 `context_builder.py` responsibilities
- `build_context(conversation_id, latest_user_text)`:
  - fetch history tail
  - recall memory
  - format + truncate to token budget

---

## 8) Example Payload Shapes

### 8.1 History insert (logical)
```json
{
  "collection": "history",
  "documents": ["User: I want to store memories in Docker…"],
  "metadatas": [{
    "conversation_id": "conv_123",
    "role": "user",
    "ts": "2025-12-25T12:10:00+02:00",
    "turn_index": 42
  }]
}
```

### 8.2 Memory insert (logical)
```json
{
  "collection": "memory",
  "documents": ["User prefers a Docker-contained memory stack using Chroma + MCP."],
  "metadatas": [{
    "type": "preference",
    "confidence": 0.85,
    "ts": "2025-12-25T12:11:00+02:00",
    "conversation_id": "conv_123"
  }]
}
```

### 8.3 Memory query (logical)
```json
{
  "collection": "memory",
  "query_text": "How should we store memory in Docker with Chroma MCP?",
  "limit": 8,
  "where": {
    "confidence": { "$gte": 0.7 }
  }
}
```

---

## 9) V1 Acceptance Criteria

V1 is complete when:

- [ ] `docker compose up` starts chroma + chroma-mcp + agent-app cleanly
- [ ] After restart, previously stored memories are still retrievable (volume works)
- [ ] Each message is appended to `history`
- [ ] Agent can retrieve last N turns for a conversation_id
- [ ] Agent can store a memory into `memory`
- [ ] Agent can semantically query `memory` and get relevant items back
- [ ] Memory write is gated by `MEMORY_CONFIDENCE_MIN`
- [ ] No runaway memory spam (basic rate limit in policy: max 1–3 per chunk)

---

## 10) Explicit Non-Goals for V1 (Defer to V2)

- Multiple memory collections (episodic/semantic/procedural/narrative)
- Promotion pipeline from history → memory
- Dedupe / similarity merging
- Decay / archival / TTL enforcement
- Re-embedding / embedding version migrations
- Full audit trail, metrics, dashboards
- Multi-tenancy routing (tenant prefixes)
- Access control / auth between services (unless required by your environment)

---

## 11) Practical Notes (keep it smooth)

- **Chunk sizes**: keep stored docs reasonably sized (e.g., 200–800 tokens). Summarize if huge.
- **IDs**: optionally provide your own `message_id` / `memory_id` so you can reconcile across systems.
- **Don’t expose ports** unless needed: prefer internal Docker network communication.
- **Keep config in env vars** for easy deployment.

---

## 12) V2 Direction (for later)

When V1 is stable, V2 usually adds:
- split `memory` into multiple collections by memory-type
- `history_summaries` collection + periodic summarization
- promotion tool: “promote summary → memory”
- decay job + dedupe job

---

## Appendix A: Suggested Environment Variables

- `MCP_ENDPOINT` (or MCP stdio config)
- `MEMORY_CONFIDENCE_MIN=0.7`
- `HISTORY_TAIL_N=16`
- `MEMORY_TOP_K=8`
- `MEMORY_MAX_PER_WINDOW=3` (optional)
- `CONTEXT_TOKEN_BUDGET` (optional)

---

End of spec.


---

## Appendix B: “Full Architecture” Notes (Composable + SOLID, still lightweight)

This appendix captures the **extra architectural details we discussed beyond the minimal V1**, so you can keep V1 simple while preserving a clean path to expansion.

### B.1 Key design intent
- Keep `chroma-mcp` as a **stateless gateway** (no business rules there).
- Keep “what to store, where to store, and how to assemble context” inside **agent-app**.
- Make it easy to:
  - add more collections (episodic/semantic/procedural/narrative)
  - add summarization + promotion
  - add retention/decay jobs
  - swap storage backend later if needed

### B.2 Minimal SOLID structure inside agent-app
Instead of adding many abstractions, use **three small ports** and a single adapter:

**Ports (interfaces)**
- `VectorStore`
  - `add(collection, docs, metadatas)`
  - `query(collection, query_text, where, limit)`
  - `get(collection, where=None, limit=None, sort=None)`
  - `delete(collection, ids)`
  - `list_collections()`

- `HistoryStore`
  - `append_turn(conversation_id, role, text, ts, turn_index)`
  - `tail(conversation_id, n)`
  - (V2) `write_summary(conversation_id, summary, ts)`

- `Summarizer`
  - `summarize(turns) -> summary_text`

**Adapter**
- `ChromaMcpVectorStoreAdapter(VectorStore)`
  - The only place that knows MCP tool names, payloads, and error mapping.

**Services**
- `HistoryService(HistoryStore)`
- `MemoryService(VectorStore, MemoryPolicy, MemoryRouter)`
- `ContextBuilder(HistoryService, MemoryService)`

**Why this stays SOLID without bloat**
- Single Responsibility: each service has one job.
- Open/Closed: adding collections is config + router mapping.
- Dependency Inversion: services depend on ports, not MCP/Chroma.

### B.3 Collection registry and routing (V2-ready)
Move collection naming into config:

- `history_messages`
- `history_summaries` (V2)
- `mem_episodic` (V2)
- `mem_semantic` (V2)
- `mem_procedural` (V2)
- `mem_narrative` (V2)

A `MemoryRouter` maps `memory_type -> collection_name`.
V1 keeps only `history` and `memory`, but the router makes V2 trivial.

### B.4 Where “history” should live
V1 stores history in Chroma for simplicity.

If you later want cleaner separation:
- keep **history** in Postgres/SQLite (exact replay, ordering)
- keep **memory** in Chroma (semantic recall)

This can be introduced without changing your agent logic much if you keep the `HistoryStore` port.

### B.5 MCP transport mode note
Most MCP clients integrate via **stdio** (spawn the MCP server and talk over standard input/output).
Some setups run MCP servers over HTTP.

Either way, your agent-app should treat it the same:
- **gateway/adapter** owns the transport
- services stay unchanged

### B.6 Growth guardrails (to avoid memory spam)
Even in V1, keep these simple rules:
- store only if `confidence >= threshold`
- max `MEMORY_MAX_PER_WINDOW` (e.g., 3)
- cap length of any stored item (summarize first)

---

