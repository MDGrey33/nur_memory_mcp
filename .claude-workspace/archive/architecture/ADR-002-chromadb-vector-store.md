# ADR-002: ChromaDB as Vector Store

**Status:** Accepted

**Date:** 2025-12-25

**Context:**

The memory system requires a vector database for semantic search over stored memories and conversation history. We need to select a vector store technology that provides:
- Vector similarity search with acceptable performance
- Metadata filtering capabilities
- Persistence across restarts
- Integration with the MCP ecosystem
- Reasonable operational complexity for V1
- Clear migration path for future scaling

Alternative vector store options considered:
1. **ChromaDB** - Lightweight, embedded-capable, MCP-native
2. **Pinecone** - Managed, cloud-native, serverless
3. **Weaviate** - Full-featured, open-source, GraphQL API
4. **Qdrant** - High-performance, Rust-based, production-ready
5. **PostgreSQL + pgvector** - Relational DB with vector extension
6. **FAISS** - In-memory, library-only, no server

**Decision:**

We will use **ChromaDB** as the vector store for V1.

Key factors in this decision:
- **MCP-native**: chroma-mcp gateway already exists and is maintained
- **Simplicity**: Easy Docker deployment, minimal configuration
- **Persistence**: Built-in persistent storage via Docker volumes
- **Metadata support**: Rich metadata filtering capabilities
- **Community**: Active development, good documentation
- **Embedding**: Automatic embedding generation included
- **Zero-ops**: No cluster management or complex setup required

**Consequences:**

**Positive:**
- **Fast implementation**: chroma-mcp gateway provides immediate MCP integration
- **Low complexity**: Single container deployment, no cluster coordination
- **Good V1 fit**: Performance adequate for expected V1 scale (10K-100K docs)
- **Developer experience**: Simple API, clear semantics
- **Local development**: Can run entirely on laptop without cloud dependencies
- **Cost**: Open-source, no licensing or SaaS fees
- **Flexibility**: Can swap embeddings models easily

**Negative:**
- **Scale limitations**: Not optimized for multi-million vector scale
- **Single-node**: No built-in clustering or sharding (adequate for V1)
- **Feature maturity**: Newer than alternatives like Pinecone or Weaviate
- **Query sophistication**: Less advanced filtering than specialized solutions
- **Vendor lock-in risk**: Switching vector stores later requires migration effort

**Performance characteristics (expected for V1):**
- Vector dimensions: 384-1536 (depending on embedding model)
- Collection size: 10K-100K documents
- Query latency: <500ms for top-K=8 (p95)
- Throughput: 100+ queries/second (single node)

**Scale migration path:**
If V2+ requires more scale, we can:
1. Keep ChromaDB for small deployments
2. Add VectorStore abstraction in agent-app
3. Implement adapters for Pinecone, Weaviate, or Qdrant
4. Migrate data using export/import tools
5. Run both stores during transition period

**Implementation constraints:**
- Use HTTP client mode (not embedded) for container deployment
- Leverage chroma-mcp as gateway (no direct ChromaDB SDK in agent-app)
- Configure persistence via IS_PERSISTENT=TRUE
- Mount volume at /chroma/chroma for data
- Use Docker health checks to ensure readiness

**Alternatives rejected:**

1. **Pinecone**: Rejected due to SaaS requirement, cost implications, and external dependency. V1 aims for self-contained Docker deployment.

2. **Weaviate**: Rejected due to higher operational complexity (more configuration, larger resource footprint) than needed for V1 scale.

3. **Qdrant**: Strong alternative, but lacks established MCP integration. Would require building custom MCP gateway, adding implementation time.

4. **PostgreSQL + pgvector**: Rejected because mixing relational and vector paradigms adds complexity. Would still need separate vector query layer.

5. **FAISS**: Rejected due to lack of server component, no built-in persistence, and requirement to build entire API layer ourselves.

**Security considerations:**
- V1 does not implement authentication between services (internal Docker network)
- ChromaDB ports not exposed externally by default
- V2 can add auth if deploying outside trusted network
- Data at rest encryption via volume encryption (OS-level)

**Related decisions:**
- ADR-001: Docker-First Deployment
- ADR-003: Separation of Concerns
- ADR-004: Two-Collection Model

**Review date:** After V1 load testing and production validation

**Success metrics:**
- Query latency <500ms (p95)
- Support 100K documents without degradation
- Zero data loss during restarts
- >99.5% uptime
