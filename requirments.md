# Nur Memory MCP — v2 Implementation Spec (OpenAI Embeddings + Artifact Ingestion + Hybrid Retrieval)

This document is the single source of truth for the next implementation step for `nur_memory_mcp`.

**IMPORTANT: v2 is a clean slate implementation. All existing v1 data will be wiped. No migration required.**

The v2 goal is to upgrade embeddings to OpenAI (best quality), add artifact ingestion (docs/emails/chat as "evidence"), and implement a retrieval flow that scales beyond "everything is a memory snippet".

---

## 1) Goals

### 1.1 Functional goals
1) Use OpenAI embeddings for all vector writes:
   - Default model: `text-embedding-3-large`
   - Default dimensions: 3072 (tunable later)
2) Add “Artifacts” as a first-class concept:
   - Store full text (email/doc/chat transcript) with metadata + provenance
   - Automatically chunk long artifacts based on token threshold
   - Maintain chunk offsets for deterministic reconstruction and neighbor expansion
3) Implement Hybrid Retrieval:
   - Query across `memory`, `history`, and artifact-derived vectors (full artifacts + chunks)
   - Return ranked results with provenance/evidence pointers
4) Keep everything Docker-first and replayable.

### 1.2 Quality goals
- Retrieval precision: return the *right passage*, not just the right document.
- Auditability: every answer can point back to concrete evidence (artifact pointers).
- Determinism: re-running ingestion does not duplicate records.
- Upgradeability: switch embedding dims/model later without redesign.

---

## 2) Non-goals (for this step)
- Kafka event log and stream processing (future phase)
- Graph DB integration (future phase)
- Automated HR decisions (avoid "judgement engine")
- OCR / heavy document parsing pipelines (can be phased in later)
- Migration of v1 data (clean slate approach)
- Structure-aware chunking (deferred to v2.1)
- Multi-user authentication (deferred to v3)
- Artifact versioning history (deferred to v3)

---

## 2.1) Implementation Decisions (Clarifications)

These decisions resolve ambiguities in the spec:

### Migration Strategy
- **Clean slate**: Wipe all existing v1 collections on deployment
- No migration scripts needed
- All collections use OpenAI embeddings from day one

### Hybrid Search
- Implement as **NEW tool**: `hybrid_search`
- **Default behavior**: Search `artifacts` + `artifact_chunks` only
- **Optional**: `include_memory=True` adds memory collection to search
- **Score merging**: Use **RRF (Reciprocal Rank Fusion)** instead of min-max normalization
  - RRF formula: `score = Σ (1 / (k + rank))` where k=60 (standard constant)
  - More robust to score distribution differences across collections

### Chunking Strategy
- **v2.0**: Token-window chunking ONLY (structure-aware deferred to v2.1)
- **Fallback is the default** — messy real-world text rarely has clean structure
- **Thresholds**:
  - ≤1200 tokens: store as single piece
  - >1200 tokens: chunk with 900 token target + 100 token overlap
- **Tokenizer**: `tiktoken` with `cl100k_base` encoding (matches OpenAI models)

### Neighbor Expansion
- **Off by default** to keep responses tight and avoid prompt bloat
- `expand_neighbors=True` fetches ±1 adjacent chunks
- **Output format**: Combined text with `[CHUNK BOUNDARY]` markers for transparency

### Privacy
- **Store all metadata now**: `sensitivity`, `visibility_scope`, `retention_policy`
- **Chunks inherit** from parent artifact
- **v2 behavior**: Single user assumed, no runtime filtering
- **v2 hook**: Add retrieval-time filter hook that **always allows** (placeholder)
  - Enforcement becomes a config flip in v3, not a refactor

### Versioning
- **v2 behavior**: Delete + insert on content change (no version history)
- **Always store**: `content_hash` and `ingested_at` for basic traceability
- Full version history deferred to v3

### OpenAI Error Handling
- **Retries**: 3 attempts with exponential backoff (1s, 2s, 4s)
- **Two-phase atomic writes**:
  1. Generate ALL embeddings successfully first
  2. Only then write to Chroma
  - Guarantees atomic behavior without transactions
- **`embedding_health` tool**: Returns model name, dimensions, and live API status

---

## 3) High-level Architecture (v2)

Claude -> MCP over HTTP/SSE -> MCP Memory Server
  -> Embedding Service (OpenAI)
  -> ChromaDB collections:
       - memory
       - history
       - artifacts
       - artifact_chunks
       - (optional) event_summaries

Key change: Chroma must NOT auto-embed. MCP server generates embeddings and writes vectors explicitly.

---

## 4) Collections & Purpose

### 4.1 `memory`
Small, durable semantic items (preferences, facts, decisions, projects).

### 4.2 `history`
Conversation turns keyed by `conversation_id` and `turn_index`.

### 4.3 `artifacts` (NEW)
Stores full artifact text as a single vector doc *only when small enough* (≤ threshold).
Also stores artifact metadata even if chunked.

### 4.4 `artifact_chunks` (NEW)
Stores chunk vectors for large artifacts (> threshold).
Each chunk carries offsets and stable IDs.

### 4.5 `event_summaries` (Optional, recommended later)
Compact summaries of extracted “events” for high-precision retrieval.
Not required in this implementation step.

---

## 5) Chunking Policy (Token Threshold Rule)

### 5.1 Defaults (quality-first)
- `SINGLE_PIECE_MAX_TOKENS = 1200`
- `CHUNK_TARGET_TOKENS = 900`
- `CHUNK_OVERLAP_TOKENS = 100`

### 5.2 Behavior
- If artifact token_count ≤ 1200:
  - store in `artifacts` as one record (one embedding)
- If artifact token_count > 1200:
  - store artifact metadata in `artifacts` with `is_chunked=true` and either:
    - omit embedding for the full artifact OR store a short synopsis embedding (phase 2)
  - store chunks in `artifact_chunks` with offsets and embeddings

### 5.3 Chunking method (do not do naive fixed windows first if avoidable)
Prefer structure-aware chunking:
- Email: split by reply blocks / quoted sections
- Markdown: split by headings
- Chat logs: split by speaker turns
Fallback: token-window chunking with overlap.

### 5.4 Deterministic chunk identity
Chunk IDs must be stable for re-ingestion:
- `chunk_id = {artifact_id}::chunk::{chunk_index}::{content_hash_prefix}`
Store:
- `chunk_index`
- `start_char`, `end_char` offsets (or token offsets if available)
- `content_hash` (sha256 of chunk content)

---

## 6) Data Models

### 6.1 Memory document
```json
{
  "id": "mem_abc123def456",
  "content": "User prefers dark mode and Python over JavaScript",
  "metadata": {
    "type": "preference",
    "confidence": 0.9,
    "ts": "2025-12-25T10:30:00",
    "conversation_id": "optional-context",

    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072,
    "token_count": 142
  }
}

6.2 History document

{
  "id": "conv123_turn_0",
  "content": "user: How do I implement auth?",
  "metadata": {
    "conversation_id": "conv123",
    "role": "user",
    "turn_index": 0,
    "ts": "2025-12-25T10:30:00",

    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072,
    "token_count": 12
  }
}

6.3 Artifact document (NEW)

Represents an ingested “source” (email/doc/chat file). This record always exists even if chunked.

{
  "id": "art_9f2c",
  "content": "Full text content (only if small enough) OR empty/omitted if chunked",
  "metadata": {
    "artifact_type": "email | doc | chat | transcript | note",
    "source_system": "gmail | slack | drive | manual",
    "source_id": "message-id/doc-id/thread-id",
    "source_url": "optional",
    "ts": "2025-12-25T10:30:00",

    "title": "optional subject/title",
    "author": "optional",
    "participants": ["optional"],

    "content_hash": "sha256(full_text)",
    "token_count": 5400,
    "is_chunked": true,

    "sensitivity": "normal | sensitive | highly_sensitive",
    "visibility_scope": "me | team | org | custom",
    "retention_policy": "forever | 1y | until_resolved | custom",

    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072
  }
}

6.4 Artifact chunk document (NEW)

{
  "id": "art_9f2c::chunk::003::c0ffee12",
  "content": "…chunk text…",
  "metadata": {
    "artifact_id": "art_9f2c",
    "chunk_index": 3,
    "start_char": 8421,
    "end_char": 11290,
    "token_count": 910,
    "content_hash": "sha256(chunk_text)",
    "ts": "2025-12-25T10:30:00",

    "sensitivity": "inherit_from_artifact",
    "visibility_scope": "inherit_from_artifact",
    "retention_policy": "inherit_from_artifact",

    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    "embedding_dimensions": 3072
  }
}


⸻

7) MCP Tooling (Additions for v2)

Existing tools remain unchanged.

7.1 New tools

artifact_ingest
Ingest a large text (email/document/chat transcript) and store appropriately.
Inputs:
	•	artifact_type
	•	source_system
	•	source_id
	•	title (optional)
	•	ts
	•	content (full text)
	•	sensitivity, visibility_scope, retention_policy (optional, defaults)
Behavior:
	•	compute content_hash
	•	token_count
	•	if ≤ threshold: embed once and store in artifacts
	•	if > threshold: store metadata in artifacts, chunk + embed and store in artifact_chunks
Output:
	•	artifact_id
	•	is_chunked
	•	num_chunks
	•	stored_ids list

artifact_search
Semantic search across artifacts and chunks.
Inputs:
	•	query
	•	limit
	•	optional filters: artifact_type, source_system, sensitivity, visibility_scope, time range
Behavior:
	•	search artifacts (small ones) and artifact_chunks
	•	merge results by score with dedupe rules
Output:
	•	ranked hits including artifact_id, chunk_id (if applicable), score, snippet, evidence pointers

artifact_get
Fetch artifact metadata and optionally content (or chunk list).
Inputs:
	•	artifact_id
	•	include_content (bool)
	•	include_chunks (bool)
Output:
	•	artifact record plus optional chunk metadata list

artifact_delete
Delete artifact and all chunks (cascade).
Inputs:
	•	artifact_id

7.2 Optional “quality control” tools (nice-to-have)
	•	embedding_health (tests OpenAI key/model; returns version/config)
	•	artifact_reembed (re-embed by artifact_id when changing dims/model later)

⸻

8) Hybrid Retrieval Logic (v2)

8.1 Query flow (recommended default)

When memory_search (or a new hybrid_search) is called:
	1.	Vector search memory (top K)
	2.	Vector search history scoped to relevant conversation_id if provided (top K)
	3.	Vector search artifacts (top K)
	4.	Vector search artifact_chunks (top K)
	5.	Merge + rank:
	•	prefer chunk hits over artifact hits when same artifact matches
	•	dedupe by artifact_id with “best snippet wins”
	6.	Neighbor expansion (for chunk hits):
	•	fetch chunk_index-1 and chunk_index+1 if present
	•	return expanded text block for better answer context

8.2 Output format (for LLM consumption)

Each hit should include:
	•	type: memory | history | artifact | artifact_chunk
	•	id
	•	score
	•	content_snippet
	•	evidence: source pointers (source_system/source_id/source_url)
	•	provenance: embedding model/dims, ts, confidence if relevant

⸻

9) OpenAI Embeddings Integration

9.1 Embedding client responsibilities
	•	single place for:
	•	model name
	•	dimensions (optional)
	•	batching
	•	retries/backoff
	•	telemetry (latency, token_count)

9.2 Chroma usage

Use “bring-your-own embeddings”:
	•	generate embeddings in MCP server
	•	call Chroma add(..., embeddings=[...])

9.3 Token counting
	•	Must compute approximate token count to enforce thresholds.
	•	Implementation options:
	•	Use a tokenizer library compatible with OpenAI tokenization (preferred)
	•	Fallback heuristic if needed (acceptable short-term, but log uncertainty)

⸻

10) Idempotency & Deduplication

10.1 Artifact identity

Compute a stable artifact id (or store separately):
	•	artifact_id = "art_" + short_hash(source_system + source_id)
Dedup key:
	•	source_system + source_id is canonical if available
	•	else fallback to content_hash

10.2 Re-ingestion behavior

If an artifact with same source_system+source_id exists:
	•	if content_hash unchanged: no-op (return existing ids)
	•	if changed: create new version:
	•	artifact_version increments
	•	old version may be retained depending on retention policy

10.3 Chunk identity

Stable chunk ids as described in section 5.4.

⸻

11) Privacy, Visibility, and Safety (Personal Life Ready)

Personal domains (medical, relationships, children) require first-class controls.
Minimum required metadata on artifacts and derived chunks:
	•	sensitivity
	•	visibility_scope
	•	retention_policy

Enforcement rule:
	•	Filtering happens at retrieval time:
	•	if caller scope does not match visibility_scope, do not return item
	•	If scope is not implemented yet, default to “me only” for sensitive/highly_sensitive.

Kids/medical:
	•	Default sensitivity = highly_sensitive
	•	Default visibility_scope = me
	•	Default retention configurable

⸻

12) Deployment (Docker Compose)

12.1 Services (v2)
	•	mcp-server
	•	chroma

No additional services required in this step.

12.2 New env vars
	•	OPENAI_API_KEY (required)
	•	OPENAI_EMBED_MODEL=text-embedding-3-large
	•	OPENAI_EMBED_DIMS=3072 (optional)
	•	SINGLE_PIECE_MAX_TOKENS=1200
	•	CHUNK_TARGET_TOKENS=900
	•	CHUNK_OVERLAP_TOKENS=100

⸻

13) Testing Plan

13.1 Unit tests
	•	token counter
	•	chunker:
	•	deterministic chunk boundaries
	•	correct overlaps
	•	correct offsets
	•	embedding client:
	•	mock OpenAI call
	•	handles batch sizes
	•	retry/backoff behavior

13.2 Integration tests
	•	artifact_ingest small (≤ threshold) stores in artifacts and retrievable
	•	artifact_ingest large (> threshold) stores metadata + chunks and retrievable
	•	artifact_search returns chunk hits with neighbor expansion
	•	memory_search hybrid merge ranking (if implemented)

13.3 Regression tests
	•	existing memory/history tools still work
	•	no duplicate inserts after repeated ingestion of same artifact

⸻

14) Observability & Ops

Minimum logging:
	•	embedding calls: latency, token_count, batch size, model, dims
	•	ingestion: artifact_id, source_id, is_chunked, num_chunks
	•	search: query, collections searched, counts, top scores

Metrics (optional but recommended):
	•	embeddings per minute
	•	mean embedding latency
	•	search latency per collection

⸻

15) Migration Notes (v1 -> v2)

**Decision: Clean Slate — No Migration**

Wipe all v1 data on deployment.

Rationale:
- v1 was experimental with minimal stored data
- Embedding dimension mismatch (384 vs 3072) makes migration complex
- Clean slate allows simpler, more robust implementation
- All collections start fresh with OpenAI embeddings

**Deployment step**:
```bash
# Wipe ChromaDB volume before starting v2
docker volume rm mcp-server_chroma_data
docker compose up -d
```

⸻

16) Roadmap After v2 (Future Phases)

Phase 3: Event-centric extraction + summaries
	•	Extract “events” from artifacts and history
	•	Store event_summaries vectors for high precision

Phase 4: Kafka + Graph
	•	Kafka as immutable log
	•	Graph DB (open-source) for relationships and timelines
	•	Recommended candidates for later evaluation:
	•	Apache AGE (Postgres extension)
	•	Neo4j Community (GPL)
	•	JanusGraph/HugeGraph/NebulaGraph (heavier ops)

⸻

17) Implementation Checklist (Ticket-ready)
	1.	Wipe existing ChromaDB data (clean slate)
	2.	Add OpenAI embedding client module (with retry/backoff)
	3.	Add token counting with tiktoken (cl100k_base)
	4.	Update all write paths to use BYO embeddings into Chroma
	5.	Add collections: artifacts, artifact_chunks
	6.	Implement chunking policy (token-window, ≤1200 single / 900+100 overlap)
	7.	Implement MCP tools:
	•	artifact_ingest (with two-phase atomic write)
	•	artifact_search (with neighbor expansion option)
	•	artifact_get
	•	artifact_delete (cascade to chunks)
	•	hybrid_search (RRF merging, artifacts+chunks default, memory optional)
	•	embedding_health (API status check)
	8.	Add retrieval-time filter hook (placeholder, always allows)
	9.	Add tests (unit + integration)
	10.	Update README with v2 usage

⸻

18) Acceptance Criteria
	•	System runs via Docker Compose with OpenAI embeddings enabled
	•	All collections use OpenAI text-embedding-3-large (3072 dims)
	•	artifact_ingest correctly stores small texts (≤1200 tokens) unchunked
	•	artifact_ingest correctly chunks large texts (>1200 tokens) with 100 token overlap
	•	artifact_search returns relevant passages with evidence pointers
	•	hybrid_search merges results from artifacts + chunks using RRF
	•	Neighbor expansion returns ±1 chunks with [CHUNK BOUNDARY] markers
	•	No duplicate records on re-ingestion of same source_system+source_id
	•	embedding_health returns API status and model info
	•	Two-phase atomic writes: no partial data on embedding failure
	•	Existing memory/history tools work with OpenAI embeddings

End.


