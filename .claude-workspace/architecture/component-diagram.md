# Component Diagram: Chroma MCP Memory V1

**Date:** 2025-12-25
**Version:** 1.0

---

## High-Level Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                          Docker Compose Environment                    │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                      agent-app Container                      │   │
│  │                                                                │   │
│  │  ┌────────────────────────────────────────────────────────┐  │   │
│  │  │                    app.py                              │  │   │
│  │  │              (Orchestration Layer)                     │  │   │
│  │  │  - Message handling                                    │  │   │
│  │  │  - Flow coordination                                   │  │   │
│  │  │  - Component wiring                                    │  │   │
│  │  └───────┬─────────────┬─────────────┬───────────────────┘  │   │
│  │          │             │             │                       │   │
│  │          ▼             ▼             ▼                       │   │
│  │  ┌─────────────┐ ┌──────────────┐ ┌─────────────────────┐  │   │
│  │  │  memory_    │ │  context_    │ │  memory_            │  │   │
│  │  │  gateway.py │ │  builder.py  │ │  policy.py          │  │   │
│  │  │             │ │              │ │                     │  │   │
│  │  │ Transport   │ │ Assembly     │ │ Policy Logic        │  │   │
│  │  │ Layer       │ │ Layer        │ │                     │  │   │
│  │  └──────┬──────┘ └──────┬───────┘ └─────────────────────┘  │   │
│  │         │                │                                   │   │
│  │         └────────────────┘                                   │   │
│  │                  │                                           │   │
│  │                  │ MCP Tool Calls (stdio)                    │   │
│  └──────────────────┼───────────────────────────────────────────┘   │
│                     │                                                │
│  ┌──────────────────┼────────────────────────────────────────────┐  │
│  │                  ▼                                            │  │
│  │  ┌──────────────────────────────────────────────────────┐   │  │
│  │  │              chroma-mcp Container                     │   │  │
│  │  │                                                       │   │  │
│  │  │  ┌────────────────────────────────────────────────┐  │   │  │
│  │  │  │          MCP Gateway Server                    │  │   │  │
│  │  │  │  - Collection management                       │  │   │  │
│  │  │  │  - Document operations                         │  │   │  │
│  │  │  │  - Query operations                            │  │   │  │
│  │  │  │  - Protocol translation (MCP ↔ HTTP)           │  │   │  │
│  │  │  └────────────────────────────────────────────────┘  │   │  │
│  │  │                        │                              │   │  │
│  │  │                        │ HTTP API                     │   │  │
│  │  └────────────────────────┼──────────────────────────────┘   │  │
│  │                           │                                  │  │
│  │  ┌────────────────────────┼──────────────────────────────┐  │  │
│  │  │                        ▼                              │  │  │
│  │  │  ┌───────────────────────────────────────────────┐   │  │  │
│  │  │  │         ChromaDB Container                    │   │  │  │
│  │  │  │                                                │   │  │  │
│  │  │  │  ┌─────────────────────────────────────────┐  │   │  │  │
│  │  │  │  │      ChromaDB Server                    │  │   │  │  │
│  │  │  │  │  - Vector storage                       │  │   │  │  │
│  │  │  │  │  - Embedding generation                 │  │   │  │  │
│  │  │  │  │  - Similarity search                    │  │   │  │  │
│  │  │  │  │  - Metadata filtering                   │  │   │  │  │
│  │  │  │  └─────────────────────────────────────────┘  │   │  │  │
│  │  │  │                    │                           │   │  │  │
│  │  │  │                    ▼                           │   │  │  │
│  │  │  │  ┌─────────────────────────────────────────┐  │   │  │  │
│  │  │  │  │     Persistent Volume: chroma_data      │  │   │  │  │
│  │  │  │  │  - history collection                   │  │   │  │  │
│  │  │  │  │  - memory collection                    │  │   │  │  │
│  │  │  │  └─────────────────────────────────────────┘  │   │  │  │
│  │  │  └───────────────────────────────────────────────┘   │  │  │
│  │  └──────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. agent-app (MCP Client Application)

**Container**: `agent-app`
**Language**: Python 3.11+
**Build**: Custom Dockerfile

#### Subcomponents:

##### 1.1 app.py (Orchestration Layer)
**Responsibilities**:
- Application entrypoint and lifecycle management
- Message routing and flow coordination
- Component initialization and dependency injection
- Error handling and logging orchestration

**Dependencies**:
- memory_gateway.py
- context_builder.py
- memory_policy.py

**Configuration**: Environment variables (see TR-ENV in specification)

##### 1.2 memory_gateway.py (Transport Layer)
**Responsibilities**:
- MCP protocol communication (stdio transport)
- Payload serialization/deserialization
- Connection management and retries
- Error mapping (MCP errors → domain exceptions)
- Rate limiting and circuit breaking

**Interfaces**:
```python
class MemoryGateway:
    ensure_collections(names: list[str]) -> None
    append_history(conversation_id, role, text, turn_index, ts, ...) -> str
    tail_history(conversation_id, n) -> list[dict]
    write_memory(text, memory_type, confidence, ts, ...) -> str
    recall_memory(query_text, k, min_confidence, ...) -> list[dict]
```

**External dependencies**: chroma-mcp (via MCP stdio)

##### 1.3 context_builder.py (Assembly Layer)
**Responsibilities**:
- Fetch history and memory via gateway
- Assemble context dictionary
- Token budget management and truncation
- Format context as LLM prompt string

**Interfaces**:
```python
class ContextBuilder:
    build_context(conversation_id, latest_user_text) -> dict
    format_for_prompt(context: dict) -> str
```

**Dependencies**: MemoryGateway

##### 1.4 memory_policy.py (Policy Layer)
**Responsibilities**:
- Determine if memory meets storage criteria
- Enforce rate limits (max memories per window)
- Validate memory types
- Pure logic, no I/O

**Interfaces**:
```python
class MemoryPolicy:
    should_store(memory_type, confidence) -> bool
    enforce_rate_limit(window_key) -> bool
    validate_memory_type(memory_type) -> bool
```

**Dependencies**: None (stateless, pure logic)

---

### 2. chroma-mcp (MCP Gateway)

**Container**: `chroma-mcp`
**Image**: `ghcr.io/chroma-core/chroma-mcp:latest`
**Protocol**: MCP (Model Context Protocol) over stdio
**Stateless**: No persistent state

#### Responsibilities:
- Expose ChromaDB operations as MCP tools
- Translate MCP requests → ChromaDB HTTP API calls
- Translate ChromaDB responses → MCP responses
- Handle connection pooling to ChromaDB
- Provide schema validation for requests

#### MCP Tools Exposed:
| Tool | Purpose |
|------|---------|
| `list_collections` | List all collections in ChromaDB |
| `create_collection` | Create a new collection |
| `add_documents` | Add documents to a collection |
| `get_documents` | Get documents by metadata filter |
| `query_collection` | Semantic search (vector similarity) |
| `delete_documents` | Delete documents by IDs (V2) |

#### Configuration:
- `CHROMA_CLIENT_TYPE=http` (connect via HTTP, not embedded)
- `CHROMA_HTTP_HOST=chroma` (Docker service name)
- `CHROMA_HTTP_PORT=8000` (ChromaDB default port)

---

### 3. ChromaDB (Vector Database)

**Container**: `chroma`
**Image**: `chromadb/chroma:latest`
**Port**: 8000 (internal Docker network)
**Persistence**: Docker volume `chroma_data:/chroma/chroma`

#### Responsibilities:
- Store document vectors and metadata
- Generate embeddings (default model or custom)
- Perform vector similarity search
- Filter results by metadata
- Manage collections and indices

#### Collections (V1):
| Collection | Purpose | Size | Access Pattern |
|------------|---------|------|----------------|
| `history` | Conversation turns | Large (100s-1000s per conversation) | Ordered retrieval by conversation_id + turn_index |
| `memory` | Deliberate memories | Small (10s-100s total) | Semantic search with metadata filters |

#### API Endpoints (used by chroma-mcp):
- `GET /api/v1/heartbeat` - Health check
- `POST /api/v1/collections` - Create collection
- `GET /api/v1/collections` - List collections
- `POST /api/v1/collections/{name}/add` - Add documents
- `POST /api/v1/collections/{name}/get` - Get documents
- `POST /api/v1/collections/{name}/query` - Query (semantic search)

#### Configuration:
- `IS_PERSISTENT=TRUE` - Enable persistence
- `ANONYMIZED_TELEMETRY=FALSE` - Disable telemetry

---

## Data Flow Summary

### Flow 1: Append History
```
User Message → app.py → gateway.append_history()
→ chroma-mcp (add_documents) → ChromaDB HTTP API
→ history collection → chroma_data volume
```

### Flow 2: Write Memory
```
Agent decides to remember → policy.should_store() [gate]
→ gateway.write_memory() → chroma-mcp (add_documents)
→ ChromaDB HTTP API → memory collection → chroma_data volume
```

### Flow 3: Build Context
```
User message arrives → builder.build_context()
→ gateway.tail_history() [parallel] gateway.recall_memory()
→ chroma-mcp (get_documents + query_collection)
→ ChromaDB HTTP API → Assemble context dictionary
→ Format for LLM prompt
```

### Flow 4: Bootstrap
```
docker compose up → ChromaDB starts → Health check passes
→ chroma-mcp starts → agent-app starts
→ gateway.ensure_collections(["history", "memory"])
→ chroma-mcp (create_collection if not exists)
→ ChromaDB HTTP API → Application ready
```

---

## Network Topology

```
┌─────────────────────────────────────────────────────────┐
│              Docker Network: mcp_memory_net             │
│                                                         │
│   agent-app:80         chroma-mcp:stdio      chroma:8000│
│        │                    │                     │     │
│        └────────MCP─────────┘                     │     │
│                          │                        │     │
│                          └────────HTTP────────────┘     │
│                                                         │
└─────────────────────────────────────────────────────────┘
           │
           │ (Optional: expose ports)
           ▼
    Host: localhost:8000 (ChromaDB admin)
```

**Port exposure (configurable)**:
- ChromaDB 8000: Optionally exposed for debugging/admin (not required for production)
- agent-app: Only expose if providing API/UI (not required for V1)
- chroma-mcp: Never exposed (stdio communication only)

---

## Deployment Dependencies

```
┌──────────────┐
│   chroma     │  (no dependencies)
└──────┬───────┘
       │ depends_on: service_healthy
       ▼
┌──────────────┐
│  chroma-mcp  │
└──────┬───────┘
       │ depends_on: service_started
       ▼
┌──────────────┐
│  agent-app   │
└──────────────┘
```

**Health checks**:
- ChromaDB: `wget -qO- http://localhost:8000/api/v1/heartbeat` (every 10s)
- chroma-mcp: Service started (no health check needed, stateless)
- agent-app: Service started (bootstrap validates collections)

---

## Volume Management

```
┌─────────────────────────────────────────┐
│   Docker Volume: chroma_data            │
│                                         │
│   /chroma/chroma/                       │
│   ├── chroma.sqlite3                    │
│   ├── index/                            │
│   │   ├── history_collection/           │
│   │   └── memory_collection/            │
│   └── wal/                              │
└─────────────────────────────────────────┘
          ▲
          │ mounted at /chroma/chroma
          │
    ┌─────┴──────┐
    │   chroma   │
    │ container  │
    └────────────┘
```

**Backup strategy**:
```bash
# Backup
docker run --rm -v chroma_data:/data -v $(pwd):/backup \
  busybox tar czf /backup/chroma_backup.tar.gz /data

# Restore
docker run --rm -v chroma_data:/data -v $(pwd):/backup \
  busybox tar xzf /backup/chroma_backup.tar.gz -C /
```

---

## Component Interaction Sequence

See `data-flows.md` for detailed sequence diagrams of key operations.

---

## Security Boundaries

```
┌────────────────────────────────────────┐
│      Docker Network (Trusted)          │
│  ┌──────────┐  ┌──────────┐  ┌──────┐ │
│  │agent-app │  │chroma-mcp│  │chroma│ │
│  │          │  │          │  │      │ │
│  └──────────┘  └──────────┘  └──────┘ │
│   No authentication between services   │
└────────────────────────────────────────┘
              │
              │ (Optional external access)
              ▼
        Host firewall
```

**V1 security posture**:
- All services on internal Docker network (not exposed to internet)
- No authentication between services (trust boundary = Docker network)
- Ports exposed only for debugging (not in production)
- Volume encryption via OS-level volume encryption (if required)

**V2 security enhancements** (if needed):
- TLS between chroma-mcp and ChromaDB
- API key authentication for MCP tools
- Network policies for pod-to-pod communication (if migrating to K8s)

---

## Observability

**Logging**:
- agent-app: Structured JSON logs to stdout
- chroma-mcp: MCP protocol logs to stdout
- ChromaDB: Server logs to stdout

**Metrics** (V2):
- Message throughput (messages/second)
- Memory writes (writes/minute)
- Query latency (p50, p95, p99)
- Collection sizes

**Health checks**:
- ChromaDB: HTTP heartbeat endpoint
- chroma-mcp: Process liveness
- agent-app: Bootstrap success indicator

---

## Scalability Considerations

**V1 scale limits**:
- Single ChromaDB instance (no clustering)
- Single agent-app instance (no load balancing)
- Up to 100K documents total
- Up to 10 concurrent conversations

**V2 horizontal scaling**:
- Multiple agent-app replicas (stateless, can scale)
- Load balancer in front of agent-app
- ChromaDB clustering (if supported) or migration to Qdrant/Weaviate
- Shared volume or object storage for ChromaDB data

---

## Technology Stack Summary

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| agent-app | Python | 3.11+ | Application logic |
| chroma-mcp | Node.js/MCP | latest | Protocol gateway |
| ChromaDB | Python/FastAPI | latest | Vector database |
| Docker | Docker Engine | 20.10+ | Containerization |
| Docker Compose | Compose | 2.0+ | Orchestration |
| MCP | Protocol | 1.0+ | Client-server protocol |

---

**Related documents**:
- ADR-001: Docker-First Deployment
- ADR-002: ChromaDB as Vector Store
- ADR-003: Separation of Concerns
- ADR-004: Two-Collection Model
- data-flows.md: Detailed flow diagrams
- directory-structure.md: Code organization
