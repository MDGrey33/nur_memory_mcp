# MCP Memory Server: V1 to V2 Changes

## Executive Summary

V2 represents a major evolution from V1's basic memory storage to a production-grade document intelligence platform. The key changes are:

1. **Upgraded embeddings**: ChromaDB default (384 dims) → OpenAI text-embedding-3-large (3072 dims)
2. **New artifact system**: Full document ingestion with automatic chunking
3. **Hybrid search**: RRF-based multi-collection search with deduplication
4. **Enhanced toolset**: 6 tools → 12 tools (doubled capability)

---

## Architecture Changes

### V1 Architecture
```
Claude App → MCP → chroma-mcp-gateway → ChromaDB (in-process)
                                            ↓
                                    Default embeddings (384d)
```

### V2 Architecture
```
Claude App → MCP (Streamable HTTP) → FastMCP Server
                                          ↓
                    ┌─────────────────────┼─────────────────────┐
                    ↓                     ↓                     ↓
            OpenAI API            ChromaDB HTTP            Services
            (embeddings)          (vector store)       (chunking, retrieval)
```

| Aspect | V1 | V2 |
|--------|----|----|
| MCP Transport | stdio (via gateway) | Streamable HTTP (native) |
| Embedding Provider | ChromaDB default | OpenAI API |
| Embedding Model | all-MiniLM-L6-v2 | text-embedding-3-large |
| Embedding Dimensions | 384 | 3072 |
| Vector Store | ChromaDB (in-process) | ChromaDB HTTP server |
| Collections | 2 (memory, history) | 4 (+artifacts, artifact_chunks) |

---

## Embedding System Changes

### V1 Embeddings
- **Provider**: ChromaDB auto-embedding (sentence-transformers)
- **Model**: all-MiniLM-L6-v2
- **Dimensions**: 384
- **Location**: In-process, synchronous
- **Cost**: Free (local compute)

### V2 Embeddings
- **Provider**: OpenAI API
- **Model**: text-embedding-3-large (configurable)
- **Dimensions**: 3072 (8x improvement)
- **Location**: External API with retry logic
- **Features**:
  - Exponential backoff for rate limits (429)
  - Timeout handling (30s default)
  - Batch processing for multi-document ingestion
  - Health check endpoint

```python
# V2 Embedding Service (services/embedding_service.py)
class EmbeddingService:
    def __init__(self, api_key, model="text-embedding-3-large", dimensions=3072):
        self.client = OpenAI(api_key=api_key, timeout=30.0)

    def generate_embedding(self, text: str) -> List[float]:
        # Retry logic with exponential backoff

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        # Efficient batch processing
```

---

## Tool Inventory Comparison

### V1 Tools (6 total)
| Tool | Description |
|------|-------------|
| `memory_store` | Store semantic memory |
| `memory_search` | Search memories by query |
| `memory_list` | List all memories |
| `memory_delete` | Delete specific memory |
| `history_append` | Add to conversation history |
| `history_get` | Retrieve conversation history |

### V2 Tools (12 total)
| Tool | Status | Description |
|------|--------|-------------|
| `memory_store` | Enhanced | Now with OpenAI embeddings + metadata |
| `memory_search` | Enhanced | Uses 3072-dim vectors |
| `memory_list` | Unchanged | List all memories |
| `memory_delete` | Unchanged | Delete specific memory |
| `history_append` | Enhanced | Token counting, embedding metadata |
| `history_get` | Unchanged | Retrieve conversation history |
| `artifact_ingest` | **NEW** | Ingest documents with auto-chunking |
| `artifact_search` | **NEW** | Search artifacts and chunks |
| `artifact_get` | **NEW** | Retrieve full artifact by ID |
| `artifact_delete` | **NEW** | Delete artifact and chunks |
| `hybrid_search` | **NEW** | Multi-collection RRF search |
| `embedding_health` | **NEW** | Check OpenAI API status |

---

## New Artifact System

### Overview
V2 introduces a complete artifact management system for ingesting, chunking, and searching documents.

### Artifact Types
```python
VALID_ARTIFACT_TYPES = ["email", "doc", "chat", "transcript", "note"]
```

### Chunking Strategy
The token-window chunking system handles large documents:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `single_piece_max` | 1200 tokens | Threshold for chunking |
| `chunk_target` | 900 tokens | Target chunk size |
| `chunk_overlap` | 100 tokens | Overlap between chunks |

```python
# Chunking decision logic
def should_chunk(text: str) -> Tuple[bool, int]:
    token_count = tiktoken.encode(text)
    return (token_count > 1200, token_count)
```

### Chunk ID Format
```
{artifact_id}::chunk::{index:03d}::{content_hash[:8]}
```
Example: `art_abc12345::chunk::003::e9f1a2b3`

### Two-Phase Atomic Write
V2 implements atomic writes for chunked documents:

1. **Phase 1**: Generate ALL embeddings via OpenAI batch API
2. **Phase 2**: Write to ChromaDB (only if all embeddings succeed)

This ensures data consistency - no partial artifacts or orphaned chunks.

---

## Hybrid Search System

### RRF (Reciprocal Rank Fusion)
V2 introduces RRF-based multi-collection search:

```python
# RRF score calculation
rrf_score = 1.0 / (k + rank + 1)  # k=60 (standard)
```

### Search Flow
1. Generate query embedding via OpenAI
2. Search across collections (artifacts, artifact_chunks, optionally memory)
3. Calculate RRF scores per result
4. Aggregate scores across collections
5. Deduplicate by artifact_id (prefer chunks over full artifacts)
6. Optionally expand chunk results with ±1 neighbors

### Neighbor Expansion
For chunk results, optionally include surrounding context:
```
[Previous chunk content]
[CHUNK BOUNDARY]
[Target chunk content]
[CHUNK BOUNDARY]
[Next chunk content]
```

---

## Collection Schema Changes

### V1 Collections

**memory**
```json
{
  "id": "mem_{hash}",
  "content": "...",
  "metadata": {
    "type": "preference|fact|project|decision",
    "confidence": 0.0-1.0,
    "ts": "ISO8601"
  }
}
```

**history**
```json
{
  "id": "{conversation_id}_turn_{index}",
  "content": "{role}: {message}",
  "metadata": {
    "conversation_id": "...",
    "role": "user|assistant|system",
    "turn_index": 0
  }
}
```

### V2 Collections (Enhanced + New)

**memory** (enhanced)
```json
{
  "id": "mem_{hash}",
  "content": "...",
  "embedding": [3072 floats],
  "metadata": {
    "type": "preference|fact|project|decision",
    "confidence": 0.0-1.0,
    "ts": "ISO8601",
    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072,
    "token_count": 123
  }
}
```

**history** (enhanced)
- Same structure as V1
- Added: `embedding_provider`, `embedding_model`, `embedding_dimensions`, `token_count`

**artifacts** (NEW)
```json
{
  "id": "art_{hash}",
  "content": "full text or summary for chunked",
  "embedding": [3072 floats],
  "metadata": {
    "artifact_type": "email|doc|chat|transcript|note",
    "source_system": "gmail|slack|drive|manual",
    "source_id": "unique_id_in_source",
    "source_url": "https://...",
    "title": "...",
    "author": "...",
    "participants": "comma,separated",
    "content_hash": "sha256",
    "token_count": 1234,
    "is_chunked": true|false,
    "num_chunks": 5,
    "ts": "ISO8601",
    "sensitivity": "normal|sensitive|highly_sensitive",
    "visibility_scope": "me|team|org|custom",
    "retention_policy": "forever|1y|until_resolved|custom",
    "ingested_at": "ISO8601"
  }
}
```

**artifact_chunks** (NEW)
```json
{
  "id": "art_{hash}::chunk::000::abc12345",
  "content": "chunk text",
  "embedding": [3072 floats],
  "metadata": {
    "artifact_id": "art_{hash}",
    "chunk_index": 0,
    "start_char": 0,
    "end_char": 2500,
    "token_count": 900,
    "content_hash": "sha256",
    "ts": "ISO8601",
    "sensitivity": "normal",
    "visibility_scope": "me",
    "retention_policy": "forever"
  }
}
```

---

## Privacy Metadata

V2 adds privacy fields (stored but not enforced in V2):

| Field | Values | Description |
|-------|--------|-------------|
| `sensitivity` | normal, sensitive, highly_sensitive | Data classification |
| `visibility_scope` | me, team, org, custom | Who can access |
| `retention_policy` | forever, 1y, until_resolved, custom | How long to keep |

These are recorded for future enforcement in V3.

---

## Deduplication System

V2 implements content-based deduplication:

```python
# Artifact ID generation
if source_id:
    artifact_id = "art_" + sha256(f"{source_system}:{source_id}")[:8]
else:
    artifact_id = "art_" + sha256(content)[:8]
```

On re-ingestion:
- Same content hash → Skip (return existing ID)
- Different content hash → Delete old, insert new (cascade delete chunks)

---

## Error Handling

### V1 Error Handling
- Basic try/catch with string returns

### V2 Error Handling
- Custom exception hierarchy:
  - `EmbeddingError`: OpenAI API failures
  - `ValidationError`: Input validation failures
  - `RetrievalError`: Search failures
- Exponential backoff for rate limits
- Detailed logging with `exc_info=True`
- Health check endpoint for monitoring

---

## Configuration

### V1 Configuration
- Minimal configuration via gateway

### V2 Configuration
```python
# config.py
class Config:
    chroma_host: str = "localhost"
    chroma_port: int = 8100
    openai_api_key: str  # Required
    openai_embed_model: str = "text-embedding-3-large"
    openai_embed_dims: int = 3072
    openai_timeout: float = 30.0
    chunk_threshold: int = 1200
    chunk_target: int = 900
    chunk_overlap: int = 100
```

---

## API Response Format Changes

### V1 Response Format
```
"Stored memory: mem_abc123"
```

### V2 Response Format
```json
{
  "artifact_id": "art_abc12345",
  "is_chunked": true,
  "num_chunks": 5,
  "stored_ids": ["art_abc12345", "art_abc12345::chunk::000::...", ...]
}
```

---

## Test Coverage

| Area | V1 | V2 |
|------|----|----|
| Unit Tests | Basic | 143+ tests passing |
| Integration Tests | None | HTTP client simulation |
| Browser Tests | None | 11 tests with automation |
| Coverage Target | N/A | >80% |

---

## Performance Characteristics

| Operation | V1 | V2 |
|-----------|----|----|
| Embedding latency | ~10ms (local) | ~200-500ms (API) |
| Embedding quality | Medium (384d) | High (3072d) |
| Search accuracy | Good | Excellent (8x vector resolution) |
| Large doc handling | Manual chunking | Automatic |
| Multi-source search | No | Yes (RRF) |

---

## Migration Notes

### Breaking Changes
1. ChromaDB collections have different embedding dimensions
2. Existing memories cannot be searched with new embeddings
3. All data requires re-ingestion with OpenAI embeddings

### Recommended Migration
1. Export V1 memories as text
2. Clear V1 ChromaDB data
3. Re-ingest via V2 `memory_store` and `artifact_ingest`

---

## Summary of Key Additions

1. **OpenAI Embeddings**: 8x higher dimensionality for better semantic understanding
2. **Artifact System**: Full document lifecycle management
3. **Smart Chunking**: Token-window strategy with overlap
4. **Hybrid Search**: RRF-based multi-collection retrieval
5. **Atomic Writes**: Two-phase commit for data consistency
6. **Privacy Metadata**: Foundation for access control
7. **Deduplication**: Content-hash based duplicate detection
8. **Health Monitoring**: API status and error tracking
