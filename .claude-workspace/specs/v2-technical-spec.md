# MCP Memory Server v2.0 - Technical Specification

**Document Version:** 1.0
**Date:** 2025-12-25
**Author:** Technical PM
**Status:** Draft for Architecture Review

---

## 1. Executive Summary

### 1.1 Purpose

This specification defines the technical implementation for MCP Memory Server v2.0, a clean-slate rewrite that upgrades embedding quality to OpenAI's text-embedding-3-large, introduces artifact ingestion for document/email/chat storage, and implements hybrid retrieval with reciprocal rank fusion.

### 1.2 Key Changes from v1

| Aspect | v1 | v2 |
|--------|----|----|
| **Embeddings** | ChromaDB auto-embed (384 dims) | OpenAI text-embedding-3-large (3072 dims) |
| **Migration** | N/A | Clean slate - wipe all v1 data |
| **Storage Model** | memory + history only | memory + history + artifacts + artifact_chunks |
| **Chunking** | None | Token-window with overlap (≤1200 single, 900+100 overlap) |
| **Retrieval** | Single collection search | Hybrid search with RRF merging |
| **Privacy** | None | Privacy fields stored (enforcement in v3) |

### 1.3 Success Criteria

- All collections use OpenAI embeddings (3072 dimensions)
- Artifacts ≤1200 tokens stored unchunked
- Artifacts >1200 tokens chunked with 100 token overlap
- Hybrid search merges results using RRF algorithm
- No duplicate records on re-ingestion
- Two-phase atomic writes prevent partial data
- Existing memory/history tools continue to work

### 1.4 Out of Scope (Deferred to Later Phases)

- Structure-aware chunking (v2.1)
- Multi-user authentication (v3)
- Privacy enforcement (v3)
- Artifact versioning history (v3)
- Event extraction and summaries (Phase 3)
- Kafka event log (Phase 4)
- Graph database integration (Phase 4)

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Claude Desktop                          │
│                    (MCP Client)                              │
└────────────────────────┬────────────────────────────────────┘
                         │ MCP over HTTP/SSE
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   MCP Memory Server                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Tool Layer (FastMCP)                                 │  │
│  │  - memory_store/search/list/delete                   │  │
│  │  - history_append/get                                │  │
│  │  - artifact_ingest/search/get/delete                 │  │
│  │  - hybrid_search                                     │  │
│  │  - embedding_health                                  │  │
│  └──────────────┬───────────────────────────────────────┘  │
│                 │                                            │
│  ┌──────────────▼───────────────────────────────────────┐  │
│  │  Service Layer                                        │  │
│  │  - EmbeddingService (OpenAI client)                  │  │
│  │  - ChunkingService (token-window)                    │  │
│  │  - RetrievalService (RRF merging)                    │  │
│  │  - PrivacyFilterService (placeholder)                │  │
│  └──────────────┬───────────────────────────────────────┘  │
│                 │                                            │
│  ┌──────────────▼───────────────────────────────────────┐  │
│  │  Storage Layer (ChromaDB)                            │  │
│  │  - memory collection                                 │  │
│  │  - history collection                                │  │
│  │  - artifacts collection                              │  │
│  │  - artifact_chunks collection                        │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────┬────────────────────────────────────────────┘
                 │ HTTPS
                 ▼
┌─────────────────────────────────────────────────────────────┐
│                    OpenAI API                                │
│             (text-embedding-3-large)                         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Technology Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Runtime | Python | 3.11+ | Server implementation |
| Framework | FastMCP | latest | MCP protocol handling |
| Web Server | Uvicorn + Starlette | latest | HTTP transport |
| Vector DB | ChromaDB | latest | Embedding storage |
| Embeddings | OpenAI API | text-embedding-3-large | Vector generation |
| Tokenizer | tiktoken | latest | Token counting (cl100k_base) |
| Containerization | Docker Compose | latest | Deployment |

### 2.3 Data Flow

#### 2.3.1 Artifact Ingestion Flow

```
1. Client calls artifact_ingest with content
2. Server computes content_hash (SHA256)
3. Server checks for duplicate (source_system + source_id)
   - If exists and hash matches: return existing IDs (no-op)
   - If exists and hash differs: delete old + proceed
4. Server tokenizes content (tiktoken cl100k_base)
5. Decision branch:
   a) If token_count ≤ 1200:
      - Generate embedding for full content
      - Store in artifacts collection (one record)
   b) If token_count > 1200:
      - Store artifact metadata in artifacts (no embedding or synopsis)
      - Chunk content (900 tokens + 100 overlap)
      - Generate embeddings for ALL chunks (batch)
      - Store chunks in artifact_chunks collection
6. Return artifact_id, is_chunked, num_chunks, stored_ids
```

#### 2.3.2 Hybrid Search Flow

```
1. Client calls hybrid_search with query
2. Server generates query embedding via OpenAI
3. Parallel vector searches:
   - artifacts collection (small docs)
   - artifact_chunks collection (doc fragments)
   - [Optional] memory collection (if include_memory=True)
4. Apply privacy filters (placeholder - always allows in v2)
5. Merge results using RRF:
   - For each result, compute: score = 1 / (60 + rank)
   - Deduplicate by artifact_id (best chunk wins)
   - Sort by aggregated RRF score
6. If expand_neighbors=True:
   - For chunk hits, fetch ±1 adjacent chunks
   - Combine with [CHUNK BOUNDARY] markers
7. Return ranked results with provenance
```

---

## 3. Data Models

### 3.1 Collection Schemas

#### 3.1.1 `memory` Collection

**Purpose:** Small, durable semantic items (preferences, facts, decisions, projects)

**Schema:**
```json
{
  "id": "mem_{12_hex_chars}",
  "content": "User prefers dark mode and Python over JavaScript",
  "metadata": {
    "type": "preference | fact | project | decision",
    "confidence": 0.9,
    "ts": "2025-12-25T10:30:00Z",
    "conversation_id": "optional-context",

    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072,
    "token_count": 142
  }
}
```

**Indexes:**
- Vector index on embeddings (dimension=3072)
- Filter indexes on: `type`, `ts`, `conversation_id`

**ID Generation:**
- Format: `mem_` + 12 hex characters from UUID4
- Example: `mem_abc123def456`

---

#### 3.1.2 `history` Collection

**Purpose:** Conversation turns keyed by conversation_id and turn_index

**Schema:**
```json
{
  "id": "{conversation_id}_turn_{turn_index}",
  "content": "user: How do I implement auth?",
  "metadata": {
    "conversation_id": "conv123",
    "role": "user | assistant | system",
    "turn_index": 0,
    "ts": "2025-12-25T10:30:00Z",

    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072,
    "token_count": 12
  }
}
```

**Indexes:**
- Vector index on embeddings (dimension=3072)
- Filter indexes on: `conversation_id`, `role`, `turn_index`, `ts`

**ID Generation:**
- Format: `{conversation_id}_turn_{turn_index}`
- Example: `conv123_turn_0`

---

#### 3.1.3 `artifacts` Collection (NEW)

**Purpose:** Full artifact storage for small documents OR metadata for chunked documents

**Schema:**
```json
{
  "id": "art_{short_hash}",
  "content": "Full text (if ≤1200 tokens) OR empty (if chunked)",
  "metadata": {
    "artifact_type": "email | doc | chat | transcript | note",
    "source_system": "gmail | slack | drive | manual",
    "source_id": "unique identifier from source",
    "source_url": "optional URL",
    "ts": "2025-12-25T10:30:00Z",

    "title": "optional subject/title",
    "author": "optional",
    "participants": ["optional list"],

    "content_hash": "sha256 hex digest",
    "token_count": 5400,
    "is_chunked": true,
    "num_chunks": 6,

    "sensitivity": "normal | sensitive | highly_sensitive",
    "visibility_scope": "me | team | org | custom",
    "retention_policy": "forever | 1y | until_resolved | custom",

    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072,
    "ingested_at": "2025-12-25T10:30:00Z"
  }
}
```

**Indexes:**
- Vector index on embeddings (dimension=3072, only for unchunked docs)
- Filter indexes on: `artifact_type`, `source_system`, `source_id`, `sensitivity`, `ts`, `content_hash`

**ID Generation:**
- Format: `art_` + first 8 chars of SHA256(source_system + source_id)
- Fallback: `art_` + first 8 chars of SHA256(content) if no source_id
- Example: `art_9f2ca8b1`

---

#### 3.1.4 `artifact_chunks` Collection (NEW)

**Purpose:** Chunk vectors for documents exceeding token threshold

**Schema:**
```json
{
  "id": "{artifact_id}::chunk::{chunk_index}::{hash_prefix}",
  "content": "chunk text content",
  "metadata": {
    "artifact_id": "art_9f2ca8b1",
    "chunk_index": 3,
    "start_char": 8421,
    "end_char": 11290,
    "token_count": 910,
    "content_hash": "sha256 hex digest",
    "ts": "2025-12-25T10:30:00Z",

    "sensitivity": "inherited from artifact",
    "visibility_scope": "inherited from artifact",
    "retention_policy": "inherited from artifact",

    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072
  }
}
```

**Indexes:**
- Vector index on embeddings (dimension=3072)
- Filter indexes on: `artifact_id`, `chunk_index`, `sensitivity`, `ts`

**ID Generation:**
- Format: `{artifact_id}::chunk::{chunk_index:03d}::{first_8_chars_of_hash}`
- Example: `art_9f2ca8b1::chunk::003::c0ffee12`
- Stable: Same input produces same ID

---

### 3.2 Metadata Field Specifications

#### 3.2.1 Standard Fields (All Collections)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `embedding_provider` | string | Yes | Always "openai" in v2 |
| `embedding_model` | string | Yes | Model name (text-embedding-3-large) |
| `embedding_dimensions` | integer | Yes | Always 3072 in v2 |
| `token_count` | integer | Yes | Token count using tiktoken cl100k_base |
| `ts` | ISO8601 string | Yes | UTC timestamp of creation |

#### 3.2.2 Privacy Fields (Artifacts & Chunks)

| Field | Type | Required | Default | v2 Behavior |
|-------|------|----------|---------|-------------|
| `sensitivity` | enum | No | "normal" | Stored, not enforced |
| `visibility_scope` | enum | No | "me" | Stored, not enforced |
| `retention_policy` | enum | No | "forever" | Stored, not enforced |

**Sensitivity Levels:**
- `normal`: General work content
- `sensitive`: Confidential work, personal info
- `highly_sensitive`: Medical, children, financial

**Visibility Scopes:**
- `me`: Only the user
- `team`: User's team members
- `org`: Organization-wide
- `custom`: Custom ACL (deferred)

**Retention Policies:**
- `forever`: No automatic deletion
- `1y`: Delete after 1 year
- `until_resolved`: Delete when marked complete
- `custom`: Custom retention rule (deferred)

#### 3.2.3 Artifact-Specific Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `artifact_type` | enum | Yes | Source type classification |
| `source_system` | string | Yes | Origin system identifier |
| `source_id` | string | No* | Unique ID in source system |
| `source_url` | string | No | Link to original |
| `title` | string | No | Subject line or title |
| `author` | string | No | Primary author |
| `participants` | string[] | No | All participants |
| `content_hash` | string | Yes | SHA256 of full content |
| `is_chunked` | boolean | Yes | True if stored in chunks |
| `num_chunks` | integer | Conditional | Required if is_chunked=true |

\* source_id required for deduplication, but manual notes may omit

---

## 4. Tool Specifications

### 4.1 Existing Tools (Updated for OpenAI)

#### 4.1.1 `memory_store`

**Status:** Updated - now generates OpenAI embeddings

**Signature:**
```python
def memory_store(
    content: str,
    type: str,
    confidence: float,
    conversation_id: str | None = None
) -> str
```

**Parameters:**

| Name | Type | Required | Validation | Description |
|------|------|----------|------------|-------------|
| `content` | string | Yes | 1-10000 chars | Memory content |
| `type` | string | Yes | enum: preference, fact, project, decision | Category |
| `confidence` | float | Yes | 0.0-1.0 | Confidence score |
| `conversation_id` | string | No | - | Optional context |

**Behavior Changes:**
1. Generate embedding via OpenAI (not ChromaDB auto-embed)
2. Add embedding metadata fields
3. Implement retry logic (3 attempts with backoff)

**Returns:**
```
"Stored memory [mem_abc123def456]: User prefers dark mode..."
```

**Error Handling:** See Section 6

---

#### 4.1.2 `memory_search`

**Status:** Updated - uses OpenAI embeddings for query

**Signature:**
```python
def memory_search(
    query: str,
    limit: int = 5,
    min_confidence: float = 0.0
) -> str
```

**Parameters:**

| Name | Type | Required | Default | Validation | Description |
|------|------|----------|---------|------------|-------------|
| `query` | string | Yes | - | 1-500 chars | Search query |
| `limit` | integer | No | 5 | 1-20 | Max results |
| `min_confidence` | float | No | 0.0 | 0.0-1.0 | Filter threshold |

**Behavior Changes:**
1. Generate query embedding via OpenAI
2. Search against OpenAI-generated embeddings in collection

**Returns:**
```
[mem_abc123] (preference, conf=0.9): User prefers dark mode
[mem_def456] (fact, conf=0.8): User's timezone is PST
```

**Error Handling:** See Section 6

---

#### 4.1.3 `memory_list`

**Status:** Unchanged

**Signature:**
```python
def memory_list(
    type: str | None = None,
    limit: int = 20
) -> str
```

**Parameters:**

| Name | Type | Required | Default | Validation | Description |
|------|------|----------|---------|------------|-------------|
| `type` | string | No | None | enum or None | Filter by type |
| `limit` | integer | No | 20 | 1-100 | Max results |

**Returns:**
```
Found 3 memories:
[mem_abc123] (preference, conf=0.9): User prefers dark mode
[mem_def456] (fact, conf=0.8): User's timezone is PST
[mem_ghi789] (project, conf=1.0): Working on MCP Memory v2
```

---

#### 4.1.4 `memory_delete`

**Status:** Unchanged

**Signature:**
```python
def memory_delete(memory_id: str) -> str
```

**Parameters:**

| Name | Type | Required | Validation | Description |
|------|------|----------|------------|-------------|
| `memory_id` | string | Yes | Starts with "mem_" | Memory ID |

**Returns:**
```
"Deleted memory: mem_abc123def456"
```

---

#### 4.1.5 `history_append`

**Status:** Updated - now generates OpenAI embeddings

**Signature:**
```python
def history_append(
    conversation_id: str,
    role: str,
    content: str,
    turn_index: int
) -> str
```

**Parameters:**

| Name | Type | Required | Validation | Description |
|------|------|----------|------------|-------------|
| `conversation_id` | string | Yes | 1-100 chars | Unique conversation ID |
| `role` | string | Yes | enum: user, assistant, system | Speaker role |
| `content` | string | Yes | 1-50000 chars | Message content |
| `turn_index` | integer | Yes | ≥0 | Turn number |

**Behavior Changes:**
1. Generate embedding via OpenAI
2. Add embedding metadata fields

**Returns:**
```
"Appended turn 0 to conv123"
```

---

#### 4.1.6 `history_get`

**Status:** Unchanged

**Signature:**
```python
def history_get(
    conversation_id: str,
    limit: int = 16
) -> str
```

**Parameters:**

| Name | Type | Required | Default | Validation | Description |
|------|------|----------|---------|------------|-------------|
| `conversation_id` | string | Yes | - | 1-100 chars | Conversation ID |
| `limit` | integer | No | 16 | 1-50 | Number of recent turns |

**Returns:**
```
user: How do I implement auth?
assistant: Here's a secure approach...
user: What about JWT tokens?
```

---

### 4.2 New Tools (v2)

#### 4.2.1 `artifact_ingest` (NEW)

**Purpose:** Ingest documents, emails, chats with automatic chunking

**Signature:**
```python
def artifact_ingest(
    artifact_type: str,
    source_system: str,
    content: str,
    source_id: str | None = None,
    source_url: str | None = None,
    title: str | None = None,
    author: str | None = None,
    participants: list[str] | None = None,
    ts: str | None = None,
    sensitivity: str = "normal",
    visibility_scope: str = "me",
    retention_policy: str = "forever"
) -> dict
```

**Parameters:**

| Name | Type | Required | Default | Validation | Description |
|------|------|----------|---------|------------|-------------|
| `artifact_type` | string | Yes | - | enum: email, doc, chat, transcript, note | Source type |
| `source_system` | string | Yes | - | 1-100 chars | Origin system |
| `content` | string | Yes | - | 1-10000000 chars | Full text |
| `source_id` | string | No | None | 1-500 chars | Unique ID in source |
| `source_url` | string | No | None | Valid URL | Link to original |
| `title` | string | No | None | 1-500 chars | Subject/title |
| `author` | string | No | None | 1-200 chars | Primary author |
| `participants` | string[] | No | None | Max 100 items | All participants |
| `ts` | string | No | None | ISO8601 | Event timestamp |
| `sensitivity` | string | No | "normal" | enum: normal, sensitive, highly_sensitive | Privacy level |
| `visibility_scope` | string | No | "me" | enum: me, team, org, custom | Who can see |
| `retention_policy` | string | No | "forever" | enum: forever, 1y, until_resolved, custom | Retention rule |

**Algorithm:**

```python
# 1. Compute content hash
content_hash = sha256(content).hexdigest()

# 2. Generate artifact_id
if source_id:
    artifact_id = "art_" + sha256(f"{source_system}:{source_id}")[:8]
else:
    artifact_id = "art_" + content_hash[:8]

# 3. Check for duplicate
existing = get_artifact_by_source(source_system, source_id)
if existing and existing.content_hash == content_hash:
    return existing  # No-op

if existing and existing.content_hash != content_hash:
    artifact_delete(existing.artifact_id)  # Delete old version

# 4. Count tokens
token_count = count_tokens(content)  # tiktoken cl100k_base

# 5. Decision: chunk or store whole
if token_count <= SINGLE_PIECE_MAX_TOKENS:
    # Store as single artifact
    embedding = generate_embedding(content)
    store_in_artifacts(
        id=artifact_id,
        content=content,
        embedding=embedding,
        metadata={...}
    )
    return {
        "artifact_id": artifact_id,
        "is_chunked": False,
        "num_chunks": 0,
        "stored_ids": [artifact_id]
    }
else:
    # Store metadata + chunks
    chunks = chunk_content(content)  # Token-window chunking

    # Two-phase atomic write
    embeddings = []
    for chunk in chunks:
        emb = generate_embedding(chunk.content)
        embeddings.append(emb)

    # Only write if ALL embeddings succeeded
    store_artifact_metadata(artifact_id, metadata={..., is_chunked=True})
    chunk_ids = []
    for chunk, embedding in zip(chunks, embeddings):
        chunk_id = store_chunk(artifact_id, chunk, embedding)
        chunk_ids.append(chunk_id)

    return {
        "artifact_id": artifact_id,
        "is_chunked": True,
        "num_chunks": len(chunks),
        "stored_ids": [artifact_id] + chunk_ids
    }
```

**Returns:**
```json
{
  "artifact_id": "art_9f2ca8b1",
  "is_chunked": true,
  "num_chunks": 6,
  "stored_ids": [
    "art_9f2ca8b1",
    "art_9f2ca8b1::chunk::000::a1b2c3d4",
    "art_9f2ca8b1::chunk::001::e5f6g7h8",
    "art_9f2ca8b1::chunk::002::i9j0k1l2",
    "art_9f2ca8b1::chunk::003::m3n4o5p6",
    "art_9f2ca8b1::chunk::004::q7r8s9t0",
    "art_9f2ca8b1::chunk::005::u1v2w3x4"
  ]
}
```

**Error Handling:** See Section 6

---

#### 4.2.2 `artifact_search` (NEW)

**Purpose:** Semantic search across artifacts and chunks

**Signature:**
```python
def artifact_search(
    query: str,
    limit: int = 5,
    artifact_type: str | None = None,
    source_system: str | None = None,
    sensitivity: str | None = None,
    visibility_scope: str | None = None,
    time_range_start: str | None = None,
    time_range_end: str | None = None,
    expand_neighbors: bool = False
) -> str
```

**Parameters:**

| Name | Type | Required | Default | Validation | Description |
|------|------|----------|---------|------------|-------------|
| `query` | string | Yes | - | 1-500 chars | Search query |
| `limit` | integer | No | 5 | 1-50 | Max results |
| `artifact_type` | string | No | None | enum or None | Filter by type |
| `source_system` | string | No | None | - | Filter by source |
| `sensitivity` | string | No | None | enum or None | Filter by sensitivity |
| `visibility_scope` | string | No | None | enum or None | Filter by visibility |
| `time_range_start` | string | No | None | ISO8601 | Start timestamp |
| `time_range_end` | string | No | None | ISO8601 | End timestamp |
| `expand_neighbors` | boolean | No | False | - | Include ±1 chunks |

**Algorithm:**

```python
# 1. Generate query embedding
query_embedding = generate_embedding(query)

# 2. Search artifacts (unchunked only)
artifact_results = search_collection(
    collection="artifacts",
    query_embedding=query_embedding,
    filters=build_filters(...),
    limit=limit * 2  # Overfetch for merging
)

# 3. Search chunks
chunk_results = search_collection(
    collection="artifact_chunks",
    query_embedding=query_embedding,
    filters=build_filters(...),
    limit=limit * 2
)

# 4. Merge and deduplicate
merged = []
seen_artifacts = {}

for result in sorted(artifact_results + chunk_results, key=lambda x: x.score):
    artifact_id = result.artifact_id

    if artifact_id not in seen_artifacts:
        # First time seeing this artifact
        seen_artifacts[artifact_id] = result
        merged.append(result)
    else:
        # Already seen - keep best chunk
        if result.is_chunk and result.score > seen_artifacts[artifact_id].score:
            merged.remove(seen_artifacts[artifact_id])
            merged.append(result)
            seen_artifacts[artifact_id] = result

# 5. Sort by score and limit
merged.sort(key=lambda x: x.score, reverse=True)
final_results = merged[:limit]

# 6. Expand neighbors if requested
if expand_neighbors:
    for result in final_results:
        if result.is_chunk:
            result.content = expand_chunk_context(result)

# 7. Format output
return format_search_results(final_results)
```

**Returns:**
```
Found 3 results:

[1] artifact: art_9f2ca8b1 (score: 0.92)
Title: Q4 Release Plan
Type: doc | Source: drive
Snippet: "...key milestones for the Q4 release include..."
Evidence: https://drive.google.com/doc/xyz

[2] chunk: art_abc123::chunk::003 (score: 0.87)
Title: Contract - Solid Base Consult
Type: email | Source: gmail
Snippet: "...payment terms are net-30 days from invoice..."
Evidence: message-id:abc123@gmail.com

[3] artifact: art_def456 (score: 0.81)
Title: Team Meeting Notes
Type: note | Source: manual
Snippet: "...discussed authentication implementation..."
```

**Error Handling:** See Section 6

---

#### 4.2.3 `artifact_get` (NEW)

**Purpose:** Retrieve artifact metadata and optionally content

**Signature:**
```python
def artifact_get(
    artifact_id: str,
    include_content: bool = False,
    include_chunks: bool = False
) -> dict
```

**Parameters:**

| Name | Type | Required | Default | Validation | Description |
|------|------|----------|---------|------------|-------------|
| `artifact_id` | string | Yes | - | Starts with "art_" | Artifact ID |
| `include_content` | boolean | No | False | - | Return full content |
| `include_chunks` | boolean | No | False | - | Return chunk list |

**Algorithm:**

```python
# 1. Fetch artifact record
artifact = get_from_collection("artifacts", artifact_id)
if not artifact:
    raise NotFoundError(f"Artifact {artifact_id} not found")

# 2. Build response
response = {
    "artifact_id": artifact.id,
    "metadata": artifact.metadata
}

# 3. Add content if requested
if include_content:
    if not artifact.metadata.is_chunked:
        response["content"] = artifact.content
    else:
        # Reconstruct from chunks
        chunks = get_chunks_by_artifact(artifact_id)
        response["content"] = reconstruct_from_chunks(chunks)

# 4. Add chunk list if requested
if include_chunks and artifact.metadata.is_chunked:
    chunks = get_chunks_by_artifact(artifact_id)
    response["chunks"] = [
        {
            "chunk_id": chunk.id,
            "chunk_index": chunk.metadata.chunk_index,
            "start_char": chunk.metadata.start_char,
            "end_char": chunk.metadata.end_char,
            "token_count": chunk.metadata.token_count
        }
        for chunk in chunks
    ]

return response
```

**Returns:**
```json
{
  "artifact_id": "art_9f2ca8b1",
  "metadata": {
    "artifact_type": "doc",
    "source_system": "drive",
    "source_id": "1a2b3c4d",
    "title": "Q4 Release Plan",
    "token_count": 5400,
    "is_chunked": true,
    "num_chunks": 6,
    "sensitivity": "normal",
    "ts": "2025-12-25T10:30:00Z"
  },
  "chunks": [
    {
      "chunk_id": "art_9f2ca8b1::chunk::000::a1b2c3d4",
      "chunk_index": 0,
      "start_char": 0,
      "end_char": 3421,
      "token_count": 900
    },
    ...
  ]
}
```

**Error Handling:** See Section 6

---

#### 4.2.4 `artifact_delete` (NEW)

**Purpose:** Delete artifact and cascade to chunks

**Signature:**
```python
def artifact_delete(artifact_id: str) -> str
```

**Parameters:**

| Name | Type | Required | Validation | Description |
|------|------|----------|------------|-------------|
| `artifact_id` | string | Yes | Starts with "art_" | Artifact ID |

**Algorithm:**

```python
# 1. Fetch artifact to check if chunked
artifact = get_from_collection("artifacts", artifact_id)
if not artifact:
    raise NotFoundError(f"Artifact {artifact_id} not found")

# 2. Delete chunks if chunked
if artifact.metadata.is_chunked:
    chunks = get_chunks_by_artifact(artifact_id)
    chunk_ids = [chunk.id for chunk in chunks]
    delete_from_collection("artifact_chunks", chunk_ids)

# 3. Delete artifact
delete_from_collection("artifacts", [artifact_id])

return f"Deleted artifact {artifact_id} and {len(chunk_ids)} chunks"
```

**Returns:**
```
"Deleted artifact art_9f2ca8b1 and 6 chunks"
```

**Error Handling:** See Section 6

---

#### 4.2.5 `hybrid_search` (NEW)

**Purpose:** Search across all collections with RRF merging

**Signature:**
```python
def hybrid_search(
    query: str,
    limit: int = 5,
    include_memory: bool = False,
    expand_neighbors: bool = False,
    filters: dict | None = None
) -> str
```

**Parameters:**

| Name | Type | Required | Default | Validation | Description |
|------|------|----------|---------|------------|-------------|
| `query` | string | Yes | - | 1-500 chars | Search query |
| `limit` | integer | No | 5 | 1-50 | Max results |
| `include_memory` | boolean | No | False | - | Include memory collection |
| `expand_neighbors` | boolean | No | False | - | Include ±1 chunks |
| `filters` | dict | No | None | - | Optional filters (artifact_type, sensitivity, etc.) |

**Algorithm:**

```python
# 1. Generate query embedding
query_embedding = generate_embedding(query)

# 2. Parallel searches with separate limits
collections_to_search = ["artifacts", "artifact_chunks"]
if include_memory:
    collections_to_search.append("memory")

all_results = {}
for collection in collections_to_search:
    results = search_collection(
        collection=collection,
        query_embedding=query_embedding,
        filters=filters,
        limit=limit * 3  # Overfetch for RRF
    )
    all_results[collection] = results

# 3. Apply RRF merging
# RRF score = Σ (1 / (k + rank)) where k=60
k = 60
merged_scores = {}

for collection, results in all_results.items():
    for rank, result in enumerate(results):
        result_id = result.id
        rrf_score = 1.0 / (k + rank + 1)

        if result_id not in merged_scores:
            merged_scores[result_id] = {
                "score": 0,
                "result": result,
                "collections": []
            }

        merged_scores[result_id]["score"] += rrf_score
        merged_scores[result_id]["collections"].append(collection)

# 4. Sort by RRF score
ranked_results = sorted(
    merged_scores.values(),
    key=lambda x: x["score"],
    reverse=True
)[:limit]

# 5. Deduplicate by artifact_id (prefer chunks)
final_results = []
seen_artifacts = set()

for item in ranked_results:
    result = item["result"]
    artifact_id = get_artifact_id(result)

    if artifact_id not in seen_artifacts:
        seen_artifacts.add(artifact_id)
        final_results.append(item)
    elif result.is_chunk:
        # Replace artifact with better chunk
        final_results = [r for r in final_results if get_artifact_id(r["result"]) != artifact_id]
        final_results.append(item)

# 6. Expand neighbors if requested
if expand_neighbors:
    for item in final_results:
        if item["result"].is_chunk:
            item["result"].content = expand_chunk_context(item["result"])

# 7. Format output
return format_hybrid_results(final_results)
```

**Returns:**
```
Found 5 results (searched: artifacts, artifact_chunks, memory):

[1] RRF score: 0.952 (from: artifacts, artifact_chunks)
Type: chunk | ID: art_9f2ca8b1::chunk::003
Title: Q4 Release Plan
Source: drive | Sensitivity: normal
Snippet: "...key milestones for the Q4 release include..."
Evidence: https://drive.google.com/doc/xyz

[2] RRF score: 0.891 (from: artifact_chunks)
Type: chunk | ID: art_abc123::chunk::002
Title: Contract Terms
Source: gmail | Sensitivity: normal
Content with neighbors:
[CHUNK BOUNDARY]
...previous context...
[CHUNK BOUNDARY]
...payment terms are net-30 days from invoice...
[CHUNK BOUNDARY]
...next context...
[CHUNK BOUNDARY]

[3] RRF score: 0.847 (from: memory)
Type: memory | ID: mem_def456
Content: User prefers Python for backend services
Confidence: 0.9
```

**Error Handling:** See Section 6

---

#### 4.2.6 `embedding_health` (NEW)

**Purpose:** Check OpenAI API status and configuration

**Signature:**
```python
def embedding_health() -> dict
```

**Parameters:** None

**Algorithm:**

```python
# 1. Check configuration
config = {
    "provider": "openai",
    "model": os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-large"),
    "dimensions": int(os.getenv("OPENAI_EMBED_DIMS", "3072")),
    "api_key_configured": bool(os.getenv("OPENAI_API_KEY"))
}

# 2. Test API with small embedding
try:
    test_embedding = generate_embedding("test")
    config["api_status"] = "healthy"
    config["test_embedding_dimensions"] = len(test_embedding)
    config["api_latency_ms"] = get_last_request_latency()
except Exception as e:
    config["api_status"] = "unhealthy"
    config["error"] = str(e)

return config
```

**Returns:**
```json
{
  "provider": "openai",
  "model": "text-embedding-3-large",
  "dimensions": 3072,
  "api_key_configured": true,
  "api_status": "healthy",
  "test_embedding_dimensions": 3072,
  "api_latency_ms": 142
}
```

**Error Handling:** See Section 6

---

## 5. Service Layer Specifications

### 5.1 EmbeddingService

**Purpose:** Centralized OpenAI embedding generation with retry logic

**Class Interface:**
```python
class EmbeddingService:
    def __init__(self, api_key: str, model: str, dimensions: int):
        pass

    def generate_embedding(self, text: str) -> list[float]:
        """Generate single embedding with retry logic"""
        pass

    def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate multiple embeddings efficiently"""
        pass

    def get_model_info(self) -> dict:
        """Return model configuration"""
        pass

    def health_check(self) -> dict:
        """Test API connectivity"""
        pass
```

**Configuration:**
- Model: `text-embedding-3-large`
- Dimensions: `3072`
- Batch size: `100` (OpenAI limit: 2048 texts or 8191 tokens each)
- Timeout: `30` seconds per request
- Retry policy: 3 attempts with exponential backoff (1s, 2s, 4s)

**Error Handling:**
- Rate limit (429): Wait and retry with exponential backoff
- Timeout: Retry up to max attempts
- Invalid input: Raise validation error (no retry)
- Auth error (401): Raise configuration error (no retry)

**Observability:**
- Log: Every embedding request (model, dimensions, token_count, latency_ms)
- Metric: Embeddings per minute
- Metric: Mean/p95/p99 latency
- Metric: Error rate by type

---

### 5.2 ChunkingService

**Purpose:** Token-window chunking with deterministic IDs

**Class Interface:**
```python
class ChunkingService:
    def __init__(self,
                 single_piece_max: int = 1200,
                 chunk_target: int = 900,
                 chunk_overlap: int = 100):
        pass

    def should_chunk(self, text: str) -> tuple[bool, int]:
        """Determine if text needs chunking. Returns (should_chunk, token_count)"""
        pass

    def chunk_text(self, text: str, artifact_id: str) -> list[Chunk]:
        """Chunk text with overlapping windows"""
        pass

    def expand_chunk_neighbors(self,
                               artifact_id: str,
                               chunk_index: int,
                               all_chunks: list[Chunk]) -> str:
        """Get chunk with ±1 neighbors and [CHUNK BOUNDARY] markers"""
        pass
```

**Chunk Data Model:**
```python
@dataclass
class Chunk:
    chunk_id: str           # art_xxx::chunk::003::c0ffee12
    artifact_id: str
    chunk_index: int
    content: str
    start_char: int
    end_char: int
    token_count: int
    content_hash: str       # SHA256 of content
```

**Chunking Algorithm:**

```python
def chunk_text(text: str, artifact_id: str) -> list[Chunk]:
    # 1. Tokenize with tiktoken (cl100k_base)
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)

    # 2. Create overlapping windows
    chunks = []
    chunk_index = 0
    pos = 0

    while pos < len(tokens):
        # Extract chunk tokens
        chunk_tokens = tokens[pos : pos + CHUNK_TARGET_TOKENS]
        chunk_text = encoding.decode(chunk_tokens)

        # Compute character offsets
        start_char = len(encoding.decode(tokens[:pos]))
        end_char = start_char + len(chunk_text)

        # Generate stable chunk ID
        content_hash = sha256(chunk_text.encode()).hexdigest()
        chunk_id = f"{artifact_id}::chunk::{chunk_index:03d}::{content_hash[:8]}"

        chunk = Chunk(
            chunk_id=chunk_id,
            artifact_id=artifact_id,
            chunk_index=chunk_index,
            content=chunk_text,
            start_char=start_char,
            end_char=end_char,
            token_count=len(chunk_tokens),
            content_hash=content_hash
        )
        chunks.append(chunk)

        # Advance position with overlap
        pos += CHUNK_TARGET_TOKENS - CHUNK_OVERLAP_TOKENS
        chunk_index += 1

    return chunks
```

**Neighbor Expansion:**

```python
def expand_chunk_neighbors(artifact_id: str,
                          chunk_index: int,
                          all_chunks: list[Chunk]) -> str:
    # Find target chunk and neighbors
    target = all_chunks[chunk_index]
    prev_chunk = all_chunks[chunk_index - 1] if chunk_index > 0 else None
    next_chunk = all_chunks[chunk_index + 1] if chunk_index < len(all_chunks) - 1 else None

    # Build combined text with markers
    parts = []

    if prev_chunk:
        parts.append(prev_chunk.content)
        parts.append("[CHUNK BOUNDARY]")

    parts.append(target.content)

    if next_chunk:
        parts.append("[CHUNK BOUNDARY]")
        parts.append(next_chunk.content)

    return "\n".join(parts)
```

---

### 5.3 RetrievalService

**Purpose:** RRF merging and deduplication

**Class Interface:**
```python
class RetrievalService:
    def __init__(self, k: int = 60):
        """k = RRF constant (standard value: 60)"""
        pass

    def merge_results_rrf(self,
                          results_by_collection: dict[str, list[SearchResult]],
                          limit: int) -> list[MergedResult]:
        """Merge multi-collection results using RRF"""
        pass

    def deduplicate_by_artifact(self,
                               results: list[MergedResult]) -> list[MergedResult]:
        """Deduplicate, preferring chunk hits over artifact hits"""
        pass
```

**RRF Algorithm:**

```python
def merge_results_rrf(results_by_collection: dict, limit: int) -> list:
    k = 60  # Standard RRF constant
    merged_scores = {}

    for collection, results in results_by_collection.items():
        for rank, result in enumerate(results):
            result_id = result.id
            rrf_score = 1.0 / (k + rank + 1)

            if result_id not in merged_scores:
                merged_scores[result_id] = {
                    "score": 0,
                    "result": result,
                    "collections": []
                }

            merged_scores[result_id]["score"] += rrf_score
            merged_scores[result_id]["collections"].append(collection)

    # Sort by aggregated RRF score
    ranked = sorted(
        merged_scores.values(),
        key=lambda x: x["score"],
        reverse=True
    )

    return ranked[:limit]
```

**Deduplication Rules:**

1. If multiple hits from same artifact, prefer chunk over full artifact
2. If multiple chunks from same artifact, keep highest RRF score
3. Maintain original rank order for non-duplicates

---

### 5.4 PrivacyFilterService (Placeholder)

**Purpose:** Hook for future privacy enforcement

**Class Interface:**
```python
class PrivacyFilterService:
    def filter_results(self,
                      results: list[SearchResult],
                      user_context: dict) -> list[SearchResult]:
        """Filter results based on visibility/sensitivity. v2: always allows"""
        pass

    def can_access_artifact(self,
                           artifact_metadata: dict,
                           user_context: dict) -> bool:
        """Check if user can access artifact. v2: always returns True"""
        pass
```

**v2 Behavior:**
```python
def filter_results(results, user_context):
    # v2: No filtering, return all results
    # TODO v3: Implement sensitivity/visibility checks
    return results

def can_access_artifact(artifact_metadata, user_context):
    # v2: Always allow
    # TODO v3: Check user_context against artifact visibility_scope
    return True
```

**v3 TODO:**
- Implement sensitivity level checks
- Implement visibility scope checks
- Add audit logging for access denials
- Support custom ACLs

---

## 6. Error Handling Matrix

### 6.1 OpenAI API Errors

| Error Code | Scenario | Retry? | Behavior | User Message |
|------------|----------|--------|----------|--------------|
| 401 | Invalid API key | No | Raise ConfigurationError | "OpenAI API key is invalid or missing. Check OPENAI_API_KEY environment variable." |
| 429 | Rate limit | Yes (3x) | Exponential backoff (1s, 2s, 4s) | "OpenAI rate limit reached. Retrying..." Then: "Failed after 3 attempts due to rate limiting. Try again later." |
| 500/502/503 | OpenAI server error | Yes (3x) | Exponential backoff | "OpenAI service temporarily unavailable. Retrying..." Then: "OpenAI service unavailable after 3 attempts." |
| Timeout | Network timeout | Yes (3x) | Exponential backoff | "Request timeout. Retrying..." Then: "Request failed after 3 timeouts." |
| 400 | Invalid input | No | Raise ValidationError | "Invalid text for embedding: {error_details}" |

### 6.2 ChromaDB Errors

| Error | Scenario | Retry? | Behavior | User Message |
|-------|----------|--------|----------|--------------|
| Connection refused | ChromaDB not running | No | Raise ConnectionError | "Cannot connect to ChromaDB at {host}:{port}. Ensure ChromaDB is running." |
| Collection not found | Race condition | No | Create collection automatically | Transparent to user |
| Duplicate ID | Re-ingestion without dedup | No | Update existing record | "Updated existing artifact {id}" |
| Invalid filter | Bad query params | No | Raise ValidationError | "Invalid filter: {error_details}" |

### 6.3 Tool-Specific Errors

#### `artifact_ingest`

| Error | Condition | HTTP Code | Message |
|-------|-----------|-----------|---------|
| ValidationError | Missing required field | 400 | "Missing required field: {field_name}" |
| ValidationError | Invalid artifact_type | 400 | "Invalid artifact_type: {value}. Must be one of: email, doc, chat, transcript, note" |
| ValidationError | Content too large | 400 | "Content exceeds maximum size of 10MB" |
| EmbeddingError | OpenAI failure (after retries) | 502 | "Failed to generate embeddings: {error}" |
| StorageError | ChromaDB write failure | 500 | "Failed to store artifact: {error}" |

#### `artifact_search`

| Error | Condition | HTTP Code | Message |
|-------|-----------|-----------|---------|
| ValidationError | Query too long | 400 | "Query exceeds maximum length of 500 characters" |
| ValidationError | Invalid limit | 400 | "Limit must be between 1 and 50" |
| EmbeddingError | OpenAI failure | 502 | "Failed to generate query embedding: {error}" |

#### `artifact_get`

| Error | Condition | HTTP Code | Message |
|-------|-----------|-----------|---------|
| NotFoundError | Artifact doesn't exist | 404 | "Artifact {artifact_id} not found" |
| ValidationError | Invalid artifact_id format | 400 | "Invalid artifact_id: must start with 'art_'" |

#### `artifact_delete`

| Error | Condition | HTTP Code | Message |
|-------|-----------|-----------|---------|
| NotFoundError | Artifact doesn't exist | 404 | "Artifact {artifact_id} not found" |
| StorageError | Cascade delete failure | 500 | "Failed to delete chunks: {error}" |

#### `hybrid_search`

| Error | Condition | HTTP Code | Message |
|-------|-----------|-----------|---------|
| ValidationError | Query too long | 400 | "Query exceeds maximum length of 500 characters" |
| EmbeddingError | OpenAI failure | 502 | "Failed to generate query embedding: {error}" |
| RetrievalError | RRF merge failure | 500 | "Failed to merge search results: {error}" |

#### `embedding_health`

| Error | Condition | HTTP Code | Message |
|-------|-----------|-----------|---------|
| ConfigurationError | No API key | 500 | "OPENAI_API_KEY not configured" |
| ConnectionError | Cannot reach OpenAI | 502 | "Cannot connect to OpenAI API" |

### 6.4 Two-Phase Atomic Write Failures

**Scenario:** Embedding generation succeeds for 4/6 chunks, then fails

**Behavior:**
1. Catch embedding failure during phase 1
2. Do NOT write any data to ChromaDB
3. Return error to user
4. Log: "Two-phase write aborted: embedding generation failed for chunk 5/6"

**User Message:**
```
"Failed to ingest artifact: embedding generation failed for 2 chunks. No data was written. Error: {openai_error}"
```

---

## 7. Configuration Specifications

### 7.1 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | - | OpenAI API authentication key |
| `OPENAI_EMBED_MODEL` | No | `text-embedding-3-large` | Embedding model name |
| `OPENAI_EMBED_DIMS` | No | `3072` | Embedding dimensions |
| `OPENAI_TIMEOUT` | No | `30` | Request timeout (seconds) |
| `OPENAI_MAX_RETRIES` | No | `3` | Max retry attempts |
| `OPENAI_BATCH_SIZE` | No | `100` | Batch embedding size |
| `SINGLE_PIECE_MAX_TOKENS` | No | `1200` | Threshold for chunking |
| `CHUNK_TARGET_TOKENS` | No | `900` | Target chunk size |
| `CHUNK_OVERLAP_TOKENS` | No | `100` | Overlap between chunks |
| `CHROMA_HOST` | No | `localhost` | ChromaDB host |
| `CHROMA_PORT` | No | `8001` | ChromaDB port |
| `MCP_PORT` | No | `3000` | MCP server port |
| `LOG_LEVEL` | No | `INFO` | Logging level |

### 7.2 Docker Compose Configuration

**File:** `docker-compose.yml`

```yaml
version: "3.8"

services:
  mcp-server:
    build: .
    container_name: mcp-memory-server
    ports:
      - "3000:3000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_EMBED_MODEL=text-embedding-3-large
      - OPENAI_EMBED_DIMS=3072
      - SINGLE_PIECE_MAX_TOKENS=1200
      - CHUNK_TARGET_TOKENS=900
      - CHUNK_OVERLAP_TOKENS=100
      - CHROMA_HOST=chroma
      - CHROMA_PORT=8000
      - MCP_PORT=3000
      - LOG_LEVEL=INFO
    depends_on:
      - chroma
    restart: unless-stopped

  chroma:
    image: chromadb/chroma:latest
    container_name: mcp-chroma
    ports:
      - "8001:8000"
    volumes:
      - chroma_data:/chroma/chroma
    environment:
      - IS_PERSISTENT=TRUE
      - ANONYMIZED_TELEMETRY=FALSE
    restart: unless-stopped

volumes:
  chroma_data:
    driver: local
```

### 7.3 Claude Desktop Configuration

**File:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "memory": {
      "url": "http://localhost:3000/mcp/"
    }
  }
}
```

---

## 8. Dependencies

### 8.1 Python Dependencies

**File:** `requirements.txt`

```txt
# MCP SDK
mcp>=1.0.0

# Web framework
uvicorn>=0.27.0
starlette>=0.36.0

# Vector database
chromadb>=0.4.22

# OpenAI client
openai>=1.12.0

# Tokenization
tiktoken>=0.6.0

# Utilities
python-dotenv>=1.0.0
pydantic>=2.5.0
```

### 8.2 Development Dependencies

```txt
# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0

# Code quality
black>=23.12.0
ruff>=0.1.9
mypy>=1.8.0

# Type stubs
types-requests>=2.31.0
```

### 8.3 System Dependencies

- Docker Engine 20.10+
- Docker Compose 2.0+
- Python 3.11+ (for local development)

---

## 9. Testing Strategy

### 9.1 Unit Tests

#### EmbeddingService Tests

```python
def test_generate_embedding_success():
    """Test successful embedding generation"""

def test_generate_embedding_retry_on_rate_limit():
    """Test retry logic for 429 errors"""

def test_generate_embedding_no_retry_on_auth_error():
    """Test no retry for 401 errors"""

def test_generate_embeddings_batch():
    """Test batch embedding generation"""
```

#### ChunkingService Tests

```python
def test_should_chunk_below_threshold():
    """Text ≤1200 tokens should not chunk"""

def test_should_chunk_above_threshold():
    """Text >1200 tokens should chunk"""

def test_chunk_text_overlaps():
    """Chunks should overlap by 100 tokens"""

def test_chunk_text_deterministic_ids():
    """Same input should produce same chunk IDs"""

def test_chunk_text_character_offsets():
    """start_char and end_char should be accurate"""

def test_expand_chunk_neighbors():
    """Should return chunk ±1 with [CHUNK BOUNDARY] markers"""
```

#### RetrievalService Tests

```python
def test_rrf_merging():
    """Test RRF score calculation"""

def test_deduplicate_prefers_chunks():
    """Deduplication should prefer chunk over artifact"""

def test_deduplicate_keeps_best_chunk():
    """Should keep highest-scoring chunk per artifact"""
```

### 9.2 Integration Tests

#### Artifact Ingestion Tests

```python
def test_ingest_small_artifact():
    """Small artifact (≤1200 tokens) stored unchunked"""
    # 1. Ingest 800-token document
    # 2. Verify stored in artifacts collection
    # 3. Verify is_chunked=False
    # 4. Verify embedding exists

def test_ingest_large_artifact():
    """Large artifact (>1200 tokens) stored with chunks"""
    # 1. Ingest 5000-token document
    # 2. Verify metadata in artifacts collection
    # 3. Verify chunks in artifact_chunks collection
    # 4. Verify chunk count matches expected
    # 5. Verify chunk overlaps

def test_ingest_idempotency():
    """Re-ingesting same source_id should no-op if unchanged"""
    # 1. Ingest artifact
    # 2. Re-ingest same artifact
    # 3. Verify no duplicate records
    # 4. Verify returned existing IDs

def test_ingest_content_change():
    """Re-ingesting with changed content should update"""
    # 1. Ingest artifact
    # 2. Re-ingest with different content
    # 3. Verify old version deleted
    # 4. Verify new version created

def test_ingest_two_phase_atomic_failure():
    """Embedding failure should not write partial data"""
    # 1. Mock OpenAI to fail on 3rd chunk
    # 2. Attempt ingestion
    # 3. Verify no data written to ChromaDB
    # 4. Verify error returned
```

#### Search Tests

```python
def test_artifact_search_unchunked():
    """Search should find unchunked artifacts"""
    # 1. Ingest small artifact
    # 2. Search for relevant query
    # 3. Verify artifact returned

def test_artifact_search_chunks():
    """Search should find relevant chunks"""
    # 1. Ingest large artifact
    # 2. Search for content in specific chunk
    # 3. Verify chunk returned, not full artifact

def test_artifact_search_neighbor_expansion():
    """expand_neighbors should return ±1 chunks"""
    # 1. Ingest large artifact
    # 2. Search with expand_neighbors=True
    # 3. Verify result includes [CHUNK BOUNDARY] markers
    # 4. Verify context from adjacent chunks

def test_hybrid_search_artifacts_only():
    """hybrid_search default should search artifacts+chunks"""
    # 1. Ingest artifacts
    # 2. Store memories
    # 3. Call hybrid_search (default: include_memory=False)
    # 4. Verify only artifact results returned

def test_hybrid_search_with_memory():
    """hybrid_search with include_memory should merge all"""
    # 1. Ingest artifacts
    # 2. Store memories
    # 3. Call hybrid_search with include_memory=True
    # 4. Verify results from both artifacts and memory
    # 5. Verify RRF scoring applied

def test_hybrid_search_deduplication():
    """Hybrid search should deduplicate by artifact_id"""
    # 1. Ingest artifact that matches in both full and chunk
    # 2. Search
    # 3. Verify only one result per artifact
    # 4. Verify chunk preferred over full artifact
```

#### Retrieval Tests

```python
def test_artifact_get_unchunked():
    """artifact_get should return full content for small docs"""
    # 1. Ingest small artifact
    # 2. Call artifact_get with include_content=True
    # 3. Verify full content returned

def test_artifact_get_chunked_reconstructed():
    """artifact_get should reconstruct from chunks"""
    # 1. Ingest large artifact
    # 2. Call artifact_get with include_content=True
    # 3. Verify content reconstructed from chunks
    # 4. Verify matches original content

def test_artifact_get_chunk_list():
    """artifact_get with include_chunks should list chunks"""
    # 1. Ingest large artifact
    # 2. Call artifact_get with include_chunks=True
    # 3. Verify chunk metadata list returned
```

#### Delete Tests

```python
def test_artifact_delete_unchunked():
    """Delete should remove unchunked artifact"""
    # 1. Ingest small artifact
    # 2. Delete
    # 3. Verify artifact removed from collection

def test_artifact_delete_cascade():
    """Delete should cascade to chunks"""
    # 1. Ingest large artifact (creates chunks)
    # 2. Delete artifact
    # 3. Verify artifact removed
    # 4. Verify all chunks removed
    # 5. Verify no orphan chunks
```

### 9.3 Regression Tests

#### Existing Tool Compatibility

```python
def test_memory_store_with_openai():
    """memory_store should work with OpenAI embeddings"""
    # 1. Call memory_store
    # 2. Verify embedding generated via OpenAI
    # 3. Verify stored with correct metadata

def test_memory_search_with_openai():
    """memory_search should work with OpenAI embeddings"""
    # 1. Store memory with OpenAI embeddings
    # 2. Search with query
    # 3. Verify results returned

def test_history_append_with_openai():
    """history_append should work with OpenAI embeddings"""
    # 1. Append history turn
    # 2. Verify embedding generated via OpenAI

def test_history_get():
    """history_get should retrieve turns in order"""
    # 1. Append multiple turns
    # 2. Retrieve history
    # 3. Verify correct order and content
```

### 9.4 Performance Tests

```python
def test_embedding_latency():
    """Embedding generation should complete within timeout"""
    # Target: <500ms per embedding

def test_batch_embedding_efficiency():
    """Batch embeddings should be more efficient than sequential"""
    # Compare batch vs sequential for 10 texts

def test_search_latency():
    """Search should complete within acceptable time"""
    # Target: <200ms for single collection, <500ms for hybrid

def test_large_artifact_ingestion():
    """Ingest 10MB document should complete successfully"""
    # Verify chunking, embedding, storage
```

### 9.5 Test Data

**Location:** `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/temp/example documents/`

**Available Test Documents:**
1. `Claude code Bible.pdf` (14.9 MB) - Large technical document
2. `6e release plan.pdf` (9.5 MB) - Multi-page planning doc
3. `Achilefs - Contract - Solid Base Consult.pdf` (149 KB) - Contract
4. `Grzegorz-Kaczorek-CV-2025-09-18.pdf` (54 KB) - Resume
5. Multiple smaller PDFs (bylaws, contracts, meeting minutes)

**Test Scenarios:**
- Small document (≤1200 tokens): Contract PDFs
- Medium document (1200-5000 tokens): Meeting minutes
- Large document (>5000 tokens): Technical documentation
- Edge cases: Empty content, special characters, very long lines

---

## 10. Observability

### 10.1 Structured Logging

**Format:** JSON structured logs

**Fields:**
```json
{
  "timestamp": "2025-12-25T10:30:00.123Z",
  "level": "INFO",
  "service": "mcp-memory",
  "component": "EmbeddingService",
  "event": "embedding_generated",
  "model": "text-embedding-3-large",
  "dimensions": 3072,
  "token_count": 142,
  "latency_ms": 234,
  "batch_size": 1,
  "trace_id": "abc123"
}
```

**Log Levels:**
- `DEBUG`: Detailed debugging (tokenization, chunk boundaries)
- `INFO`: Normal operations (ingestion, search, embedding generation)
- `WARNING`: Recoverable errors (retries, deduplication)
- `ERROR`: Failures requiring attention (API errors, storage failures)
- `CRITICAL`: Service-level failures (cannot connect to ChromaDB/OpenAI)

### 10.2 Key Events to Log

#### Embedding Events
```python
logger.info("embedding_requested", {
    "model": "text-embedding-3-large",
    "input_length": len(text),
    "token_count": token_count
})

logger.info("embedding_generated", {
    "model": "text-embedding-3-large",
    "dimensions": 3072,
    "latency_ms": latency,
    "token_count": token_count
})

logger.warning("embedding_retry", {
    "attempt": 2,
    "error": "rate_limit",
    "backoff_ms": 2000
})

logger.error("embedding_failed", {
    "attempts": 3,
    "error": error_message
})
```

#### Ingestion Events
```python
logger.info("artifact_ingest_started", {
    "artifact_id": "art_9f2ca8b1",
    "artifact_type": "doc",
    "source_system": "drive",
    "token_count": 5400,
    "will_chunk": True
})

logger.info("artifact_chunked", {
    "artifact_id": "art_9f2ca8b1",
    "num_chunks": 6,
    "chunk_size_avg": 900,
    "overlap": 100
})

logger.info("artifact_ingest_completed", {
    "artifact_id": "art_9f2ca8b1",
    "is_chunked": True,
    "num_chunks": 6,
    "total_latency_ms": 3421
})
```

#### Search Events
```python
logger.info("search_started", {
    "tool": "hybrid_search",
    "query_length": len(query),
    "collections": ["artifacts", "artifact_chunks"],
    "include_memory": False
})

logger.info("search_completed", {
    "tool": "hybrid_search",
    "results_count": 5,
    "latency_ms": 342,
    "collections_searched": ["artifacts", "artifact_chunks"],
    "rrf_applied": True
})
```

### 10.3 Metrics (Optional but Recommended)

**Embedding Metrics:**
- `embeddings_total` (counter) - Total embeddings generated
- `embeddings_failed_total` (counter) - Failed embeddings by error type
- `embedding_latency_seconds` (histogram) - Latency distribution
- `embedding_tokens_total` (counter) - Total tokens embedded
- `embedding_batch_size` (histogram) - Batch size distribution

**Ingestion Metrics:**
- `artifacts_ingested_total` (counter) - Total artifacts ingested
- `artifacts_chunked_total` (counter) - Artifacts that required chunking
- `artifact_chunks_total` (counter) - Total chunks created
- `ingestion_latency_seconds` (histogram) - End-to-end ingestion time

**Search Metrics:**
- `searches_total` (counter) - Total searches by tool
- `search_latency_seconds` (histogram) - Search latency by tool
- `search_results_count` (histogram) - Result count distribution
- `rrf_merges_total` (counter) - Hybrid searches with RRF

**Storage Metrics:**
- `chroma_operations_total` (counter) - Operations by type (add, query, delete)
- `chroma_errors_total` (counter) - Errors by type

### 10.4 Health Checks

**Endpoint:** `/health`

**Response:**
```json
{
  "status": "healthy",
  "service": "mcp-memory",
  "version": "2.0.0",
  "checks": {
    "chromadb": {
      "status": "healthy",
      "latency_ms": 12
    },
    "openai": {
      "status": "healthy",
      "model": "text-embedding-3-large",
      "dimensions": 3072,
      "latency_ms": 234
    }
  },
  "timestamp": "2025-12-25T10:30:00Z"
}
```

---

## 11. Migration & Deployment

### 11.1 Deployment Steps

**Prerequisites:**
1. Docker Engine 20.10+ installed
2. Docker Compose 2.0+ installed
3. OpenAI API key obtained

**Steps:**

```bash
# 1. Stop v1 services
cd /path/to/mcp-server
docker compose down

# 2. Wipe ChromaDB volume (CLEAN SLATE)
docker volume rm mcp-server_chroma_data

# 3. Update environment variables
cat > .env <<EOF
OPENAI_API_KEY=sk-your-key-here
OPENAI_EMBED_MODEL=text-embedding-3-large
OPENAI_EMBED_DIMS=3072
SINGLE_PIECE_MAX_TOKENS=1200
CHUNK_TARGET_TOKENS=900
CHUNK_OVERLAP_TOKENS=100
EOF

# 4. Build and start v2 services
docker compose build
docker compose up -d

# 5. Verify health
curl http://localhost:3000/health

# 6. Test embedding_health tool
# Use Claude to call: embedding_health

# 7. Update Claude Desktop config (if needed)
# File: ~/Library/Application Support/Claude/claude_desktop_config.json
# Should point to: http://localhost:3000/mcp/
```

### 11.2 Rollback Plan

If v2 deployment fails:

```bash
# 1. Stop v2 services
docker compose down

# 2. Checkout v1 code
git checkout v1-tag

# 3. Restore v1 ChromaDB volume (if backup exists)
docker volume create mcp-server_chroma_data
docker run --rm -v mcp-server_chroma_data:/data -v $(pwd)/backup:/backup \
  alpine tar xzf /backup/chroma_backup.tar.gz -C /data

# 4. Start v1 services
docker compose up -d
```

**Note:** v2 is a clean slate. No v1 data to preserve.

### 11.3 Smoke Tests Post-Deployment

1. **Health Check:**
   ```bash
   curl http://localhost:3000/health
   # Expected: {"status": "healthy", ...}
   ```

2. **Embedding Health:**
   - Call `embedding_health` tool via Claude
   - Verify: `api_status: "healthy"`, `dimensions: 3072`

3. **Memory Store & Search:**
   - Store memory: `memory_store("Test memory", "fact", 1.0)`
   - Search: `memory_search("test")`
   - Verify: Memory returned in results

4. **Artifact Ingestion:**
   - Ingest small artifact (≤1200 tokens)
   - Verify: `is_chunked: false`
   - Ingest large artifact (>1200 tokens)
   - Verify: `is_chunked: true`, `num_chunks > 0`

5. **Hybrid Search:**
   - Call `hybrid_search` with query
   - Verify: Results returned with RRF scores

---

## 12. API Contracts

### 12.1 Tool Response Formats

#### Success Response (String Tools)

```
"Stored memory [mem_abc123def456]: User prefers dark mode..."
```

#### Success Response (Dict Tools)

```json
{
  "artifact_id": "art_9f2ca8b1",
  "is_chunked": true,
  "num_chunks": 6,
  "stored_ids": ["art_9f2ca8b1", "art_9f2ca8b1::chunk::000::..."]
}
```

#### Error Response

All tools return error messages as strings in format:
```
"Failed to {action}: {error_details}"
```

Examples:
- `"Failed to store memory: OpenAI rate limit reached after 3 retries"`
- `"Failed to ingest artifact: embedding generation failed"`
- `"Artifact art_xyz not found"`

### 12.2 Search Result Format

#### `memory_search` / `artifact_search`

```
Found {N} results:

[1] [{id}] ({type}, conf={confidence}): {content_snippet}
[2] ...
```

#### `hybrid_search`

```
Found {N} results (searched: {collections}):

[1] RRF score: {score} (from: {collections})
Type: {type} | ID: {id}
Title: {title}
Source: {source_system} | Sensitivity: {sensitivity}
Snippet: "{content_snippet}"
Evidence: {source_url}

[2] ...
```

### 12.3 Metadata Contracts

All metadata dictionaries returned by `artifact_get` must include:

**Required Fields:**
- `artifact_type`
- `source_system`
- `ts`
- `content_hash`
- `token_count`
- `is_chunked`
- `embedding_provider`
- `embedding_model`
- `embedding_dimensions`

**Optional Fields:**
- `source_id`
- `source_url`
- `title`
- `author`
- `participants`
- `num_chunks` (required if `is_chunked=true`)
- `sensitivity`
- `visibility_scope`
- `retention_policy`

---

## 13. Future Enhancements (v2.1+)

### 13.1 v2.1 - Structure-Aware Chunking

**Goal:** Improve chunk quality by respecting document structure

**Features:**
- Email: Split by reply blocks, quoted sections
- Markdown: Split by headings (h1, h2, h3)
- Chat logs: Split by speaker turns
- Code: Split by functions/classes
- Fallback: Token-window (current approach)

**Decision:** Deferred to allow faster v2.0 delivery

---

### 13.2 v3 - Multi-User & Privacy Enforcement

**Goal:** Support multiple users with privacy enforcement

**Features:**
- User authentication and sessions
- Enforce `sensitivity` filtering at retrieval time
- Enforce `visibility_scope` based on user context
- Audit logging for access denials
- Custom ACLs for `custom` visibility scope

**Decision:** Deferred to focus on core functionality

---

### 13.3 Phase 3 - Event Extraction

**Goal:** Extract and index structured events from artifacts

**Features:**
- LLM-based event extraction (decisions, actions, milestones)
- `event_summaries` collection for high-precision retrieval
- Event timeline visualization
- Event-centric search

**Decision:** Requires stable artifact foundation from v2

---

### 13.4 Phase 4 - Kafka & Graph

**Goal:** Add immutable event log and relationship tracking

**Features:**
- Kafka as immutable append-only log
- Graph database for entity relationships
- Temporal queries (what changed between dates?)
- Entity resolution (merge duplicate mentions)

**Decision:** Significant infrastructure investment, deferred

---

## 14. Appendices

### Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Artifact** | A document, email, chat, or other ingested text source |
| **Chunk** | A segment of an artifact split for embedding (900 tokens) |
| **RRF** | Reciprocal Rank Fusion - algorithm for merging ranked lists |
| **Two-Phase Write** | Generate all embeddings first, then write to DB atomically |
| **Neighbor Expansion** | Including ±1 chunks around a result for context |
| **Clean Slate** | Wiping all v1 data without migration |
| **BYO Embeddings** | "Bring Your Own" - server generates embeddings, not ChromaDB |

### Appendix B: Token Counting Reference

**Tokenizer:** tiktoken with `cl100k_base` encoding

**Approximate Token Counts:**
- 1 token ≈ 4 characters (English text)
- 1 token ≈ ¾ words (English text)
- 1200 tokens ≈ 4800 characters ≈ 900 words
- 900 tokens ≈ 3600 characters ≈ 675 words

**Example:**
```python
import tiktoken

encoding = tiktoken.get_encoding("cl100k_base")
text = "Your document text here"
token_count = len(encoding.encode(text))
```

### Appendix C: RRF Formula

**Reciprocal Rank Fusion (RRF):**

```
score(doc) = Σ_collections (1 / (k + rank_in_collection))
```

Where:
- `k = 60` (standard constant)
- `rank_in_collection` = position in that collection's results (0-indexed)

**Example:**
- Document appears at rank 2 in `artifacts` and rank 5 in `artifact_chunks`
- RRF score = (1 / (60 + 2)) + (1 / (60 + 5)) = 0.0161 + 0.0154 = 0.0315

### Appendix D: Content Hash Calculation

**Algorithm:** SHA256

**Python Implementation:**
```python
import hashlib

def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()
```

**Example:**
```python
content = "User prefers dark mode"
hash = compute_content_hash(content)
# Result: "3f8a7bc9d2e1f4a5b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5"
```

### Appendix E: Chunk Boundary Marker Format

**Format:**
```
{previous_chunk_content}
[CHUNK BOUNDARY]
{target_chunk_content}
[CHUNK BOUNDARY]
{next_chunk_content}
```

**Example:**
```
...end of previous chunk discussing project timeline...
[CHUNK BOUNDARY]
The Q4 release milestones include: feature freeze on Oct 15, code complete on Nov 1, and launch on Dec 1. Each milestone has specific acceptance criteria...
[CHUNK BOUNDARY]
...start of next chunk discussing testing requirements...
```

---

## 15. Approval & Sign-Off

This technical specification is ready for:

1. **Architecture Review** - Senior Architect to validate design decisions
2. **Implementation** - Lead Backend Engineer to begin development
3. **QA Planning** - Test Automation Engineer to design test suites

**Next Steps:**
1. Architecture review meeting
2. Create implementation tickets from Section 17 checklist
3. Set up development environment
4. Begin EmbeddingService implementation

---

**Document Status:** ✅ Draft Complete - Ready for Review

**Generated by:** Technical PM
**Date:** 2025-12-25
**Version:** 1.0
