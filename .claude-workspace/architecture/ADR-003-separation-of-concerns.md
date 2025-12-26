# ADR-003: Separation of Concerns (Gateway/Builder/Policy)

**Status:** Accepted

**Date:** 2025-12-25

**Context:**

The agent-app needs to coordinate multiple responsibilities:
- Communicating with the vector store via MCP
- Assembling context from history and memories
- Deciding what to store and when (memory policy)
- Managing conversation state
- Formatting data for LLM consumption

We need to decide how to organize this code to maintain clarity, testability, and evolvability as the system grows from V1 to V2+.

Architecture philosophies considered:
1. **Layered architecture** - Separate gateway/service/policy layers
2. **Monolithic** - Single large module handling everything
3. **Microservices** - Split into separate deployable services
4. **Hexagonal (Ports & Adapters)** - Domain core with adapter boundaries
5. **Event-driven** - Async message passing between components

**Decision:**

We will implement a **three-layer separation of concerns** within agent-app:

```
┌─────────────────────────────────────────┐
│          app.py (orchestration)         │
└─────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   memory_    │ │   context_   │ │   memory_    │
│   gateway    │ │   builder    │ │   policy     │
└──────────────┘ └──────────────┘ └──────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│         chroma-mcp (MCP gateway)         │
└──────────────────────────────────────────┘
```

**Layer responsibilities:**

1. **memory_gateway.py** (Transport Layer)
   - All MCP communication lives here
   - Translates between domain objects and MCP payloads
   - Handles connection management and retries
   - **No business logic** - pure transport
   - Maps errors to domain exceptions

2. **context_builder.py** (Assembly Layer)
   - Retrieves data via gateway
   - Assembles context from multiple sources
   - Handles token budget and truncation
   - Formats context for LLM prompt
   - **No storage decisions** - pure assembly

3. **memory_policy.py** (Policy Layer)
   - Decides what to store (confidence threshold)
   - Enforces rate limits (max per window)
   - Validates memory types
   - **No I/O operations** - pure logic

4. **app.py** (Orchestration Layer)
   - Wires together gateway, builder, policy
   - Implements message handling flow
   - Manages conversation state
   - Coordinates across layers

**Decision criteria:**

This approach provides:
- **Single Responsibility Principle**: Each module has one clear job
- **Testability**: Layers can be unit tested in isolation with mocks
- **Evolvability**: Can swap implementations without cascading changes
- **Clarity**: Clear boundaries make code review easier
- **Debugging**: Logs can be scoped to specific layers

**Consequences:**

**Positive:**
- **Maintainability**: Easy to locate and modify specific behaviors
- **Testing**: Gateway tested with MCP mocks, builder tested with gateway mocks, policy tested with pure logic
- **Future expansion**: Can add VectorStore abstraction layer without touching business logic
- **Code review**: Reviewers can focus on specific concerns
- **Onboarding**: New developers can understand system layer by layer
- **Flexibility**: Can swap gateway implementation (e.g., different vector store) without changing policy or builder

**Negative:**
- **More files**: 4 modules instead of 1 monolithic file
- **Indirection**: Following data flow requires understanding layer boundaries
- **Over-engineering risk**: V1 is small enough that layers might feel excessive
- **Coordination overhead**: Changes affecting multiple layers require coordination

**Interface contracts:**

Each layer exposes a minimal interface:

```python
# memory_gateway.py
class MemoryGateway:
    def append_history(...) -> str
    def tail_history(...) -> list[dict]
    def write_memory(...) -> str
    def recall_memory(...) -> list[dict]

# context_builder.py
class ContextBuilder:
    def build_context(...) -> dict
    def format_for_prompt(...) -> str

# memory_policy.py
class MemoryPolicy:
    def should_store(...) -> bool
    def enforce_rate_limit(...) -> bool
```

**V2 expansion path:**

This structure enables clean V2 additions:

1. **Add VectorStore abstraction**:
   - Create `ports/vector_store.py` interface
   - Gateway becomes adapter implementing interface
   - Services depend on port, not gateway directly

2. **Add HistoryStore abstraction**:
   - Separate history storage from memory storage
   - Could move history to PostgreSQL while keeping memory in ChromaDB

3. **Add MemoryRouter**:
   - Maps memory types to collections (episodic, semantic, procedural, narrative)
   - Policy delegates routing decisions

4. **Add Summarizer**:
   - New module for history summarization
   - Builder can use summaries when history tail exceeds budget

**Alternatives rejected:**

1. **Monolithic approach**: Rejected because it creates tight coupling, makes testing difficult, and doesn't scale to V2 complexity.

2. **Microservices**: Rejected as over-engineering. Network boundaries between these components would add latency and operational complexity without benefit at V1 scale.

3. **Hexagonal architecture**: Considered but deemed too heavy for V1. The gateway layer provides sufficient decoupling without full port/adapter formalization.

4. **Event-driven**: Rejected because V1 flows are synchronous and sequential. Async messaging would add complexity without performance benefit.

**Dependency direction:**

```
app.py → context_builder.py → memory_gateway.py → MCP
      → memory_policy.py
```

Dependencies flow inward/downward only. Lower layers have no knowledge of upper layers.

**Code organization principles:**
- **No circular dependencies**: Layers never import upward
- **Minimal coupling**: Layers communicate via explicit interfaces
- **High cohesion**: Related functions stay together in same module
- **Dependency injection**: Layers receive dependencies via constructors
- **Stateless where possible**: Gateway and policy are stateless

**Related decisions:**
- ADR-001: Docker-First Deployment
- ADR-002: ChromaDB as Vector Store

**Review date:** After V1 implementation complete, assess if boundaries were helpful or burdensome
