# Chroma MCP Memory V1 – Technical Specification

**Version:** 1.0
**Date:** 2025-12-25
**Status:** Draft for Implementation
**Technical PM:** Claude (Autonomous Development Team)

---

## Executive Summary

This specification defines V1 of an LLM memory system that provides persistent conversation history and semantic memory storage using ChromaDB, exposed via the chroma-mcp gateway, with memory policy and context assembly implemented in a Python agent application.

V1 scope is intentionally minimal: reliable storage and retrieval of conversation history and deliberate memories, with persistence across container restarts.

---

## 1. Functional Requirements

### 1.1 Conversation History (FR-HIST)

**FR-HIST-001: Store Message Turns**
- The system SHALL store every user and assistant message turn
- Each turn SHALL be stored with complete metadata (conversation_id, role, timestamp, turn_index)
- Storage SHALL happen synchronously on each message
- No message SHALL be lost during normal operation

**FR-HIST-002: Retrieve Recent History**
- The system SHALL retrieve the last N turns for a given conversation_id
- Retrieval SHALL maintain chronological order (oldest to newest)
- The number of turns (N) SHALL be configurable via environment variable
- Default retrieval SHALL be 16 turns

**FR-HIST-003: Multi-Session Support**
- The system SHALL support multiple concurrent conversations
- Each conversation SHALL be isolated by conversation_id
- History retrieval SHALL filter by conversation_id

### 1.2 Long-Term Memory (FR-MEM)

**FR-MEM-001: Store Deliberate Memories**
- The system SHALL store "worth remembering" items determined by the agent
- Each memory SHALL include type classification (preference, fact, project, decision)
- Each memory SHALL include confidence score (0.0-1.0)
- Storage SHALL be gated by minimum confidence threshold

**FR-MEM-002: Semantic Memory Recall**
- The system SHALL perform vector similarity search over stored memories
- Search SHALL support metadata filtering (e.g., confidence >= threshold)
- Search SHALL return top-K most relevant memories
- The number of results (K) SHALL be configurable via environment variable
- Default top-K SHALL be 8 results

**FR-MEM-003: Memory Quality Gates**
- Only memories with confidence >= MEMORY_CONFIDENCE_MIN SHALL be stored
- Default minimum confidence SHALL be 0.7
- The system SHALL limit memory writes to prevent spam (max 1-3 per window)

### 1.3 Context Building (FR-CTX)

**FR-CTX-001: Assemble Context for LLM**
- Before each assistant response, the system SHALL build context containing:
  - Recent conversation history (chronological tail)
  - Relevant memories from semantic search
  - The latest user message
- Context SHALL be formatted for optimal LLM consumption

**FR-CTX-002: Context Budget Management**
- The system SHALL support optional token budget limits
- If budget is specified, context SHALL be truncated to fit
- Truncation SHALL prioritize: latest message > recent history > memories

### 1.4 Persistence (FR-PERS)

**FR-PERS-001: Survive Container Restarts**
- All data SHALL persist across Docker container restarts
- Persistence SHALL be provided via Docker volumes
- No data loss SHALL occur during graceful shutdown and restart

**FR-PERS-002: Volume-Based Storage**
- ChromaDB SHALL use a named Docker volume (chroma_data)
- Volume SHALL be mounted at /chroma/chroma
- Volume SHALL be the single source of persistence

---

## 2. Technical Requirements

### 2.1 Architecture Overview

The system consists of three Docker services:

```
┌─────────────────────────────────────┐
│      Agent App (MCP Client)         │
│  - memory_gateway.py                │
│  - context_builder.py               │
│  - memory_policy.py                 │
│  - app.py                           │
└──────────────┬──────────────────────┘
               │ MCP Tool Calls
               ▼
┌─────────────────────────────────────┐
│      chroma-mcp (Gateway)           │
│  - Stateless MCP server             │
│  - Exposes collection/doc/query     │
└──────────────┬──────────────────────┘
               │ HTTP API
               ▼
┌─────────────────────────────────────┐
│      ChromaDB (Vector Database)     │
│  - Persistent storage               │
│  - Vector similarity search         │
│  - Volume: chroma_data              │
└─────────────────────────────────────┘
```

### 2.2 Docker Services (TR-DOCKER)

**TR-DOCKER-001: ChromaDB Service**
- Image: `chromadb/chroma:latest`
- Container name: `chroma`
- Port: 8000 (internal to Docker network, optionally exposed)
- Volume: `chroma_data:/chroma/chroma`
- Environment variables:
  - `IS_PERSISTENT=TRUE`
  - `ANONYMIZED_TELEMETRY=FALSE`
- Health check: HTTP GET to `/api/v1/heartbeat` every 10s

**TR-DOCKER-002: chroma-mcp Service**
- Image: `ghcr.io/chroma-core/chroma-mcp:latest`
- Container name: `chroma-mcp`
- Depends on: chroma (service_healthy)
- Environment variables:
  - `CHROMA_CLIENT_TYPE=http`
  - `CHROMA_HTTP_HOST=chroma`
  - `CHROMA_HTTP_PORT=8000`
- Transport: stdio (spawned by MCP client)

**TR-DOCKER-003: agent-app Service**
- Build context: `./agent-app`
- Container name: `agent-app`
- Depends on: chroma-mcp (service_started)
- Environment variables: (see section 2.5)
- No persistent volume required (stateless)

### 2.3 Collections and Schemas (TR-COLL)

**TR-COLL-001: history Collection**

Purpose: Store every conversation turn for replay and context

Schema:
- Document text: Raw message text (as-is)
- Metadata (required):
  - `conversation_id` (string) – identifies the conversation thread
  - `role` (string) – one of: "user", "assistant", "system"
  - `ts` (string) – ISO-8601 timestamp
  - `turn_index` (int) – monotonic turn counter within conversation
- Metadata (optional):
  - `message_id` (string) – unique identifier for deduplication
  - `channel` (string) – source channel (web, app, slack, etc.)

Indexing: Automatic vector embedding by ChromaDB

Retrieval pattern: Get last N by (conversation_id, turn_index DESC)

**TR-COLL-002: memory Collection**

Purpose: Store deliberate, high-value memories for semantic recall

Schema:
- Document text: Memory statement or summary text
- Metadata (required):
  - `type` (string) – one of: "preference", "fact", "project", "decision"
  - `confidence` (float) – range [0.0, 1.0]
  - `ts` (string) – ISO-8601 timestamp
  - `conversation_id` (string, optional) – source conversation if applicable
- Metadata (optional):
  - `entities` (string) – comma-separated entity list
  - `source` (string) – one of: "chat", "tool", "import"
  - `tags` (string) – comma-separated tag list

Indexing: Automatic vector embedding by ChromaDB

Retrieval pattern: Semantic query with metadata filters (e.g., confidence >= 0.7)

### 2.4 MCP Operations (TR-MCP)

The agent-app SHALL use the following MCP operations provided by chroma-mcp:

**TR-MCP-001: Collection Management**
- Ensure collections exist (bootstrap): `history`, `memory`
- List collections to verify existence

**TR-MCP-002: Document Operations**
- Add document to collection with text and metadata
- Batch add (if multiple documents)

**TR-MCP-003: Query Operations**
- Semantic query: query_text, limit (top-K), where (metadata filter)
- Get documents: collection, where (metadata filter), limit, sort

**TR-MCP-004: No Update/Delete Required**
- V1 does NOT require update or delete operations
- Append-only model for simplicity

### 2.5 Environment Variables (TR-ENV)

**Agent-app environment variables:**

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MCP_ENDPOINT` | string | "chroma-mcp" | MCP server endpoint (hostname or URL) |
| `MEMORY_CONFIDENCE_MIN` | float | 0.7 | Minimum confidence to store a memory |
| `HISTORY_TAIL_N` | int | 16 | Number of recent turns to retrieve |
| `MEMORY_TOP_K` | int | 8 | Number of memories to retrieve in semantic search |
| `MEMORY_MAX_PER_WINDOW` | int | 3 | Maximum memories to store per chunk/window |
| `CONTEXT_TOKEN_BUDGET` | int | null | Optional token limit for context assembly |
| `LOG_LEVEL` | string | "INFO" | Logging verbosity (DEBUG, INFO, WARN, ERROR) |

**ChromaDB environment variables:**

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `IS_PERSISTENT` | string | "TRUE" | Enable persistent storage |
| `ANONYMIZED_TELEMETRY` | string | "FALSE" | Disable telemetry |

**chroma-mcp environment variables:**

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CHROMA_CLIENT_TYPE` | string | "http" | Client type (http or in-memory) |
| `CHROMA_HTTP_HOST` | string | "chroma" | ChromaDB hostname |
| `CHROMA_HTTP_PORT` | int | 8000 | ChromaDB port |

### 2.6 Code Structure (TR-CODE)

**Agent-app directory structure:**

```
agent-app/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── app.py                 # Main application entrypoint
│   ├── memory_gateway.py      # MCP transport layer
│   ├── context_builder.py     # Context assembly logic
│   └── memory_policy.py       # Memory storage policy
└── tests/
    ├── __init__.py
    ├── test_memory_gateway.py
    ├── test_context_builder.py
    └── test_memory_policy.py
```

---

## 3. API Contracts

### 3.1 memory_gateway.py Interface

The memory gateway SHALL provide a clean abstraction over MCP tool calls.

**Class: MemoryGateway**

```python
class MemoryGateway:
    """Transport layer for MCP operations. No business logic."""

    def __init__(self, mcp_endpoint: str):
        """Initialize connection to MCP server."""
        pass

    def ensure_collections(self, names: list[str]) -> None:
        """Ensure collections exist, create if missing.

        Args:
            names: List of collection names to ensure exist

        Raises:
            ConnectionError: If MCP server is unreachable
            MCPError: If collection creation fails
        """
        pass

    def append_history(
        self,
        conversation_id: str,
        role: str,
        text: str,
        turn_index: int,
        ts: str,
        message_id: str | None = None,
        channel: str | None = None
    ) -> str:
        """Append a turn to history collection.

        Args:
            conversation_id: Conversation identifier
            role: Message role (user, assistant, system)
            text: Message text content
            turn_index: Monotonic turn counter
            ts: ISO-8601 timestamp
            message_id: Optional unique message identifier
            channel: Optional source channel

        Returns:
            Document ID assigned by ChromaDB

        Raises:
            ValueError: If required fields are missing or invalid
            MCPError: If storage operation fails
        """
        pass

    def tail_history(
        self,
        conversation_id: str,
        n: int
    ) -> list[dict]:
        """Retrieve last N turns from history.

        Args:
            conversation_id: Conversation identifier
            n: Number of recent turns to retrieve

        Returns:
            List of documents with text and metadata, ordered chronologically

        Raises:
            ValueError: If n < 1
            MCPError: If retrieval fails
        """
        pass

    def write_memory(
        self,
        text: str,
        memory_type: str,
        confidence: float,
        ts: str,
        conversation_id: str | None = None,
        entities: str | None = None,
        source: str | None = None,
        tags: str | None = None
    ) -> str:
        """Store a memory to memory collection.

        Args:
            text: Memory statement or summary
            memory_type: One of: preference, fact, project, decision
            confidence: Confidence score [0.0, 1.0]
            ts: ISO-8601 timestamp
            conversation_id: Optional source conversation
            entities: Optional comma-separated entity list
            source: Optional source type (chat, tool, import)
            tags: Optional comma-separated tag list

        Returns:
            Document ID assigned by ChromaDB

        Raises:
            ValueError: If required fields are invalid
            MCPError: If storage operation fails
        """
        pass

    def recall_memory(
        self,
        query_text: str,
        k: int,
        min_confidence: float,
        conversation_id: str | None = None
    ) -> list[dict]:
        """Semantic search over memory collection.

        Args:
            query_text: Query string for vector similarity
            k: Number of results to return (top-K)
            min_confidence: Minimum confidence threshold
            conversation_id: Optional filter by source conversation

        Returns:
            List of documents with text, metadata, and similarity scores

        Raises:
            ValueError: If k < 1 or min_confidence not in [0.0, 1.0]
            MCPError: If query fails
        """
        pass
```

**Error Handling:**
- All methods SHALL raise specific exceptions for different failure modes
- ConnectionError: MCP server unreachable
- MCPError: MCP operation failed
- ValueError: Invalid input parameters

### 3.2 context_builder.py Interface

The context builder SHALL assemble context from history and memory sources.

**Class: ContextBuilder**

```python
class ContextBuilder:
    """Assembles context from history and memory for LLM prompts."""

    def __init__(
        self,
        gateway: MemoryGateway,
        history_tail_n: int = 16,
        memory_top_k: int = 8,
        min_confidence: float = 0.7,
        token_budget: int | None = None
    ):
        """Initialize context builder.

        Args:
            gateway: Memory gateway instance
            history_tail_n: Number of history turns to retrieve
            memory_top_k: Number of memories to retrieve
            min_confidence: Minimum memory confidence threshold
            token_budget: Optional token limit for context
        """
        pass

    def build_context(
        self,
        conversation_id: str,
        latest_user_text: str
    ) -> dict:
        """Build complete context for LLM response generation.

        Args:
            conversation_id: Conversation identifier
            latest_user_text: Current user message text

        Returns:
            Dictionary containing:
            - history: List of recent turns (chronological)
            - memories: List of relevant memories (by relevance)
            - latest_message: Current user message
            - metadata: Token counts, truncation flags, etc.

        Raises:
            ContextBuildError: If context assembly fails
        """
        pass

    def format_for_prompt(self, context: dict) -> str:
        """Format context dictionary as string for LLM prompt.

        Args:
            context: Context dictionary from build_context()

        Returns:
            Formatted string ready for prompt injection
        """
        pass

    def _truncate_to_budget(self, context: dict) -> dict:
        """Truncate context to fit token budget.

        Priority: latest_message > history > memories
        """
        pass
```

### 3.3 memory_policy.py Interface

The memory policy SHALL determine when and what to store as memories.

**Class: MemoryPolicy**

```python
class MemoryPolicy:
    """Policy decisions for memory storage."""

    def __init__(
        self,
        min_confidence: float = 0.7,
        max_per_window: int = 3
    ):
        """Initialize memory policy.

        Args:
            min_confidence: Minimum confidence to store
            max_per_window: Maximum memories per window
        """
        pass

    def should_store(
        self,
        memory_type: str,
        confidence: float
    ) -> bool:
        """Determine if a memory should be stored.

        Args:
            memory_type: Type of memory (preference, fact, project, decision)
            confidence: Confidence score [0.0, 1.0]

        Returns:
            True if memory meets storage criteria
        """
        pass

    def enforce_rate_limit(self, window_key: str) -> bool:
        """Check if rate limit allows storing another memory.

        Args:
            window_key: Identifier for current window (e.g., conversation_id + time_bucket)

        Returns:
            True if under limit, False if limit reached
        """
        pass

    def validate_memory_type(self, memory_type: str) -> bool:
        """Validate memory type is recognized.

        Args:
            memory_type: Type to validate

        Returns:
            True if valid type
        """
        pass
```

---

## 4. Core Flows

### 4.1 Flow: Append History (F-HIST-APPEND)

**Trigger:** Every user or assistant message

**Preconditions:**
- agent-app is running
- chroma-mcp is connected to ChromaDB
- history collection exists

**Steps:**
1. Receive message with conversation_id, role, text
2. Generate turn_index (increment from last turn)
3. Generate ISO-8601 timestamp
4. Call `gateway.append_history(conversation_id, role, text, turn_index, ts)`
5. Log success or handle error

**Postconditions:**
- Message is stored in history collection
- Message is retrievable by conversation_id

**Error Handling:**
- On MCPError: Log error, optionally retry once
- On ConnectionError: Log error, queue for retry
- Never fail the user-facing operation due to history storage failure

### 4.2 Flow: Write Memory (F-MEM-WRITE)

**Trigger:** Agent determines a memory is worth storing

**Preconditions:**
- agent-app is running
- memory collection exists
- Memory meets policy criteria

**Steps:**
1. Agent extracts memory candidate (text, type, confidence)
2. Call `policy.should_store(memory_type, confidence)`
3. If False: skip storage, log decision
4. Call `policy.enforce_rate_limit(window_key)`
5. If False: skip storage, log rate limit
6. Generate ISO-8601 timestamp
7. Call `gateway.write_memory(text, memory_type, confidence, ts, ...)`
8. Log success or handle error

**Postconditions:**
- Memory is stored in memory collection
- Memory is retrievable via semantic search

**Error Handling:**
- On policy rejection: Log but do not retry
- On MCPError: Log error, do not retry (avoid spam)
- On ConnectionError: Log error, memory is lost (acceptable for V1)

### 4.3 Flow: Build Context (F-CTX-BUILD)

**Trigger:** Before generating assistant response

**Preconditions:**
- agent-app is running
- User message has been received

**Steps:**
1. Call `builder.build_context(conversation_id, latest_user_text)`
2. Within build_context:
   a. Call `gateway.tail_history(conversation_id, history_tail_n)`
   b. Call `gateway.recall_memory(latest_user_text, memory_top_k, min_confidence)`
   c. Assemble context dictionary with history, memories, latest_message
   d. If token_budget set: call `_truncate_to_budget(context)`
   e. Return context
3. Call `builder.format_for_prompt(context)`
4. Inject formatted string into LLM prompt
5. Generate response

**Postconditions:**
- LLM has access to relevant history and memories
- Context fits within token budget (if specified)

**Error Handling:**
- On gateway error: Use degraded context (e.g., only latest message)
- On truncation: Log truncation metadata
- Never fail response generation due to context build failure

### 4.4 Flow: Bootstrap (F-BOOT)

**Trigger:** Application startup

**Preconditions:**
- Docker Compose has started all services
- ChromaDB is healthy
- chroma-mcp is connected

**Steps:**
1. agent-app initializes MemoryGateway(mcp_endpoint)
2. Call `gateway.ensure_collections(["history", "memory"])`
3. Log collection status
4. Initialize ContextBuilder and MemoryPolicy
5. Mark application as ready

**Postconditions:**
- Both collections exist in ChromaDB
- Application is ready to handle messages

**Error Handling:**
- On collection creation failure: Log error and exit (fatal)
- On connection failure: Retry with exponential backoff (up to 5 attempts)

---

## 5. Data Models

### 5.1 History Turn

**Python dataclass:**

```python
@dataclass
class HistoryTurn:
    conversation_id: str
    role: str  # "user" | "assistant" | "system"
    text: str
    turn_index: int
    ts: str  # ISO-8601
    message_id: str | None = None
    channel: str | None = None
```

**Validation rules:**
- `conversation_id`: non-empty string
- `role`: must be one of ["user", "assistant", "system"]
- `text`: non-empty string, max 100,000 characters
- `turn_index`: non-negative integer
- `ts`: valid ISO-8601 timestamp

### 5.2 Memory Item

**Python dataclass:**

```python
@dataclass
class MemoryItem:
    text: str
    memory_type: str  # "preference" | "fact" | "project" | "decision"
    confidence: float  # [0.0, 1.0]
    ts: str  # ISO-8601
    conversation_id: str | None = None
    entities: str | None = None  # comma-separated
    source: str | None = None  # "chat" | "tool" | "import"
    tags: str | None = None  # comma-separated
```

**Validation rules:**
- `text`: non-empty string, max 2,000 characters (summarize if longer)
- `memory_type`: must be one of ["preference", "fact", "project", "decision"]
- `confidence`: float in range [0.0, 1.0]
- `ts`: valid ISO-8601 timestamp

### 5.3 Context Package

**Python dataclass:**

```python
@dataclass
class ContextPackage:
    history: list[HistoryTurn]
    memories: list[tuple[MemoryItem, float]]  # (item, similarity_score)
    latest_message: str
    metadata: dict  # token_counts, truncated flags, etc.
```

---

## 6. Non-Functional Requirements

### 6.1 Performance (NFR-PERF)

**NFR-PERF-001: Latency**
- History append: < 100ms (p95)
- Memory write: < 150ms (p95)
- History retrieval: < 200ms for 16 turns (p95)
- Memory recall: < 500ms for top-8 (p95)

**NFR-PERF-002: Throughput**
- Support at least 10 concurrent conversations
- Handle at least 100 messages/minute aggregate

### 6.2 Reliability (NFR-REL)

**NFR-REL-001: Data Durability**
- No data loss during graceful shutdown
- Data persists across container restarts
- Volume backup capability

**NFR-REL-002: Error Recovery**
- Graceful degradation on subsystem failure
- Automatic reconnection on transient failures
- Detailed error logging for diagnostics

### 6.3 Maintainability (NFR-MAINT)

**NFR-MAINT-001: Code Quality**
- Python type hints throughout
- Docstrings for all public interfaces
- Unit test coverage > 80%
- Integration test for end-to-end flows

**NFR-MAINT-002: Observability**
- Structured logging (JSON format)
- Log levels: DEBUG, INFO, WARN, ERROR
- Key metrics: message_count, memory_count, query_latency
- Health check endpoint

### 6.4 Scalability (NFR-SCALE)

**NFR-SCALE-001: Data Growth**
- Support up to 100,000 history turns per conversation
- Support up to 10,000 memories total
- No performance degradation up to these limits

**NFR-SCALE-002: Future Expansion**
- Clean abstractions for adding more collections
- No hard-coded collection names in business logic
- Configuration-driven behavior

---

## 7. Acceptance Criteria

V1 is considered complete and production-ready when ALL of the following criteria are met:

### 7.1 Deployment Criteria (AC-DEPLOY)

- [ ] **AC-DEPLOY-001**: `docker compose up` starts all three services (chroma, chroma-mcp, agent-app) without errors
- [ ] **AC-DEPLOY-002**: ChromaDB health check passes within 30 seconds
- [ ] **AC-DEPLOY-003**: agent-app successfully bootstraps and creates both collections
- [ ] **AC-DEPLOY-004**: All services restart gracefully with `docker compose restart`

### 7.2 Functional Criteria (AC-FUNC)

- [ ] **AC-FUNC-001**: History storage - every message is appended to history collection
- [ ] **AC-FUNC-002**: History retrieval - last N turns for a conversation_id are retrieved in chronological order
- [ ] **AC-FUNC-003**: Memory storage - agent can store a memory with type and confidence
- [ ] **AC-FUNC-004**: Memory recall - agent can semantically query memory collection and receive relevant results
- [ ] **AC-FUNC-005**: Confidence gating - only memories with confidence >= MEMORY_CONFIDENCE_MIN are stored
- [ ] **AC-FUNC-006**: Rate limiting - no more than MEMORY_MAX_PER_WINDOW memories stored per window
- [ ] **AC-FUNC-007**: Context building - context includes history tail, relevant memories, and latest message

### 7.3 Persistence Criteria (AC-PERS)

- [ ] **AC-PERS-001**: After `docker compose down && docker compose up`, previously stored history is retrievable
- [ ] **AC-PERS-002**: After `docker compose down && docker compose up`, previously stored memories are retrievable
- [ ] **AC-PERS-003**: Volume `chroma_data` contains all persisted data
- [ ] **AC-PERS-004**: No data loss occurs during graceful shutdown

### 7.4 Quality Criteria (AC-QUAL)

- [ ] **AC-QUAL-001**: All public interfaces have type hints and docstrings
- [ ] **AC-QUAL-002**: Unit test coverage >= 80% for memory_gateway.py, context_builder.py, memory_policy.py
- [ ] **AC-QUAL-003**: Integration test covers end-to-end flow (store history + memory, restart, retrieve)
- [ ] **AC-QUAL-004**: No critical or high severity linting errors
- [ ] **AC-QUAL-005**: All error cases have appropriate logging

### 7.5 Configuration Criteria (AC-CONF)

- [ ] **AC-CONF-001**: All environment variables are documented and have sensible defaults
- [ ] **AC-CONF-002**: Changing HISTORY_TAIL_N affects history retrieval count
- [ ] **AC-CONF-003**: Changing MEMORY_TOP_K affects memory recall count
- [ ] **AC-CONF-004**: Changing MEMORY_CONFIDENCE_MIN affects memory storage gating

### 7.6 Documentation Criteria (AC-DOC)

- [ ] **AC-DOC-001**: README.md exists with quickstart instructions
- [ ] **AC-DOC-002**: docker-compose.yml has inline comments explaining each service
- [ ] **AC-DOC-003**: Example payloads documented for history and memory
- [ ] **AC-DOC-004**: Architecture diagram included (ASCII or image)

---

## 8. Explicit Non-Goals (Deferred to V2)

The following features are explicitly OUT OF SCOPE for V1 and should NOT be implemented:

- Multiple memory collections (episodic, semantic, procedural, narrative)
- Automatic promotion pipeline from history to memory
- Deduplication or similarity merging of memories
- Decay, archival, or TTL enforcement
- Re-embedding or embedding version migrations
- Full audit trail with metrics dashboards
- Multi-tenancy with tenant prefixes
- Access control or authentication between services
- History summarization
- Memory update or deletion operations

These may be considered for V2 after V1 is stable and validated.

---

## 9. Testing Strategy

### 9.1 Unit Tests

**memory_gateway_test.py:**
- Test connection initialization
- Test each method with valid inputs
- Test error handling for invalid inputs
- Mock MCP calls to avoid external dependencies

**context_builder_test.py:**
- Test context assembly with mock gateway
- Test token budget truncation
- Test formatting for prompt
- Test degraded context on gateway failure

**memory_policy_test.py:**
- Test should_store with various confidence levels
- Test rate limit enforcement
- Test memory type validation

### 9.2 Integration Tests

**test_end_to_end.py:**
1. Start Docker Compose environment
2. Store several history turns
3. Store several memories
4. Retrieve history and verify order
5. Query memories and verify relevance
6. Restart containers
7. Verify data persists
8. Shutdown cleanly

### 9.3 Manual Testing

**Manual Test Plan:**
1. Start system: `docker compose up`
2. Send 20 messages in a conversation
3. Trigger 5 memory writes with varying confidence
4. Verify history retrieval returns last 16 turns
5. Verify memory recall returns relevant items
6. Restart: `docker compose restart`
7. Repeat retrieval and verify data intact
8. Full teardown: `docker compose down`
9. Restart: `docker compose up`
10. Verify data still intact

---

## 10. Dependencies

### 10.1 External Dependencies

- **ChromaDB**: Vector database (Docker image: chromadb/chroma:latest)
- **chroma-mcp**: MCP gateway (Docker image: ghcr.io/chroma-core/chroma-mcp:latest)
- **Python 3.11+**: Runtime for agent-app
- **Docker & Docker Compose**: Container orchestration

### 10.2 Python Dependencies (requirements.txt)

```
# MCP Client
mcp>=1.0.0

# Utilities
pydantic>=2.5.0
python-dateutil>=2.8.2

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0

# Linting
ruff>=0.1.0
mypy>=1.7.0
```

---

## 11. Deployment Checklist

Before deploying to any environment:

- [ ] All acceptance criteria met
- [ ] Integration tests passing
- [ ] Docker images built and tagged
- [ ] docker-compose.yml configured for target environment
- [ ] Environment variables documented
- [ ] Volume backup strategy defined
- [ ] Rollback procedure documented
- [ ] Monitoring and alerting configured
- [ ] Incident response plan defined

---

## 12. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| ChromaDB volume corruption | Low | High | Regular backups, volume monitoring |
| Memory spam (too many writes) | Medium | Medium | Rate limiting via MEMORY_MAX_PER_WINDOW |
| Context exceeds token budget | Medium | Low | Truncation with priority (latest > history > memories) |
| MCP connection failure | Low | High | Automatic reconnection, graceful degradation |
| Large message causing storage failure | Low | Low | Validate and truncate before storage |
| Concurrent access to same conversation | Medium | Low | ChromaDB handles concurrency |

---

## 13. Success Metrics

V1 success will be measured by:

- **Reliability**: 99.5% uptime over 30 days
- **Data integrity**: Zero data loss incidents
- **Performance**: < 500ms p95 latency for all operations
- **Usability**: Agent can successfully build context for 95% of requests
- **Adoption**: System used in at least 3 production conversations

---

## 14. Timeline Estimate

Estimated implementation timeline (assuming single full-time engineer):

- **Phase 1: Setup** (0.5 days)
  - Docker Compose configuration
  - Bootstrap script

- **Phase 2: Gateway** (1 day)
  - memory_gateway.py implementation
  - Unit tests

- **Phase 3: Context Builder** (1 day)
  - context_builder.py implementation
  - Unit tests

- **Phase 4: Policy** (0.5 days)
  - memory_policy.py implementation
  - Unit tests

- **Phase 5: Integration** (1 day)
  - app.py wiring
  - Integration tests
  - End-to-end testing

- **Phase 6: Documentation** (0.5 days)
  - README, comments, examples

- **Phase 7: Review & Polish** (0.5 days)
  - Code review, linting, final tests

**Total: 5 days**

---

## 15. Appendix A: Example Payloads

### 15.1 History Insert (Logical)

```json
{
  "collection": "history",
  "documents": ["User: I want to store memories in Docker using ChromaDB and MCP."],
  "metadatas": [{
    "conversation_id": "conv_123",
    "role": "user",
    "ts": "2025-12-25T12:10:00+02:00",
    "turn_index": 42
  }]
}
```

### 15.2 Memory Insert (Logical)

```json
{
  "collection": "memory",
  "documents": ["User prefers a Docker-based memory stack using Chroma + MCP."],
  "metadatas": [{
    "type": "preference",
    "confidence": 0.85,
    "ts": "2025-12-25T12:11:00+02:00",
    "conversation_id": "conv_123"
  }]
}
```

### 15.3 Memory Query (Logical)

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

### 15.4 History Retrieval (Logical)

```json
{
  "collection": "history",
  "where": {
    "conversation_id": "conv_123"
  },
  "limit": 16,
  "sort": [{"field": "turn_index", "order": "desc"}]
}
```

---

## 16. Appendix B: Future Considerations (V2+)

When V1 is stable, consider these enhancements:

### 16.1 Multi-Collection Memory
- Split `memory` into: `mem_episodic`, `mem_semantic`, `mem_procedural`, `mem_narrative`
- Add `MemoryRouter` to map memory type to collection

### 16.2 History Summarization
- Add `history_summaries` collection
- Periodic summarization job
- Use summaries for context when tail exceeds budget

### 16.3 Promotion Pipeline
- Automatically promote high-quality history turns to memory
- Confidence scoring on history items
- Deduplication before promotion

### 16.4 Decay and Archival
- TTL-based decay for old memories
- Archive collection for low-relevance items
- Re-ranking based on access patterns

### 16.5 Enhanced Metadata
- Entity extraction and linking
- Automatic tagging using LLM
- Confidence adjustment based on validation

### 16.6 Observability
- Prometheus metrics export
- Grafana dashboards
- Distributed tracing with OpenTelemetry

---

**End of Specification**

---

**Approval Required From:**
- [ ] Senior Architect (architecture review)
- [ ] Lead Backend Engineer (implementation feasibility)
- [ ] Test Automation Engineer (testability review)
- [ ] Security Engineer (security review)
- [ ] Chief of Staff (user proxy approval)
