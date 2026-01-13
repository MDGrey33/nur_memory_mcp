# Architecture Documentation

**Current Version**: V9 (Consolidation Release)
**Last Updated**: 2026-01-13

---

## Quick Overview

MCP Memory Server is a Model Context Protocol server with:
- **ChromaDB** for vector storage (embeddings, semantic search)
- **PostgreSQL** for structured data (events, entities, edges)
- **Background Worker** for async event extraction

See `CLAUDE.md` at project root for architecture diagram and key components.

---

## Current Architecture Docs

| Document | Description |
|----------|-------------|
| [`../specs/v9-consolidation.md`](../specs/v9-consolidation.md) | Current release spec |
| [`../specs/v8-explicit-edges.md`](../specs/v8-explicit-edges.md) | Edge/relationship model |
| [`../specs/v7-quality-benchmarks.md`](../specs/v7-quality-benchmarks.md) | Benchmark framework |

---

## Data Model

### ChromaDB Collections
- `content` - Full documents with embeddings
- `chunks` - Document chunks for long content

### PostgreSQL Tables
- `semantic_event` - Extracted events (decisions, commitments, etc.)
- `entity` - People, projects, organizations
- `event_actor` - Links entities as actors in events
- `event_subject` - Links entities as subjects of events
- `entity_edge` - Named relationships between entities

---

## Diagrams

The following diagrams are still valid references:
- [`component-diagram.md`](component-diagram.md) - Service components
- [`data-flows.md`](data-flows.md) - Request/response flows
- [`directory-structure.md`](directory-structure.md) - Code organization

---

## Historical ADRs

All ADRs from V1-V4 are archived in `archive/architecture/`. They provide historical context but are not authoritative for current implementation.

Key superseded decisions:
- V1-V4 used Apache AGE graph database → V8+ uses SQL joins
- V1-V4 had 17 tools → V5+ has 4 tools (remember, recall, forget, status)
- V1-V3 had fixed event categories → V7.3+ uses dynamic categories

---

## Testing Infrastructure

See archived ADR: [`archive/architecture/v4/adr/ADR-005-testing-infrastructure.md`](../archive/architecture/v4/adr/ADR-005-testing-infrastructure.md)

Environments:
| Environment | MCP Port | ChromaDB | PostgreSQL |
|-------------|----------|----------|------------|
| prod | 3001 | 8001 | 5432 |
| staging | 3101 | 8101 | 5532 |
| test | 3201 | 8201 | 5632 |
