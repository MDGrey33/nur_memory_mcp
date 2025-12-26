# ADR-004: Module Structure and Service Layer

**Status:** Accepted
**Date:** 2025-12-25
**Author:** Senior Architect
**Relates to:** v2.0 Code Organization

---

## Context

### Current State (v1)

The v1 implementation uses a **monolithic server file** (`server.py`, 356 lines):

```
server.py
├── Imports and configuration
├── ChromaDB client management
├── 6 tool functions (memory_store, memory_search, etc.)
├── Session manager setup
├── Health endpoint
└── Uvicorn startup
```

**Issues with v1 structure:**

1. **Poor separation of concerns**: Business logic mixed with MCP protocol handling
2. **Tight coupling**: ChromaDB calls embedded in tool functions
3. **Hard to test**: Cannot test business logic without mocking MCP framework
4. **No reusability**: Logic cannot be reused outside MCP context
5. **Limited extensibility**: Adding new services (embedding, chunking, retrieval) would bloat file

### Requirements for v2

v2.0 introduces significant complexity:

- **3 new services**: EmbeddingService, ChunkingService, RetrievalService
- **8 new tools**: artifact_ingest, artifact_search, artifact_get, artifact_delete, hybrid_search, embedding_health, + updates to 6 existing tools
- **4 collections**: memory, history, artifacts, artifact_chunks
- **Complex workflows**: Two-phase atomic writes, RRF merging, deduplication
- **Observability**: Structured logging, metrics, health checks

**Goals:**

1. **Maintainability**: Clear module boundaries, easy to navigate
2. **Testability**: Each component testable in isolation
3. **Extensibility**: Easy to add new services/tools
4. **Reusability**: Services usable outside MCP context (e.g., CLI tools)
5. **Type safety**: Full type hints for IDE support

---

## Decision

We will adopt a **layered architecture** with clear separation:

```
mcp-server/
├── src/
│   ├── __init__.py
│   ├── server.py                  # MCP server, tool definitions, startup
│   ├── config.py                  # Configuration management
│   ├── services/
│   │   ├── __init__.py
│   │   ├── embedding_service.py   # OpenAI embedding generation
│   │   ├── chunking_service.py    # Token-window chunking
│   │   ├── retrieval_service.py   # RRF hybrid search
│   │   └── privacy_service.py     # Privacy filter (placeholder)
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── chroma_client.py       # ChromaDB client wrapper
│   │   ├── collections.py         # Collection schemas and helpers
│   │   └── models.py              # Data models (Chunk, SearchResult, etc.)
│   └── utils/
│       ├── __init__.py
│       ├── logging.py             # Structured logging setup
│       ├── errors.py              # Custom exception classes
│       └── validators.py          # Input validation helpers
├── tests/
│   ├── unit/
│   │   ├── test_embedding_service.py
│   │   ├── test_chunking_service.py
│   │   ├── test_retrieval_service.py
│   │   └── ...
│   ├── integration/
│   │   ├── test_artifact_ingestion.py
│   │   ├── test_hybrid_search.py
│   │   └── ...
│   └── fixtures/
│       ├── test_documents.py
│       └── mock_services.py
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

### Layer Responsibilities

#### Layer 1: Server Layer (`server.py`)

**Responsibilities:**
- MCP protocol handling (FastMCP, session management)
- Tool definitions (parameter validation, response formatting)
- HTTP endpoints (health, MCP mount)
- Application lifecycle (startup, shutdown)

**Does NOT:**
- Generate embeddings
- Chunk text
- Execute searches
- Access ChromaDB directly

**Example:**
```python
# server.py
from mcp.server.fastmcp import FastMCP
from services import EmbeddingService, ChunkingService, RetrievalService
from storage import get_chroma_client

mcp = FastMCP("MCP Memory")

# Services initialized at startup
embedding_service: EmbeddingService
chunking_service: ChunkingService
retrieval_service: RetrievalService

@mcp.tool()
def artifact_ingest(
    artifact_type: str,
    source_system: str,
    content: str,
    ...
) -> dict:
    """Ingest artifact with automatic chunking."""
    try:
        # Validate inputs
        validate_artifact_type(artifact_type)
        validate_content_length(content)

        # Delegate to service layer
        result = _ingest_artifact(
            artifact_type=artifact_type,
            source_system=source_system,
            content=content,
            ...
        )

        return result

    except ValidationError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"artifact_ingest failed: {e}")
        return {"error": "Internal server error"}
```

#### Layer 2: Service Layer (`services/`)

**Responsibilities:**
- Business logic (chunking decisions, RRF merging, deduplication)
- External API calls (OpenAI embeddings)
- Complex workflows (two-phase writes, neighbor expansion)
- Retry logic and error handling

**Does NOT:**
- Handle HTTP requests
- Format MCP responses
- Manage application lifecycle

**Example:**
```python
# services/embedding_service.py
class EmbeddingService:
    """OpenAI embedding generation with retry logic."""

    def __init__(self, api_key: str, model: str, dimensions: int, ...):
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.dimensions = dimensions
        # ...

    def generate_embedding(self, text: str) -> list[float]:
        """Generate single embedding with retry."""
        return self._call_with_retry(
            self.client.embeddings.create,
            input=[text],
            model=self.model,
            dimensions=self.dimensions
        )

    def _call_with_retry(self, func, *args, **kwargs):
        """Exponential backoff retry logic."""
        # ... (see ADR-001)
```

#### Layer 3: Storage Layer (`storage/`)

**Responsibilities:**
- ChromaDB client management (connection, health checks)
- Collection operations (get_or_create, add, query, delete)
- Schema definitions (metadata fields, indexes)
- Data models (Chunk, SearchResult, MergedResult)

**Does NOT:**
- Business logic (no chunking, merging, etc.)
- External API calls (no OpenAI)
- Request handling

**Example:**
```python
# storage/chroma_client.py
import chromadb

class ChromaClientManager:
    """Manage ChromaDB client lifecycle."""

    def __init__(self, host: str, port: int):
        self._client = None
        self.host = host
        self.port = port

    def get_client(self) -> chromadb.HttpClient:
        """Get or create ChromaDB client."""
        if self._client is None:
            self._client = chromadb.HttpClient(
                host=self.host,
                port=self.port
            )
        return self._client

    def health_check(self) -> dict:
        """Check ChromaDB connectivity."""
        try:
            client = self.get_client()
            client.heartbeat()
            return {"status": "healthy"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# storage/collections.py
def get_memory_collection(client: chromadb.HttpClient):
    """Get or create memory collection."""
    return client.get_or_create_collection(
        name="memory",
        metadata={
            "description": "Durable semantic memories",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072
        }
    )


# storage/models.py
from dataclasses import dataclass

@dataclass
class Chunk:
    """Data model for artifact chunk."""
    chunk_id: str
    artifact_id: str
    chunk_index: int
    content: str
    start_char: int
    end_char: int
    token_count: int
    content_hash: str
```

#### Layer 4: Utilities (`utils/`)

**Responsibilities:**
- Structured logging configuration
- Custom exception classes
- Input validation helpers
- Common utilities (hashing, timestamps, etc.)

**Example:**
```python
# utils/errors.py
class MCPMemoryError(Exception):
    """Base exception for MCP Memory errors."""
    pass

class ValidationError(MCPMemoryError):
    """Invalid input error."""
    pass

class EmbeddingError(MCPMemoryError):
    """Embedding generation failed."""
    pass

class ConfigurationError(MCPMemoryError):
    """Invalid configuration."""
    pass


# utils/validators.py
def validate_artifact_type(artifact_type: str) -> None:
    """Validate artifact type enum."""
    valid_types = ["email", "doc", "chat", "transcript", "note"]
    if artifact_type not in valid_types:
        raise ValidationError(
            f"Invalid artifact_type: {artifact_type}. "
            f"Must be one of: {', '.join(valid_types)}"
        )


# utils/logging.py
import logging
import json

class StructuredLogger(logging.Logger):
    """Logger with structured JSON output."""

    def info(self, event: str, extra: dict = None):
        """Log info event with structured data."""
        log_data = {
            "event": event,
            "level": "INFO",
            **(extra or {})
        }
        super().info(json.dumps(log_data))
```

---

## Key Design Patterns

### 1. Dependency Injection

Services receive dependencies via constructor (not globals):

```python
# Good: Dependencies injected
class RetrievalService:
    def __init__(
        self,
        embedding_service: EmbeddingService,
        chroma_client: chromadb.HttpClient,
        k: int = 60
    ):
        self.embedding_service = embedding_service
        self.chroma_client = chroma_client
        self.k = k

# Bad: Global dependencies
class RetrievalService:
    def hybrid_search(self, query: str):
        embedding = global_embedding_service.generate_embedding(query)  # No!
```

**Benefits:**
- Testable (inject mocks)
- Flexible (swap implementations)
- Clear dependencies

### 2. Service Initialization at Startup

Services created once during application lifespan:

```python
# server.py
@asynccontextmanager
async def lifespan(app):
    """Application lifecycle."""
    global embedding_service, chunking_service, retrieval_service

    # Load configuration
    config = load_config()

    # Initialize services
    embedding_service = EmbeddingService(
        api_key=config.openai_api_key,
        model=config.openai_embed_model,
        dimensions=config.openai_embed_dims,
        timeout=config.openai_timeout,
        max_retries=config.openai_max_retries,
        batch_size=config.openai_batch_size
    )

    chunking_service = ChunkingService(
        single_piece_max=config.single_piece_max_tokens,
        chunk_target=config.chunk_target_tokens,
        chunk_overlap=config.chunk_overlap_tokens
    )

    chroma_client = get_chroma_client(
        host=config.chroma_host,
        port=config.chroma_port
    )

    retrieval_service = RetrievalService(
        embedding_service=embedding_service,
        chroma_client=chroma_client,
        k=config.rrf_constant
    )

    # Health checks
    health = embedding_service.health_check()
    if health["status"] != "healthy":
        raise RuntimeError(f"Embedding service unhealthy: {health}")

    logger.info("All services initialized successfully")
    yield

    logger.info("Shutting down services")
```

### 3. Two-Phase Atomic Writes

Separate data preparation from storage:

```python
def _ingest_artifact_chunked(artifact_id: str, chunks: list[Chunk], metadata: dict):
    """Ingest chunked artifact with two-phase write."""

    # PHASE 1: Generate ALL embeddings first (fail fast if error)
    embeddings = []
    for chunk in chunks:
        try:
            emb = embedding_service.generate_embedding(chunk.content)
            embeddings.append(emb)
        except EmbeddingError as e:
            # Fail fast - don't write anything
            logger.error(
                "two_phase_write_aborted",
                extra={
                    "artifact_id": artifact_id,
                    "chunk_index": chunk.chunk_index,
                    "error": str(e)
                }
            )
            raise EmbeddingError(
                f"Embedding generation failed for chunk {chunk.chunk_index}: {e}"
            )

    # PHASE 2: Write to DB (only if ALL embeddings succeeded)
    artifacts_collection = get_artifacts_collection(chroma_client)
    artifact_chunks_collection = get_artifact_chunks_collection(chroma_client)

    # Store artifact metadata
    artifacts_collection.add(
        ids=[artifact_id],
        documents=[""],
        metadatas=[metadata]
    )

    # Store all chunks
    chunk_ids = []
    for chunk, embedding in zip(chunks, embeddings):
        artifact_chunks_collection.add(
            ids=[chunk.chunk_id],
            documents=[chunk.content],
            embeddings=[embedding],
            metadatas=[{
                "artifact_id": artifact_id,
                "chunk_index": chunk.chunk_index,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "token_count": chunk.token_count,
                "content_hash": chunk.content_hash,
                ...
            }]
        )
        chunk_ids.append(chunk.chunk_id)

    return {
        "artifact_id": artifact_id,
        "is_chunked": True,
        "num_chunks": len(chunks),
        "stored_ids": [artifact_id] + chunk_ids
    }
```

### 4. Error Handling Hierarchy

```python
# Tool layer: Catch all, return user-friendly message
@mcp.tool()
def artifact_ingest(...) -> dict:
    try:
        result = _ingest_artifact(...)
        return result
    except ValidationError as e:
        return {"error": f"Invalid input: {e}"}
    except EmbeddingError as e:
        return {"error": f"Embedding generation failed: {e}"}
    except StorageError as e:
        return {"error": f"Storage failed: {e}"}
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {"error": "Internal server error"}


# Service layer: Raise specific exceptions
class EmbeddingService:
    def generate_embedding(self, text: str) -> list[float]:
        try:
            response = self.client.embeddings.create(...)
            return response.data[0].embedding
        except openai.AuthenticationError as e:
            raise ConfigurationError("Invalid OpenAI API key") from e
        except openai.RateLimitError as e:
            # Retry logic...
            raise EmbeddingError("Rate limit exceeded after retries") from e
```

---

## File Structure Details

### `src/server.py` (~300 lines)

```python
"""MCP Memory Server v2.0 - Streamable HTTP Transport."""

import os
import logging
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from config import load_config
from services import EmbeddingService, ChunkingService, RetrievalService, PrivacyService
from storage import get_chroma_client, get_memory_collection, get_artifacts_collection
from utils import setup_logging, ValidationError, EmbeddingError

# Setup logging
logger = setup_logging()

# Create FastMCP server
mcp = FastMCP("MCP Memory v2")

# Global services (initialized in lifespan)
embedding_service: EmbeddingService = None
chunking_service: ChunkingService = None
retrieval_service: RetrievalService = None
privacy_service: PrivacyService = None
chroma_client = None


# Tool definitions
@mcp.tool()
def memory_store(...) -> str:
    """Store a memory for long-term recall."""
    # ...

@mcp.tool()
def memory_search(...) -> str:
    """Search memories using semantic similarity."""
    # ...

# ... (10 more tools)


# Application lifecycle
@asynccontextmanager
async def lifespan(app):
    """Application startup and shutdown."""
    global embedding_service, chunking_service, retrieval_service, chroma_client

    logger.info("Starting MCP Memory Server v2.0")

    # Load configuration
    config = load_config()

    # Initialize services
    # ... (see pattern above)

    yield

    logger.info("MCP Memory Server stopped")


# Health endpoint
async def health(request):
    return JSONResponse({"status": "ok", "version": "2.0.0"})


# Starlette app
app = Starlette(
    debug=os.getenv("LOG_LEVEL") == "DEBUG",
    routes=[
        Route("/health", health),
        Mount("/mcp", app=MCPHandler()),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    config = load_config()
    uvicorn.run(app, host="0.0.0.0", port=config.mcp_port)
```

### `src/config.py` (~100 lines)

```python
"""Configuration management."""

import os
from dataclasses import dataclass

@dataclass
class Config:
    """Application configuration."""

    # OpenAI
    openai_api_key: str
    openai_embed_model: str
    openai_embed_dims: int
    openai_timeout: int
    openai_max_retries: int
    openai_batch_size: int

    # Chunking
    single_piece_max_tokens: int
    chunk_target_tokens: int
    chunk_overlap_tokens: int

    # ChromaDB
    chroma_host: str
    chroma_port: int

    # Server
    mcp_port: int
    log_level: str

    # RRF
    rrf_constant: int


def load_config() -> Config:
    """Load configuration from environment variables."""
    return Config(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_embed_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-large"),
        openai_embed_dims=int(os.getenv("OPENAI_EMBED_DIMS", "3072")),
        openai_timeout=int(os.getenv("OPENAI_TIMEOUT", "30")),
        openai_max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "3")),
        openai_batch_size=int(os.getenv("OPENAI_BATCH_SIZE", "100")),

        single_piece_max_tokens=int(os.getenv("SINGLE_PIECE_MAX_TOKENS", "1200")),
        chunk_target_tokens=int(os.getenv("CHUNK_TARGET_TOKENS", "900")),
        chunk_overlap_tokens=int(os.getenv("CHUNK_OVERLAP_TOKENS", "100")),

        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8001")),

        mcp_port=int(os.getenv("MCP_PORT", "3000")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),

        rrf_constant=int(os.getenv("RRF_CONSTANT", "60")),
    )
```

### `src/services/embedding_service.py` (~200 lines)

See ADR-001 for full implementation.

### `src/services/chunking_service.py` (~250 lines)

See ADR-002 for full implementation.

### `src/services/retrieval_service.py` (~400 lines)

See ADR-003 for full implementation.

### `src/storage/models.py` (~150 lines)

```python
"""Data models for MCP Memory."""

from dataclasses import dataclass
from typing import Optional

@dataclass
class Chunk:
    """Artifact chunk."""
    chunk_id: str
    artifact_id: str
    chunk_index: int
    content: str
    start_char: int
    end_char: int
    token_count: int
    content_hash: str


@dataclass
class SearchResult:
    """Single search result."""
    id: str
    content: str
    metadata: dict
    collection: str
    rank: int
    distance: float
    is_chunk: bool
    artifact_id: Optional[str] = None


@dataclass
class MergedResult:
    """RRF-merged result."""
    result: SearchResult
    rrf_score: float
    collections: list[str]
```

---

## Consequences

### Positive

1. **Maintainability**: Clear module boundaries, easy to find code
2. **Testability**: Each layer testable in isolation
3. **Extensibility**: Add new services without touching existing code
4. **Reusability**: Services usable in CLI, notebooks, other contexts
5. **Type Safety**: Full type hints enable IDE autocomplete, static analysis
6. **Scalability**: Easy to extract services to microservices if needed

### Negative

1. **Boilerplate**: More files and imports than monolithic approach
2. **Indirection**: More layers to navigate (server → service → storage)
3. **Learning Curve**: New developers must understand architecture
4. **Initial Complexity**: Takes longer to set up than single file

### Trade-offs

| Aspect | Monolithic (v1) | Layered (v2) |
|--------|-----------------|--------------|
| Lines of code | 356 (1 file) | ~2000 (15 files) |
| Time to first feature | Fast | Moderate |
| Time to 10th feature | Slow (spaghetti) | Fast (clear structure) |
| Testability | Hard (mock MCP) | Easy (unit tests) |
| Onboarding | Fast (one file) | Moderate (architecture doc) |

---

## Implementation Notes

### Migration from v1 to v2

1. **Extract services** from v1 tools:
   - Embedding calls → `EmbeddingService`
   - ChromaDB calls → `storage/` layer

2. **Preserve v1 tool signatures**:
   - Same parameters, same return format
   - Just delegate to service layer

3. **Add new tools** using same pattern:
   ```python
   @mcp.tool()
   def new_tool(...):
       try:
           result = service.do_work(...)
           return format_response(result)
       except Exception as e:
           return error_response(e)
   ```

### Testing Strategy

1. **Unit Tests** (no external dependencies):
   ```python
   def test_chunking_service():
       service = ChunkingService(
           single_piece_max=1200,
           chunk_target=900,
           chunk_overlap=100
       )
       should_chunk, token_count = service.should_chunk("short text")
       assert not should_chunk
   ```

2. **Integration Tests** (real ChromaDB, OpenAI):
   ```python
   def test_artifact_ingestion():
       # Real services
       result = artifact_ingest(
           artifact_type="doc",
           source_system="test",
           content=long_document
       )
       assert result["is_chunked"] == True
   ```

3. **Tool Tests** (mock services):
   ```python
   def test_memory_store_tool():
       # Mock embedding service
       with patch('server.embedding_service') as mock_embedding:
           mock_embedding.generate_embedding.return_value = [0.1] * 3072
           result = memory_store("test", "fact", 1.0)
           assert "Stored memory" in result
   ```

---

## Alternatives Considered

### Alternative 1: Keep Monolithic Structure

**Pros:**
- Simpler for small codebase
- Faster initial development

**Cons:**
- Becomes unmaintainable at scale
- Hard to test
- Poor separation of concerns

**Decision:** Rejected - v2 complexity justifies layered architecture

### Alternative 2: Microservices Architecture

**Description:** Separate services into independent deployments (embedding service, chunking service, etc.)

**Pros:**
- Independent scaling
- Language flexibility
- Fault isolation

**Cons:**
- Complex deployment (Kubernetes, service mesh)
- Network latency between services
- Distributed tracing complexity
- Overkill for single-user MCP server

**Decision:** Rejected - premature for current scale

### Alternative 3: Hexagonal Architecture (Ports & Adapters)

**Description:** Define ports (interfaces) for all external dependencies, implement adapters

**Pros:**
- Maximum testability
- Easy to swap implementations
- Very clean separation

**Cons:**
- High boilerplate (interface + implementation for everything)
- Overkill for Python (duck typing)

**Decision:** Rejected - layered architecture is sufficient, less boilerplate

---

## References

- [Clean Architecture (Robert Martin)](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Layered Architecture Pattern](https://www.oreilly.com/library/view/software-architecture-patterns/9781491971437/ch01.html)
- Technical Specification: Sections 2.1 (High-Level Architecture), 5.0 (Service Layer)

---

## Approval

**Approved by:** Senior Architect
**Date:** 2025-12-25
**Status:** Ready for Implementation

**Next Steps:**
1. Create directory structure
2. Implement service layer (EmbeddingService, ChunkingService, RetrievalService)
3. Update server.py with layered architecture
4. Write unit tests for each service
5. Integration testing
