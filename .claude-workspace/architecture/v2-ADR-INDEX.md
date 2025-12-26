# MCP Memory Server v2.0 - Architecture Decision Records Index

**Date:** 2025-12-25
**Author:** Senior Architect
**Status:** Complete

---

## Overview

This directory contains Architecture Decision Records (ADRs) for the MCP Memory Server v2.0 rewrite. The v2.0 release is a **clean-slate rewrite** that upgrades from ChromaDB auto-embeddings to OpenAI text-embedding-3-large, introduces artifact ingestion with intelligent chunking, and implements hybrid search with RRF merging.

---

## v2.0 ADRs

### ADR-001: OpenAI Embedding Strategy

**File:** `ADR-001-embedding-strategy.md`

**Status:** Accepted

**Summary:** Migrates from ChromaDB's automatic embeddings (384 dimensions) to OpenAI's text-embedding-3-large (3072 dimensions) for higher quality semantic search. Introduces a centralized EmbeddingService with retry logic, batch coordination, and observability.

**Key Decisions:**
- Use OpenAI text-embedding-3-large (3072 dimensions)
- Implement retry logic with exponential backoff (3 attempts)
- Batch embedding generation (up to 100 texts per batch)
- Track latency, token count, and error rates for observability

**Consequences:**
- **Pros:** Higher quality embeddings, full control over embedding generation, resilience to transient failures
- **Cons:** Additional cost ($0.13 per 1M tokens), network latency, dependency on external API

**Related ADRs:** ADR-002 (uses EmbeddingService for chunks), ADR-004 (service layer design)

---

### ADR-002: Token-Window Chunking Architecture

**File:** `ADR-002-chunking-architecture.md`

**Status:** Accepted

**Summary:** Implements intelligent chunking for large artifacts (>1200 tokens) using token-window strategy with overlap. Small documents (≤1200 tokens) stored unchunked, large documents split into 900-token chunks with 100-token overlap for context continuity.

**Key Decisions:**
- Threshold: 1200 tokens (unchunked vs chunked)
- Chunk size: 900 tokens target
- Overlap: 100 tokens between adjacent chunks
- Use tiktoken cl100k_base encoding (same as GPT-4)
- Deterministic chunk IDs for idempotency
- Support neighbor expansion (±1 chunks with [CHUNK BOUNDARY] markers)

**Consequences:**
- **Pros:** Better retrieval precision, handles arbitrarily large documents, context preservation through overlap
- **Cons:** 11% storage overhead from overlap, reconstruction cost for full documents

**Related ADRs:** ADR-001 (embeddings), ADR-003 (searches both artifacts and chunks), ADR-004 (ChunkingService design)

**Future:** v2.1 will add structure-aware chunking (email blocks, markdown headings, etc.)

---

### ADR-003: Hybrid Retrieval with RRF Merging

**File:** `ADR-003-hybrid-retrieval.md`

**Status:** Accepted

**Summary:** Implements hybrid search across multiple collections (artifacts, artifact_chunks, optionally memory) with Reciprocal Rank Fusion (RRF) for result merging and intelligent deduplication to prevent duplicate artifact results.

**Key Decisions:**
- Use RRF (Reciprocal Rank Fusion) with k=60 for merging ranked lists
- Search collections in parallel with shared query embedding
- Overfetch (limit × 3) from each collection before merging
- Deduplicate by artifact_id, preferring chunks over full documents
- Optional neighbor expansion for broader chunk context
- Privacy filter hook (placeholder in v2, enforced in v3)

**Consequences:**
- **Pros:** Single API for multi-collection search, better recall, consistent cross-collection ranking
- **Cons:** 3× latency vs single collection, overfetching overhead, RRF scores less intuitive

**Related ADRs:** ADR-001 (query embedding), ADR-002 (searches chunks), ADR-004 (RetrievalService design)

**Future:** v3+ may implement learned ranking models (LambdaMART, RankNet) for optimal ranking

---

### ADR-004: Module Structure and Service Layer

**File:** `ADR-004-module-structure.md`

**Status:** Accepted

**Summary:** Defines a layered architecture with clear separation of concerns: Server Layer (MCP protocol), Service Layer (business logic), Storage Layer (ChromaDB), and Utilities. Replaces v1's monolithic 356-line server.py with organized module structure.

**Key Decisions:**
- **Layer 1 (Server):** MCP protocol, tool definitions, HTTP endpoints
- **Layer 2 (Services):** EmbeddingService, ChunkingService, RetrievalService, PrivacyService
- **Layer 3 (Storage):** ChromaDB client, collection helpers, data models
- **Layer 4 (Utilities):** Logging, errors, validators

**Module Structure:**
```
src/
├── server.py           # MCP server, tools, startup
├── config.py           # Configuration management
├── services/           # Business logic
│   ├── embedding_service.py
│   ├── chunking_service.py
│   ├── retrieval_service.py
│   └── privacy_service.py
├── storage/            # ChromaDB layer
│   ├── chroma_client.py
│   ├── collections.py
│   └── models.py
└── utils/              # Common utilities
    ├── logging.py
    ├── errors.py
    └── validators.py
```

**Key Patterns:**
- Dependency injection (services receive dependencies via constructor)
- Service initialization at startup (lifespan hook)
- Two-phase atomic writes (generate all embeddings first, then write)
- Error handling hierarchy (tool → service → storage)

**Consequences:**
- **Pros:** Maintainable, testable, extensible, reusable services, type-safe
- **Cons:** More boilerplate, indirection, learning curve for new developers

**Related ADRs:** ADR-001, ADR-002, ADR-003 (all services defined here)

---

## Decision Rationale Summary

| Aspect | v1 | v2 | Rationale |
|--------|----|----|-----------|
| **Embeddings** | ChromaDB auto (384 dims) | OpenAI text-embedding-3-large (3072 dims) | Quality improvement, full control |
| **Storage** | 2 collections (memory, history) | 4 collections (+artifacts, +artifact_chunks) | Support large documents with chunking |
| **Chunking** | None | Token-window (900 + 100 overlap) | Retrieval precision for large docs |
| **Search** | Single collection | Hybrid with RRF merging | Better recall across sources |
| **Architecture** | Monolithic (356 lines) | Layered (15 files) | Maintainability, testability |

---

## Cross-Cutting Concerns

### Two-Phase Atomic Writes

**Pattern:** Generate ALL embeddings first (Phase 1), then write to DB (Phase 2)

**Rationale:** Prevents partial data if embedding generation fails mid-batch

**Referenced in:**
- ADR-002 (chunked artifact ingestion)
- ADR-004 (implementation pattern)

### Observability

**Pattern:** Structured JSON logging with event names and metadata

**Rationale:** Debug production issues, track performance, monitor costs

**Referenced in:**
- ADR-001 (embedding metrics)
- ADR-002 (chunking decisions)
- ADR-003 (search performance)
- ADR-004 (logging utilities)

### Privacy Filtering

**Pattern:** PrivacyService with placeholder implementation (v2: no-op, v3: enforce)

**Rationale:** Store privacy fields now, enforce later without schema changes

**Referenced in:**
- ADR-003 (retrieval privacy hook)
- ADR-004 (PrivacyService design)

---

## Implementation Sequence

Recommended order for implementing v2.0:

1. **Setup** (ADR-004):
   - Create directory structure
   - Implement config.py
   - Setup utils/ (logging, errors, validators)

2. **Storage Layer** (ADR-004):
   - ChromaDB client wrapper
   - Collection helpers
   - Data models (Chunk, SearchResult, MergedResult)

3. **Embedding Service** (ADR-001):
   - OpenAI client integration
   - Retry logic with exponential backoff
   - Batch coordination
   - Health check

4. **Chunking Service** (ADR-002):
   - Token counting (tiktoken)
   - Token-window chunking algorithm
   - Deterministic chunk ID generation
   - Neighbor expansion

5. **Retrieval Service** (ADR-003):
   - Parallel collection searches
   - RRF merging algorithm
   - Deduplication logic
   - Privacy filter hook (placeholder)

6. **Server Layer** (ADR-004):
   - Update existing tools (memory_store, memory_search, etc.)
   - Implement new tools (artifact_ingest, artifact_search, hybrid_search, etc.)
   - Lifespan management (service initialization)
   - Health endpoint

7. **Testing**:
   - Unit tests (each service in isolation)
   - Integration tests (end-to-end flows)
   - Regression tests (v1 tools still work)

8. **Deployment**:
   - Docker Compose configuration
   - Environment variable setup
   - Health checks
   - Smoke tests

---

## Testing Strategy

### Unit Tests (No External Dependencies)

- **EmbeddingService:** Mock OpenAI client, test retry logic
- **ChunkingService:** Test token counting, chunk boundaries, deterministic IDs
- **RetrievalService:** Mock ChromaDB, test RRF calculation, deduplication

### Integration Tests (Real Dependencies)

- **Artifact Ingestion:** Real embeddings + ChromaDB, test small/large docs
- **Hybrid Search:** Real search across collections, verify RRF merging
- **Two-Phase Writes:** Inject failures, verify no partial data

### Regression Tests

- **v1 Compatibility:** All v1 tools (memory_store, memory_search, history_*) still work
- **OpenAI Upgrade:** v1 memories searchable with v2 embeddings

---

## Future Enhancements

### v2.1 - Structure-Aware Chunking

**Goal:** Improve chunk quality by respecting document structure

**Changes:**
- Email: Split by reply blocks
- Markdown: Split by headings
- Chat: Split by speaker turns
- Fallback: Token-window (current)

**ADR Impact:** ADR-002 (ChunkingService extended)

### v3 - Multi-User & Privacy Enforcement

**Goal:** Support multiple users with privacy enforcement

**Changes:**
- User authentication and sessions
- Enforce sensitivity/visibility at retrieval
- Audit logging for access denials
- Custom ACLs

**ADR Impact:** ADR-003 (PrivacyService implemented), ADR-004 (new AuthService)

---

## Legacy ADRs (v1.0)

The following ADRs are from v1.0 and are superseded by v2.0:

- `ADR-001-docker-first.md` - Still relevant (deployment)
- `ADR-002-chromadb-vector-store.md` - Updated in v2 (BYO embeddings)
- `ADR-003-separation-of-concerns.md` - Superseded by ADR-004 (module structure)
- `ADR-004-two-collection-model.md` - Superseded by v2 (4 collections)

---

## References

- **Technical Specification:** `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/specs/v2-technical-spec.md`
- **v1 Implementation:** `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/server.py`

---

## Approval & Next Steps

**Status:** ✅ Architecture Design Complete

**Approved by:** Senior Architect
**Date:** 2025-12-25

**Next Phase:** Implementation

**Handoff to:** Lead Backend Engineer

**Action Items:**
1. Review all 4 ADRs with team
2. Set up development environment
3. Create implementation tickets from ADR-004 sequence
4. Begin with storage layer and embedding service
5. Iterate through implementation sequence
6. Run test suite after each component
7. Integration testing with real OpenAI API
8. Deployment and smoke tests

---

**Generated by:** Senior Architect
**Date:** 2025-12-25
**Version:** 1.0
