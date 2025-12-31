# Architecture Documentation: Chroma MCP Memory V1

**Version:** 1.0
**Date:** 2025-12-25
**Status:** Ready for Implementation
**Senior Architect:** Claude (Autonomous Development Team)

---

## Overview

This directory contains the complete architecture documentation for the Chroma MCP Memory V1 system. The architecture defines a Docker-first, three-tier system for persistent conversation history and semantic memory storage.

---

## Document Index

### Architecture Decision Records (ADRs)

Key architectural decisions with context, rationale, and consequences:

1. **[ADR-001: Docker-First Deployment](./ADR-001-docker-first.md)**
   - Decision: Use Docker Compose for all deployments
   - Rationale: Consistency, isolation, simplicity
   - Status: Accepted

2. **[ADR-002: ChromaDB as Vector Store](./ADR-002-chromadb-vector-store.md)**
   - Decision: Use ChromaDB for vector storage and semantic search
   - Rationale: MCP-native, simplicity, adequate V1 scale
   - Status: Accepted

3. **[ADR-003: Separation of Concerns](./ADR-003-separation-of-concerns.md)**
   - Decision: Three-layer architecture (gateway/builder/policy)
   - Rationale: Testability, maintainability, evolvability
   - Status: Accepted

4. **[ADR-004: Two-Collection Model](./ADR-004-two-collection-model.md)**
   - Decision: Separate `history` and `memory` collections
   - Rationale: Different access patterns, clear semantics
   - Status: Accepted

### Design Documentation

5. **[Component Diagram](./component-diagram.md)**
   - Complete component architecture
   - Service interactions and responsibilities
   - Network topology and deployment dependencies
   - Technology stack summary

6. **[Data Flow Diagrams](./data-flows.md)**
   - Detailed sequence diagrams for all core flows:
     - History append flow
     - Memory write flow
     - Context build flow
     - Bootstrap flow
     - Persistence verification flow
   - Data transformations and error handling
   - Performance characteristics

7. **[Directory Structure](./directory-structure.md)**
   - Complete file and folder layout
   - Module responsibilities and interfaces
   - Testing structure
   - Development workflow
   - File size estimates

---

## Architecture Summary

### System Layers

```
┌─────────────────────────────────────────┐
│         User / LLM Application          │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│           agent-app (Python)            │
│  ┌────────────────────────────────────┐ │
│  │  app.py (Orchestration)            │ │
│  └────┬────────────┬────────────┬─────┘ │
│       │            │            │       │
│  ┌────▼────┐  ┌───▼────┐  ┌────▼────┐  │
│  │ gateway │  │builder │  │ policy  │  │
│  └────┬────┘  └───┬────┘  └─────────┘  │
└───────┼───────────┼─────────────────────┘
        │           │
┌───────▼───────────▼─────────────────────┐
│       chroma-mcp (MCP Gateway)          │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│         ChromaDB (Vector Store)         │
│  ┌────────────────────────────────────┐ │
│  │  Persistent Volume: chroma_data    │ │
│  │  - history collection              │ │
│  │  - memory collection               │ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### Key Principles

1. **Separation of Concerns**
   - Gateway: Pure transport, no business logic
   - Builder: Data assembly, no storage decisions
   - Policy: Business rules, no I/O

2. **Docker-First Deployment**
   - All services containerized
   - Single command deployment: `docker compose up`
   - Persistent volumes for data durability

3. **Two-Collection Model**
   - `history`: Complete conversation transcript
   - `memory`: High-value, deliberate memories
   - Different access patterns, optimized separately

4. **Stateless Services**
   - Only ChromaDB maintains state (via volume)
   - chroma-mcp is stateless gateway
   - agent-app is stateless (policy state is ephemeral)

---

## Core Flows

### 1. History Append (Every Message)
```
Message → app.py → gateway.append_history()
→ chroma-mcp → ChromaDB → history collection
```
**Latency**: <100ms (p95)

### 2. Memory Write (Selective)
```
Candidate → policy.should_store() [gate]
→ gateway.write_memory() → chroma-mcp
→ ChromaDB → memory collection
```
**Latency**: <150ms (p95)

### 3. Context Build (Every Response)
```
Request → builder.build_context()
→ [parallel] gateway.tail_history() + gateway.recall_memory()
→ Assemble + Format → LLM Prompt
```
**Latency**: <500ms (p95)

---

## Technology Decisions

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Container Platform | Docker Compose | Simplicity, consistency |
| Vector Database | ChromaDB | MCP-native, V1 scale adequate |
| MCP Gateway | chroma-mcp | Official, maintained |
| Agent Language | Python 3.11+ | Ecosystem, readability |
| Transport | MCP (stdio) | Standard protocol |
| Persistence | Docker Volume | Decoupled, backup-friendly |

---

## Design Patterns Applied

1. **Ports and Adapters** (Partial)
   - Gateway abstracts MCP protocol
   - V2 can introduce full port/adapter for vector store

2. **Dependency Injection**
   - Layers receive dependencies via constructors
   - Enables testing with mocks

3. **Single Responsibility Principle**
   - Each module has one clear job
   - Changes isolated to specific layer

4. **Policy Pattern**
   - Memory storage rules encapsulated in policy layer
   - Easily modified without touching transport

5. **Builder Pattern**
   - Context assembly separated from data fetching
   - Supports token budget and formatting variations

---

## Scalability and Evolution

### V1 Scale Targets
- **Documents**: 100K total (history + memory)
- **Conversations**: 10 concurrent
- **Throughput**: 100 messages/minute
- **Latency**: <500ms (p95) for all operations

### V2 Expansion Path

**Multi-collection memory model**:
```
history             (unchanged)
history_summaries   (new - compression)
mem_episodic        (new - "what happened")
mem_semantic        (new - "facts")
mem_procedural      (new - "how-to")
mem_narrative       (new - "story")
```

**Architecture extensions**:
- Add `VectorStore` port/interface
- Add `HistoryStore` port (could move to PostgreSQL)
- Add `MemoryRouter` (maps types to collections)
- Add `Summarizer` service
- Add promotion pipeline (history → memory)
- Add decay/archival jobs

**Horizontal scaling**:
- Multiple agent-app replicas (stateless)
- Load balancer
- ChromaDB clustering or migration to Qdrant/Weaviate

---

## Quality Attributes

### Performance
- History append: <100ms
- Memory write: <150ms
- Context build: <500ms
- Bootstrap: <30s

### Reliability
- 99.5% uptime target
- Zero data loss during graceful shutdown
- Automatic reconnection on transient failures

### Maintainability
- Type hints throughout
- >80% test coverage
- Clear layer boundaries
- Comprehensive documentation

### Security
- Internal Docker network (not exposed)
- No authentication required (trust boundary)
- V2 can add TLS/auth if needed

---

## Implementation Guidelines

### For Engineers

1. **Start with models.py**
   - Define data structures first
   - Establish type system

2. **Build gateway layer next**
   - Implement MCP communication
   - Test with mocks

3. **Then policy and builder**
   - Both depend on gateway
   - Test independently

4. **Wire in app.py last**
   - Orchestrate components
   - Integration tests

5. **Docker Compose final**
   - Container definitions
   - End-to-end testing

### Critical Success Factors

1. **Maintain layer boundaries**
   - Gateway: NO business logic
   - Builder: NO storage decisions
   - Policy: NO I/O operations

2. **Test each layer independently**
   - Unit tests with mocks
   - Integration tests with Docker

3. **Follow ADR decisions**
   - Don't deviate without new ADR
   - Document rationale for changes

4. **Keep V1 scope tight**
   - Resist feature creep
   - Defer to V2 per specification

---

## Review and Validation

### Architecture Review Checklist

- [ ] All ADRs reviewed and accepted
- [ ] Component diagram matches implementation
- [ ] Data flows verified with sequence diagrams
- [ ] Directory structure follows conventions
- [ ] Test strategy covers all flows
- [ ] Performance targets achievable
- [ ] Security posture acceptable for V1
- [ ] V2 expansion path clear

### Next Steps

1. **Lead Backend Engineer**: Review architecture for implementation feasibility
2. **Test Automation Engineer**: Review test strategy and coverage targets
3. **Security Engineer**: Review security boundaries and threat model
4. **Chief of Staff**: Review against user requirements

---

## Testing & Operations (V4)

V4 includes comprehensive testing infrastructure with environment isolation.
See [V4 ADR-005: Testing Infrastructure](./v4/adr/ADR-005-testing-infrastructure.md).

**Quick Reference:**

| Environment | MCP Port | Purpose |
|-------------|----------|---------|
| prod | 3001 | Production |
| staging | 3101 | Pre-release |
| test | 3201 | CI/CD |

**Scripts:** `.claude-workspace/deployment/scripts/`
- `env-up.sh` / `env-down.sh` - Start/stop environments
- `health-check.sh` - Verify service health (supports `--wait`, `--json`)

**CI:** `.github/workflows/test.yml` - GitHub Actions pipeline

---

## Reference Materials

### External Documentation
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [MCP Protocol Specification](https://github.com/modelcontextprotocol)
- [Docker Compose Reference](https://docs.docker.com/compose/)
- [Python Type Hints Guide](https://docs.python.org/3/library/typing.html)

### Internal Documentation
- Original spec: `/chroma_mcp_memory_v1.md`
- Detailed spec: `/.claude-workspace/specs/v1-specification.md`
- V4 architecture: `./v4/architecture-overview.md`
- This architecture directory

---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-25 | Senior Architect | Initial architecture documentation |

---

## Approval Status

- [ ] **Technical PM** - Requirements alignment verified
- [ ] **Senior Architect** - Architecture review complete (SELF)
- [ ] **Lead Backend Engineer** - Implementation feasibility confirmed
- [ ] **Test Automation Engineer** - Test strategy approved
- [ ] **Security Engineer** - Security review passed
- [ ] **Chief of Staff** - Ready for implementation

---

## Contact

For questions or clarifications on this architecture:
- Review ADRs for decision rationale
- Check data-flows.md for operational details
- Consult directory-structure.md for code organization
- Escalate to Chief of Staff if alignment issues arise

---

**Document Status**: Complete and ready for implementation
**Next Phase**: Implementation (Lead Backend Engineer)
