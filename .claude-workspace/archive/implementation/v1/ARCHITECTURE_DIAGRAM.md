# Chroma MCP Memory V1 - Architecture Diagram

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Docker Compose Stack                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │                    agent-app Container                      │    │
│  │                      (Python 3.11)                          │    │
│  │  ┌────────────────────────────────────────────────────┐    │    │
│  │  │              app.py (Orchestration)                │    │    │
│  │  │  - Bootstrap                                       │    │    │
│  │  │  - Handle messages                                 │    │    │
│  │  │  - Store memories                                  │    │    │
│  │  │  - Demonstrate flows                               │    │    │
│  │  └──────────┬──────────────┬──────────────┬───────────┘    │    │
│  │             │              │              │                 │    │
│  │  ┌──────────▼──────┐  ┌───▼──────┐  ┌───▼─────────┐       │    │
│  │  │MemoryGateway    │  │Context   │  │Memory       │       │    │
│  │  │                 │  │Builder   │  │Policy       │       │    │
│  │  │- ensure_collections  │- build_context  │- should_store  │    │
│  │  │- append_history │  │- format_for_prompt │- enforce_rate_limit  │
│  │  │- tail_history   │  │- truncate_to_budget │- validate_memory_type │
│  │  │- write_memory   │  │                 │                 │       │    │
│  │  │- recall_memory  │  │                 │                 │       │    │
│  │  └────────┬────────┘  └────┬────────┘  └─────────────┘   │    │
│  │           │                 │                              │    │
│  │           │ HTTP            │ Uses Gateway                 │    │
│  │           │ (httpx async)   │                              │    │
│  └───────────┼─────────────────┼──────────────────────────────┘    │
│              │                 │                                    │
│              │                 │                                    │
│  ┌───────────▼─────────────────▼──────────────────────────────┐   │
│  │                    chroma Container                          │   │
│  │                  (ChromaDB Vector Database)                  │   │
│  │                                                               │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │              HTTP API Server (Port 8000)              │   │   │
│  │  │                                                        │   │   │
│  │  │  Endpoints:                                            │   │   │
│  │  │  - POST /api/v1/collections                            │   │   │
│  │  │  - GET  /api/v1/collections                            │   │   │
│  │  │  - POST /api/v1/collections/{name}/add                 │   │   │
│  │  │  - POST /api/v1/collections/{name}/get                 │   │   │
│  │  │  - POST /api/v1/collections/{name}/query               │   │   │
│  │  │  - GET  /api/v1/heartbeat                              │   │   │
│  │  └──────────────────────┬───────────────────────────────┘   │   │
│  │                         │                                    │   │
│  │  ┌──────────────────────▼───────────────────────────────┐   │   │
│  │  │              Collections                               │   │   │
│  │  │                                                        │   │   │
│  │  │  ┌────────────────┐       ┌────────────────┐         │   │   │
│  │  │  │   history      │       │    memory      │         │   │   │
│  │  │  │                │       │                │         │   │   │
│  │  │  │ - documents    │       │ - documents    │         │   │   │
│  │  │  │ - embeddings   │       │ - embeddings   │         │   │   │
│  │  │  │ - metadata     │       │ - metadata     │         │   │   │
│  │  │  │   * conv_id    │       │   * type       │         │   │   │
│  │  │  │   * role       │       │   * confidence │         │   │   │
│  │  │  │   * turn_index │       │   * ts         │         │   │   │
│  │  │  │   * ts         │       │   * conv_id    │         │   │   │
│  │  │  └────────────────┘       └────────────────┘         │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                         │                                    │   │
│  │  ┌──────────────────────▼───────────────────────────────┐   │   │
│  │  │          Persistent Storage (SQLite + HNSW)          │   │   │
│  │  │                                                        │   │   │
│  │  │  - chroma.sqlite3 (metadata + documents)              │   │   │
│  │  │  - index/ (HNSW vector indices)                       │   │   │
│  │  │                                                        │   │   │
│  │  │  Mounted to: /chroma/chroma                           │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                         │                                    │   │
│  └─────────────────────────┼────────────────────────────────┘   │
│                            │                                      │
│                            ▼                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              Docker Volume: chroma_data                     │ │
│  │              (Persistent across container restarts)         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │               chroma-mcp Container (Optional)               │ │
│  │                    (MCP Gateway - unused in V1)             │ │
│  │                                                              │ │
│  │  Note: V1 uses ChromaDB HTTP API directly for simplicity   │ │
│  │  V2 will integrate stdio-based MCP protocol                │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

## Data Flow: Message Processing

```
User sends message
       │
       ▼
┌──────────────────┐
│   app.py         │
│ handle_message() │
└────┬─────────────┘
     │
     │ 1. Store in history
     ▼
┌──────────────────┐
│MemoryGateway     │
│ append_history() │
└────┬─────────────┘
     │
     │ HTTP POST /collections/history/add
     ▼
┌──────────────────┐
│   ChromaDB       │
│   - Embed text   │
│   - Store doc    │
│   - Store vector │
│   - Persist      │
└────┬─────────────┘
     │
     │ Document ID
     ▼
┌──────────────────┐
│   app.py         │
│ Log success      │
└──────────────────┘
```

## Data Flow: Context Building

```
User message arrives
       │
       ▼
┌──────────────────┐
│   app.py         │
│ handle_message() │
└────┬─────────────┘
     │
     │ 2. Build context
     ▼
┌──────────────────────────────────┐
│      ContextBuilder              │
│      build_context()             │
└──────┬───────────────────┬───────┘
       │                   │
       │ Parallel fetch    │
       │                   │
   ┌───▼────┐         ┌────▼────┐
   │ tail_  │         │ recall_ │
   │history │         │ memory  │
   └───┬────┘         └────┬────┘
       │                   │
       ▼                   ▼
┌────────────────────────────────┐
│      MemoryGateway             │
│ - tail_history()               │
│ - recall_memory()              │
└──────┬─────────────────┬───────┘
       │                 │
       │ HTTP GET        │ HTTP POST
       │ /get            │ /query
       │                 │
       ▼                 ▼
┌────────────────────────────────┐
│         ChromaDB               │
│ - Get last N by metadata       │
│ - Vector similarity search     │
└──────┬─────────────────┬───────┘
       │                 │
       │ History turns   │ Memories + scores
       │                 │
       ▼                 ▼
┌────────────────────────────────┐
│      ContextBuilder            │
│ - Parse results                │
│ - Assemble ContextPackage      │
│ - Apply token budget           │
│ - Format for LLM               │
└──────┬─────────────────────────┘
       │
       │ Formatted context string
       ▼
┌──────────────────┐
│   app.py         │
│ Generate response│
└──────────────────┘
```

## Data Flow: Memory Storage with Policy

```
Agent identifies worth-remembering info
       │
       ▼
┌──────────────────┐
│   app.py         │
│ store_memory()   │
└────┬─────────────┘
     │
     │ 1. Check policy
     ▼
┌──────────────────┐
│ MemoryPolicy     │
│ should_store()   │
│                  │
│ confidence >= 0.7?
│   ✓ Yes          │
└────┬─────────────┘
     │
     │ 2. Check rate limit
     ▼
┌──────────────────┐
│ MemoryPolicy     │
│enforce_rate_limit()
│                  │
│ count < 3?       │
│   ✓ Yes          │
└────┬─────────────┘
     │
     │ 3. Store
     ▼
┌──────────────────┐
│ MemoryGateway    │
│ write_memory()   │
└────┬─────────────┘
     │
     │ HTTP POST /collections/memory/add
     ▼
┌──────────────────┐
│   ChromaDB       │
│   - Embed text   │
│   - Store doc    │
│   - Store vector │
│   - Store metadata
│   - Persist      │
└────┬─────────────┘
     │
     │ Document ID
     ▼
┌──────────────────┐
│   app.py         │
│ Log success      │
└──────────────────┘
```

## Module Dependencies

```
app.py (orchestration)
  │
  ├─> config.py (configuration)
  │
  ├─> memory_gateway.py (transport)
  │     ├─> httpx (HTTP client)
  │     ├─> exceptions.py
  │     └─> utils.py (logging)
  │
  ├─> context_builder.py (assembly)
  │     ├─> memory_gateway.py
  │     ├─> models.py
  │     ├─> exceptions.py
  │     └─> utils.py (token counting)
  │
  ├─> memory_policy.py (logic)
  │     └─> (no dependencies - pure logic)
  │
  ├─> models.py (data)
  │     └─> (stdlib only)
  │
  ├─> exceptions.py (errors)
  │     └─> (stdlib only)
  │
  └─> utils.py (utilities)
        └─> (stdlib only)
```

## File Organization

```
.claude-workspace/implementation/
│
├── docker-compose.yml          # 3-service orchestration
│
└── agent-app/
    ├── Dockerfile              # Container definition
    ├── requirements.txt        # Python dependencies
    ├── .env.example            # Config template
    ├── README.md               # Documentation
    │
    ├── src/                    # Source code
    │   ├── __init__.py         # Package init
    │   ├── app.py              # Main application (244 lines)
    │   ├── config.py           # Configuration (68 lines)
    │   ├── memory_gateway.py   # MCP transport (498 lines)
    │   ├── context_builder.py  # Context assembly (342 lines)
    │   ├── memory_policy.py    # Policy logic (149 lines)
    │   ├── models.py           # Data models (133 lines)
    │   ├── exceptions.py       # Custom errors (28 lines)
    │   └── utils.py            # Utilities (109 lines)
    │
    └── tests/                  # Test suite (ready for implementation)
        ├── unit/
        │   ├── test_config.py
        │   ├── test_models.py
        │   ├── test_utils.py
        │   ├── test_memory_policy.py
        │   ├── test_context_builder.py
        │   └── test_memory_gateway.py
        │
        └── integration/
            ├── test_end_to_end.py
            └── test_persistence.py
```

## Collections Schema

### history Collection

```
{
  "document": "User: I want to build a memory system...",
  "metadata": {
    "conversation_id": "conv_123",
    "role": "user",
    "ts": "2025-12-25T12:00:00Z",
    "turn_index": 1,
    "message_id": "msg_abc123",  // optional
    "channel": "web"              // optional
  },
  "embedding": [0.123, 0.456, ...]  // auto-generated
}
```

**Purpose:** Store every conversation turn for context replay
**Retrieval:** Get last N by (conversation_id, turn_index DESC)

### memory Collection

```
{
  "document": "User prefers Docker-based solutions",
  "metadata": {
    "type": "preference",
    "confidence": 0.85,
    "ts": "2025-12-25T12:01:00Z",
    "conversation_id": "conv_123",  // optional
    "entities": "docker,deployment", // optional
    "source": "chat",                // optional
    "tags": "preference,infra"       // optional
  },
  "embedding": [0.789, 0.012, ...]  // auto-generated
}
```

**Purpose:** Store deliberate, high-value memories
**Retrieval:** Vector similarity search with metadata filters

## Environment Configuration Flow

```
1. Docker Compose starts agent-app container
       │
       ▼
2. Container loads environment variables
   - MCP_ENDPOINT=chroma
   - MEMORY_CONFIDENCE_MIN=0.7
   - HISTORY_TAIL_N=16
   - MEMORY_TOP_K=8
   - MEMORY_MAX_PER_WINDOW=3
   - LOG_LEVEL=INFO
       │
       ▼
3. app.py calls AppConfig.from_env()
       │
       ▼
4. config.py loads and validates each variable
       │
       ▼
5. config.validate() ensures all values are valid
       │
       ▼
6. AppConfig instance passed to Application()
       │
       ▼
7. Components initialized with config values
```

## Key Design Decisions

1. **Direct ChromaDB HTTP**: V1 uses HTTP API directly for simplicity
2. **Async/Await**: All I/O is async for optimal performance
3. **Parallel Fetching**: Context builder fetches history + memories concurrently
4. **In-Memory Rate Limiting**: Simple dict tracking for V1
5. **Token Budget**: Optional truncation with priority (message > history > memories)
6. **Graceful Degradation**: Context build continues even if history/memory fetch fails
7. **Structured Logging**: JSON logs for easy parsing and monitoring
8. **Environment-Driven**: All config via env vars for 12-factor app compliance

---

**This architecture delivers:**
- ✅ Clean separation of concerns
- ✅ Testable components (easy to mock)
- ✅ Scalable design (stateless agent-app)
- ✅ Observable (structured logs)
- ✅ Configurable (environment variables)
- ✅ Resilient (error handling + graceful degradation)
