# MCP Memory Server V2.0: Complete Architecture Document

## Overview

MCP Memory Server is a Model Context Protocol (MCP) server providing persistent memory, conversation history, and document artifact management with semantic search capabilities.

---

## System Architecture

### High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           CLIENT LAYER                                    │
├────────────────┬────────────────┬────────────────┬───────────────────────┤
│  Claude Code   │  Claude Desktop│   Cursor IDE   │    Other MCP Clients  │
│    (CLI)       │    (App)       │                │                       │
└───────┬────────┴───────┬────────┴───────┬────────┴──────────┬────────────┘
        │                │                │                   │
        ▼                ▼                ▼                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       MCP TRANSPORT LAYER                                 │
│                    Streamable HTTP (localhost:3001)                       │
│                    + ngrok tunnel for HTTPS access                        │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         MCP SERVER (FastMCP)                              │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                         TOOL LAYER (12 tools)                        │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                 │ │
│  │  │ Memory Tools │ │ History Tools│ │Artifact Tools│                 │ │
│  │  │ - store      │ │ - append     │ │ - ingest     │                 │ │
│  │  │ - search     │ │ - get        │ │ - search     │                 │ │
│  │  │ - list       │ │              │ │ - get        │                 │ │
│  │  │ - delete     │ │              │ │ - delete     │                 │ │
│  │  └──────────────┘ └──────────────┘ └──────┬───────┘                 │ │
│  │                                           │                          │ │
│  │  ┌──────────────┐ ┌──────────────┐        │                          │ │
│  │  │Hybrid Search │ │Embed Health  │        │                          │ │
│  │  │ (RRF-based)  │ │ (monitoring) │        │                          │ │
│  │  └──────────────┘ └──────────────┘        │                          │ │
│  └───────────────────────────────────────────┼──────────────────────────┘ │
│                                              │                            │
│  ┌───────────────────────────────────────────┼──────────────────────────┐ │
│  │                    SERVICE LAYER          │                          │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────┴───────┐ ┌─────────────┐ │ │
│  │  │  Embedding   │ │   Chunking   │ │  Retrieval   │ │   Privacy   │ │ │
│  │  │   Service    │ │   Service    │ │   Service    │ │   Service   │ │ │
│  │  │  (OpenAI)    │ │  (tiktoken)  │ │   (RRF)      │ │  (future)   │ │ │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └─────────────┘ │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                    STORAGE LAYER                                      │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │ │
│  │  │                ChromaDB HTTP Client                              │ │ │
│  │  │  ┌─────────────┐ ┌─────────────┐ ┌───────────┐ ┌──────────────┐ │ │ │
│  │  │  │   memory    │ │   history   │ │ artifacts │ │artifact_chunks│ │ │ │
│  │  │  │ collection  │ │ collection  │ │ collection│ │  collection  │ │ │ │
│  │  │  └─────────────┘ └─────────────┘ └───────────┘ └──────────────┘ │ │ │
│  │  └─────────────────────────────────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      EXTERNAL SERVICES                                    │
│  ┌─────────────────────────┐  ┌─────────────────────────────────────────┐│
│  │      ChromaDB Server    │  │           OpenAI API                     ││
│  │    (localhost:8100)     │  │    (text-embedding-3-large)              ││
│  │    - Vector storage     │  │    - 3072-dim embeddings                 ││
│  │    - Similarity search  │  │    - Batch processing                    ││
│  │    - Metadata filtering │  │    - Rate limit handling                 ││
│  └─────────────────────────┘  └─────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. MCP Server (FastMCP)

**File**: `src/server.py`

The main entry point using FastMCP framework for Streamable HTTP transport.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("MCP Memory v2.0")

# Server startup
if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=3000)
```

**Configuration**: `src/config.py`
```python
class Config:
    # ChromaDB
    chroma_host: str = os.getenv("CHROMA_HOST", "localhost")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8100"))

    # OpenAI Embeddings
    openai_api_key: str = os.getenv("OPENAI_API_KEY")
    openai_embed_model: str = "text-embedding-3-large"
    openai_embed_dims: int = 3072
    openai_timeout: float = 30.0

    # Chunking
    chunk_threshold: int = 1200  # tokens
    chunk_target: int = 900      # tokens
    chunk_overlap: int = 100     # tokens
```

---

### 2. Tool Layer

#### Memory Tools

| Tool | Arguments | Returns | Description |
|------|-----------|---------|-------------|
| `memory_store` | `content`, `type`, `confidence`, `conversation_id?` | `mem_{id}` | Store semantic memory |
| `memory_search` | `query`, `limit?`, `type?` | Results list | Vector search memories |
| `memory_list` | `type?`, `limit?` | Memory list | List all memories |
| `memory_delete` | `memory_id` | Confirmation | Delete by ID |

**Memory Types**: `preference`, `fact`, `project`, `decision`

#### History Tools

| Tool | Arguments | Returns | Description |
|------|-----------|---------|-------------|
| `history_append` | `conversation_id`, `role`, `content`, `turn_index` | Confirmation | Add conversation turn |
| `history_get` | `conversation_id`, `limit?` | Turn list | Retrieve history |

**Roles**: `user`, `assistant`, `system`

#### Artifact Tools

| Tool | Arguments | Returns | Description |
|------|-----------|---------|-------------|
| `artifact_ingest` | `artifact_type`, `source_system`, `content`, `title?`, `author?`, ... | `{artifact_id, is_chunked, num_chunks}` | Ingest document |
| `artifact_search` | `query`, `limit?`, `type?` | Results list | Search artifacts |
| `artifact_get` | `artifact_id`, `expand_chunks?` | Full artifact | Retrieve by ID |
| `artifact_delete` | `artifact_id` | Confirmation | Delete with cascade |

**Artifact Types**: `email`, `doc`, `chat`, `transcript`, `note`

#### Cross-Cutting Tools

| Tool | Arguments | Returns | Description |
|------|-----------|---------|-------------|
| `hybrid_search` | `query`, `limit?`, `include_memory?`, `expand_neighbors?` | RRF results | Multi-collection search |
| `embedding_health` | (none) | Status object | Check OpenAI API health |

---

### 3. Service Layer

#### Embedding Service
**File**: `src/services/embedding_service.py`

Manages OpenAI API integration for generating text embeddings.

```python
class EmbeddingService:
    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-large",
        dimensions: int = 3072,
        timeout: float = 30.0
    )

    def generate_embedding(self, text: str) -> List[float]
    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]
    def health_check(self) -> dict
```

**Features**:
- Exponential backoff for rate limits (429)
- Timeout handling with configurable duration
- Batch processing for efficiency
- Health check endpoint

**Error Handling**:
```python
class EmbeddingError(Exception):
    """Raised when embedding generation fails."""
    pass
```

#### Chunking Service
**File**: `src/services/chunking_service.py`

Implements token-window chunking for large documents.

```python
class ChunkingService:
    def __init__(
        self,
        single_piece_max: int = 1200,  # Chunk threshold
        chunk_target: int = 900,        # Target chunk size
        chunk_overlap: int = 100        # Overlap tokens
    )

    def should_chunk(self, text: str) -> Tuple[bool, int]
    def chunk_text(self, text: str, artifact_id: str) -> List[Chunk]
    def expand_chunk_neighbors(self, artifact_id, chunk_index, all_chunks) -> str
    def count_tokens(self, text: str) -> int
```

**Chunking Algorithm**:
1. Count tokens using `tiktoken` (cl100k_base encoding)
2. If tokens > 1200: chunk required
3. Sliding window: 900 tokens with 100 token overlap
4. Generate stable chunk IDs: `{artifact_id}::chunk::{index:03d}::{hash[:8]}`

#### Retrieval Service
**File**: `src/services/retrieval_service.py`

Implements RRF-based hybrid search across collections.

```python
class RetrievalService:
    def __init__(
        self,
        embedding_service: EmbeddingService,
        chunking_service: ChunkingService,
        chroma_client: HttpClient,
        k: int = 60  # RRF constant
    )

    def merge_results_rrf(self, results_by_collection, limit) -> List[MergedResult]
    def deduplicate_by_artifact(self, results) -> List[MergedResult]
    def hybrid_search(self, query, limit, include_memory, expand_neighbors, filters) -> List[MergedResult]
```

**RRF Algorithm**:
```python
# For each result at rank r in collection c:
rrf_score = 1.0 / (k + r + 1)  # k=60 is standard

# Aggregate scores across collections for same item
total_score = sum(rrf_scores_from_all_collections)

# Sort by total_score descending
```

#### Privacy Service
**File**: `src/services/privacy_service.py`

Placeholder for future privacy enforcement (V3).

Currently stores metadata:
- `sensitivity`: normal, sensitive, highly_sensitive
- `visibility_scope`: me, team, org, custom
- `retention_policy`: forever, 1y, until_resolved, custom

---

### 4. Storage Layer

#### ChromaDB Client Manager
**File**: `src/storage/chroma_client.py`

Manages ChromaDB HTTP connection.

```python
class ChromaManager:
    def __init__(self, host: str = "localhost", port: int = 8100):
        self.client = HttpClient(host=host, port=port)

    def get_client(self) -> HttpClient
    def health_check(self) -> dict
```

#### Collection Definitions
**File**: `src/storage/collections.py`

```python
# Collection getters with schema metadata
def get_memory_collection(client) -> Collection
def get_history_collection(client) -> Collection
def get_artifacts_collection(client) -> Collection
def get_artifact_chunks_collection(client) -> Collection

# Utility functions
def get_chunks_by_artifact(client, artifact_id) -> List[Dict]
def get_artifact_by_source(client, source_system, source_id) -> Optional[Dict]
def delete_artifact_cascade(client, artifact_id) -> int
```

**Collection Configuration**:
```python
# All collections use:
embedding_function=None  # We provide our own embeddings
metadata={
    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072
}
```

#### Data Models
**File**: `src/storage/models.py`

```python
@dataclass
class Chunk:
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
    id: str
    content: str
    metadata: Dict
    collection: str
    rank: int
    distance: float
    is_chunk: bool
    artifact_id: Optional[str]

@dataclass
class MergedResult:
    result: SearchResult
    rrf_score: float
    collections: List[str]
```

---

## Data Schemas

### Memory Collection Schema

```json
{
  "id": "mem_{sha256(content)[:8]}",
  "document": "The actual memory content",
  "embedding": [3072 floats],
  "metadata": {
    "type": "preference|fact|project|decision",
    "confidence": 0.0-1.0,
    "ts": "2024-12-26T10:00:00Z",
    "conversation_id": "optional_conv_id",
    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072,
    "token_count": 150
  }
}
```

### History Collection Schema

```json
{
  "id": "{conversation_id}_turn_{turn_index}",
  "document": "user: Hello, how are you?",
  "embedding": [3072 floats],
  "metadata": {
    "conversation_id": "conv_abc123",
    "role": "user|assistant|system",
    "turn_index": 0,
    "ts": "2024-12-26T10:00:00Z",
    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072,
    "token_count": 25
  }
}
```

### Artifacts Collection Schema

```json
{
  "id": "art_{hash}",
  "document": "Full content OR summary for chunked",
  "embedding": [3072 floats],
  "metadata": {
    "artifact_type": "email|doc|chat|transcript|note",
    "source_system": "gmail|slack|drive|manual|test_corpus",
    "source_id": "unique_id_in_source_system",
    "source_url": "https://link.to/original",
    "title": "Document Title",
    "author": "Author Name",
    "participants": "comma,separated,list",
    "content_hash": "sha256_full_hash",
    "token_count": 5000,
    "is_chunked": true,
    "num_chunks": 6,
    "ts": "2024-12-26T10:00:00Z",
    "ingested_at": "2024-12-26T10:01:00Z",
    "sensitivity": "normal|sensitive|highly_sensitive",
    "visibility_scope": "me|team|org|custom",
    "retention_policy": "forever|1y|until_resolved|custom",
    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072
  }
}
```

### Artifact Chunks Collection Schema

```json
{
  "id": "art_{hash}::chunk::000::abcd1234",
  "document": "Chunk content text...",
  "embedding": [3072 floats],
  "metadata": {
    "artifact_id": "art_{hash}",
    "chunk_index": 0,
    "start_char": 0,
    "end_char": 2500,
    "token_count": 900,
    "content_hash": "sha256_chunk_hash",
    "ts": "2024-12-26T10:00:00Z",
    "sensitivity": "normal",
    "visibility_scope": "me",
    "retention_policy": "forever",
    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072
  }
}
```

---

## Data Flows

### Memory Storage Flow

```
User Request → memory_store(content, type, confidence)
                    │
                    ▼
         ┌──────────────────┐
         │ Input Validation │
         │ - type enum      │
         │ - confidence 0-1 │
         │ - content length │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Generate Embedding│
         │ (OpenAI API)     │
         │ 3072 dimensions  │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Generate mem_id  │
         │ sha256(content)  │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Store in ChromaDB│
         │ memory collection│
         └────────┬─────────┘
                  │
                  ▼
         Return: "Stored: mem_{id}"
```

### Artifact Ingestion Flow

```
User Request → artifact_ingest(type, source, content, ...)
                    │
                    ▼
         ┌──────────────────┐
         │ Input Validation │
         │ - artifact_type  │
         │ - content size   │
         │ - sensitivity    │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Compute Hashes   │
         │ - content_hash   │
         │ - artifact_id    │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Check Duplicate  │
         │ by source_id     │
         └────────┬─────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
        ▼                   ▼
   [Duplicate]         [New/Changed]
   Same hash?               │
        │                   │
        ▼                   ▼
   Return existing   Delete old version
                           │
                           ▼
                  ┌──────────────────┐
                  │ Check Token Count│
                  │ > 1200 tokens?   │
                  └────────┬─────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
        [No Chunking]            [Needs Chunking]
              │                         │
              ▼                         ▼
    ┌──────────────────┐     ┌──────────────────┐
    │ Generate Single  │     │ Generate Chunks  │
    │ Embedding        │     │ (900 tok, 100    │
    │                  │     │  overlap)        │
    └────────┬─────────┘     └────────┬─────────┘
             │                        │
             │                        ▼
             │               ┌──────────────────┐
             │               │ PHASE 1: Generate│
             │               │ ALL embeddings   │
             │               │ (batch API)      │
             │               └────────┬─────────┘
             │                        │
             │                        ▼
             │               ┌──────────────────┐
             │               │ PHASE 2: Write   │
             │               │ artifact + chunks│
             │               │ (atomic)         │
             │               └────────┬─────────┘
             │                        │
             ▼                        ▼
    ┌──────────────────┐     ┌──────────────────┐
    │ Store Artifact   │     │ Store Artifact + │
    │ (unchunked)      │     │ All Chunks       │
    └────────┬─────────┘     └────────┬─────────┘
             │                        │
             └────────────┬───────────┘
                          │
                          ▼
             Return: {artifact_id, is_chunked, num_chunks}
```

### Hybrid Search Flow

```
User Request → hybrid_search(query, limit, include_memory, expand_neighbors)
                    │
                    ▼
         ┌──────────────────┐
         │ Generate Query   │
         │ Embedding        │
         │ (OpenAI API)     │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Parallel Search  │
         │ - artifacts      │
         │ - artifact_chunks│
         │ - memory (opt)   │
         └────────┬─────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
[artifacts]  [chunks]    [memory]
    │             │             │
    └─────────────┼─────────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ RRF Scoring      │
         │ score = 1/(k+r+1)│
         │ k=60             │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Aggregate Scores │
         │ by result ID     │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Deduplicate by   │
         │ artifact_id      │
         │ (prefer chunks)  │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Expand Neighbors │
         │ (if requested)   │
         │ ±1 chunks        │
         └────────┬─────────┘
                  │
                  ▼
         Return: List[MergedResult]
```

---

## Directory Structure

```
mcp-server/
├── src/
│   ├── server.py              # Main FastMCP server with all 12 tools
│   ├── config.py              # Configuration management
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── embedding_service.py   # OpenAI embedding integration
│   │   ├── chunking_service.py    # Token-window chunking
│   │   ├── retrieval_service.py   # RRF hybrid search
│   │   └── privacy_service.py     # Privacy metadata (placeholder)
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── chroma_client.py       # ChromaDB connection manager
│   │   ├── collections.py         # Collection definitions and helpers
│   │   └── models.py              # Data models (Chunk, SearchResult, etc.)
│   │
│   └── utils/
│       ├── __init__.py
│       ├── errors.py              # Custom exceptions
│       └── logging.py             # Logging configuration
│
├── tests/
│   ├── unit/                      # Unit tests
│   ├── integration/               # Integration tests
│   └── browser/                   # Browser automation tests
│
├── requirements.txt               # Python dependencies
├── pyproject.toml                # Project metadata
└── README.md                     # Setup instructions
```

---

## Dependencies

### Core Dependencies
```
mcp>=1.0.0                    # MCP SDK with FastMCP
chromadb>=0.4.0               # Vector database
openai>=1.0.0                 # OpenAI API client
tiktoken>=0.5.0               # Token counting for chunking
pydantic>=2.0.0               # Data validation
python-dotenv>=1.0.0          # Environment configuration
```

### Development Dependencies
```
pytest>=7.0.0                 # Testing framework
pytest-asyncio>=0.21.0        # Async test support
httpx>=0.24.0                 # HTTP client for tests
```

---

## Configuration & Environment

### Required Environment Variables
```bash
OPENAI_API_KEY=sk-...         # Required: OpenAI API key for embeddings
```

### Optional Environment Variables
```bash
CHROMA_HOST=localhost         # ChromaDB host (default: localhost)
CHROMA_PORT=8100              # ChromaDB port (default: 8100)
LOG_LEVEL=INFO                # Logging level (default: INFO)
```

### MCP Client Configuration

**Cursor IDE** (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "memory": {
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

**Claude Desktop** (via mcp-remote proxy):
```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:3001/mcp/"]
    }
  }
}
```

---

## API Contract Summary

### Tool Response Formats

**Success Responses**:
```python
# Simple tools
return "Stored memory: mem_abc12345"

# Complex tools (artifact_ingest)
return {
    "artifact_id": "art_abc12345",
    "is_chunked": True,
    "num_chunks": 5,
    "stored_ids": ["art_abc12345", "art_abc12345::chunk::000::...", ...]
}

# Search results
return [
    {
        "id": "art_abc12345::chunk::002::def67890",
        "content": "Matching text...",
        "score": 0.0164,  # RRF score
        "collections": ["artifact_chunks"],
        "metadata": {...}
    },
    ...
]
```

**Error Responses**:
```python
# Validation errors
return "Error: Invalid artifact_type: programming. Must be one of: email, doc, chat, transcript, note"

# API errors
return {"error": "Failed to generate embeddings: Rate limit exceeded"}

# System errors
return f"Search failed: {str(exception)}"
```

---

## Performance Characteristics

| Operation | Typical Latency | Notes |
|-----------|-----------------|-------|
| `memory_store` | 200-500ms | Single embedding generation |
| `memory_search` | 300-600ms | Embedding + vector search |
| `artifact_ingest` (small) | 200-500ms | < 1200 tokens |
| `artifact_ingest` (large) | 1-5s | Depends on chunk count |
| `hybrid_search` | 400-800ms | Multi-collection + RRF |
| `embedding_health` | 50-100ms | Health check only |

---

## Security Considerations

### Current (V2)
- Privacy metadata stored but not enforced
- No authentication/authorization
- Designed for local/trusted network access
- HTTPS via ngrok for external access

### Future (V3 Candidates)
- Enforce visibility_scope filtering in queries
- Implement retention policy cleanup jobs
- Add API key authentication
- Implement user/team context

---

## Known Limitations

1. **Single-user**: No multi-tenancy or user isolation
2. **No persistence**: ChromaDB data lives in container/process
3. **Rate limits**: OpenAI API has rate limits (429 errors)
4. **Sync-only**: All operations are synchronous
5. **Privacy not enforced**: Metadata only, no query filtering

---

## Future Architecture (V3 Candidates)

### Potential Enhancements

1. **Privacy Enforcement**
   - Filter search results by visibility_scope
   - Implement retention policy automation
   - Add sensitivity-based access control

2. **Multi-User Support**
   - User context in requests
   - Per-user collections or tenant isolation
   - Team-based sharing

3. **Async Operations**
   - Background ingestion for large documents
   - Async embedding generation
   - Progress tracking for long operations

4. **Enhanced Search**
   - Faceted search by metadata
   - Date range filtering
   - Boolean query operators

5. **Storage Optimization**
   - Persistent ChromaDB with volume mounts
   - Embedding caching
   - Incremental re-embedding

6. **Monitoring & Observability**
   - Prometheus metrics
   - Distributed tracing
   - Cost tracking for OpenAI API

---

## Appendix: ID Formats

| Entity | Format | Example |
|--------|--------|---------|
| Memory | `mem_{sha256[:8]}` | `mem_abc12345` |
| History Turn | `{conv_id}_turn_{index}` | `conv123_turn_5` |
| Artifact | `art_{sha256[:8]}` | `art_def67890` |
| Chunk | `{art_id}::chunk::{idx:03d}::{hash[:8]}` | `art_def67890::chunk::003::aaa11111` |

---

## Appendix: Embedding Quality

OpenAI text-embedding-3-large vs alternatives:

| Model | Dimensions | Quality | Cost |
|-------|------------|---------|------|
| text-embedding-3-large | 3072 | Highest | $$$ |
| text-embedding-3-small | 1536 | High | $$ |
| text-embedding-ada-002 | 1536 | Good | $ |
| all-MiniLM-L6-v2 (local) | 384 | Medium | Free |

V2 chose text-embedding-3-large for maximum semantic understanding quality.
