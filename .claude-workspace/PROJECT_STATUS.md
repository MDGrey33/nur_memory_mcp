# MCP Memory Server - Project Status & Roadmap

**Last Updated**: 2026-01-13
**Current Version**: V9 Consolidation
**Status**: Active Development

---

## Executive Summary

MCP Memory Server is a Model Context Protocol server for persistent memory with semantic event extraction and graph-backed context expansion. The project has evolved through 9 major versions (Dec 2025 - Jan 2026).

**Current State**: Core functionality works well. Retrieval quality exceeds targets. Extraction and entity resolution need improvement to hit quality gates.

---

## 1. System Architecture

### Components
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  MCP Clients    │────▶│  MCP Server     │────▶│  Event Worker   │
│  (Claude, etc.) │     │  (FastMCP)      │     │  (Background)   │
└─────────────────┘     └────────┬────────┘     └────────┬────────┘
                                 │                       │
                    ┌────────────┴────────────┐          │
                    ▼                         ▼          ▼
              ┌──────────┐              ┌──────────┐    │
              │ ChromaDB │              │ Postgres │◀───┘
              │ (Vector) │              │ (Events) │
              └──────────┘              └──────────┘
```

### Tech Stack
| Component | Technology | Purpose |
|-----------|------------|---------|
| Server | Python + FastMCP | MCP protocol handling |
| Vector DB | ChromaDB | Embeddings, semantic search |
| Relational DB | PostgreSQL | Events, entities, edges |
| Embeddings | OpenAI text-embedding-3-small | Vector generation |
| Extraction | GPT-4o-mini | Event/entity extraction |
| Transport | Streamable HTTP (SSE) | Client communication |

### API Surface (4 tools)
| Tool | Purpose |
|------|---------|
| `remember(content)` | Store content with auto-chunking, embedding, extraction |
| `recall(query)` | Semantic search with graph expansion |
| `forget(id)` | Delete content with cascade |
| `status()` | Health check, job status |

---

## 2. Quality Metrics

### Current Benchmark Scores (2026-01-11)

| Metric | Score | Target | Gap | Status |
|--------|-------|--------|-----|--------|
| Retrieval MRR | 0.81 | 0.60 | +0.21 | ✅ PASS |
| Retrieval NDCG | 0.82 | 0.65 | +0.17 | ✅ PASS |
| Extraction F1 | 0.60 | 0.70 | -0.10 | ⚠️ Close |
| Entity F1 | 0.58 | 0.70 | -0.12 | ⚠️ Needs work |
| Graph Conn F1 | 0.48 | 0.60 | -0.12 | ⚠️ Needs work |

### Extraction Breakdown by Document Type
| Type | F1 | Notes |
|------|-----|-------|
| Meetings | 0.67-0.88 | Strong |
| Emails | 0.44-0.50 | Medium |
| Decisions | 0.50 | Medium |
| Conversations | 0.31-0.67 | Weak - main drag on score |

### Entity Extraction Issues
- **Precision**: 0.44 (too many false positives)
- **Recall**: 0.85 (finding most entities)
- **Problem**: Extracting noise entities that don't exist in ground truth

---

## 3. Version History & Features

| Version | Date | Key Features | Status |
|---------|------|--------------|--------|
| V1 | Dec 2025 | ChromaDB, basic memory | Archived |
| V2 | Dec 2025 | OpenAI embeddings, chunking | Archived |
| V3 | Dec 2025 | PostgreSQL, event extraction | Archived |
| V4 | Dec 2025 | Graph expansion (Apache AGE) | Archived |
| V5 | Dec 2025 | Simplified API (4 tools) | Archived |
| V6 | Jan 2026 | Tool consolidation, cleanup | Archived |
| V7 | Jan 2026 | Quality benchmarks | Archived |
| V7.3 | Jan 2026 | Dynamic categories, two-phase retrieval | Merged to V9 |
| V8 | Jan 2026 | Explicit edges, SQL graph | Merged to V9 |
| **V9** | Jan 2026 | Consolidation release | **Active** |

### V9 Completed Work
- ✅ `edge_types` param in recall()
- ✅ `include_edges` param in recall()
- ✅ Embedding cache for triplet scoring
- ✅ Benchmark fixes for dynamic categories
- ✅ CI/CD workflow (unit + integration tests)

### V9 Remaining Work
- ⬜ Extraction F1: 0.60 → 0.70
- ⬜ Entity F1: 0.58 → 0.70
- ⬜ Graph F1: 0.48 → 0.60

---

## 4. Codebase Structure

### Source Code
```
.claude-workspace/implementation/mcp-server/
├── src/
│   ├── server.py              # Main MCP server (4 tools)
│   ├── services/
│   │   ├── retrieval_service.py      # Hybrid search, RRF, graph expansion
│   │   ├── event_extraction_service.py  # LLM extraction
│   │   ├── entity_resolution_service.py # Entity dedup
│   │   ├── embedding_service.py      # OpenAI embeddings
│   │   ├── chunking_service.py       # Document chunking
│   │   └── job_queue_service.py      # Background jobs
│   ├── storage/
│   │   ├── chroma_client.py          # ChromaDB connection
│   │   ├── postgres_client.py        # PostgreSQL connection
│   │   └── collections.py            # V5+ collections
│   └── worker/
│       └── event_worker.py           # Background extraction
├── tests/
│   └── unit/                         # 90 unit tests
└── migrations/                       # SQL migrations
```

### Tests
| Location | Type | Count | Coverage |
|----------|------|-------|----------|
| `mcp-server/tests/unit/` | Unit | 90 | Services, storage |
| `tests/v6/integration/` | Integration | 61 | API contracts |
| `tests/e2e/` | E2E | ~22 | Full user simulation |
| `benchmarks/` | Quality | 5 metrics | Extraction, retrieval |

### Deployment
```
.claude-workspace/deployment/
├── docker-compose.yml      # All environments
├── .env.prod/.env.staging/.env.test
├── scripts/
│   ├── env-up.sh           # Start environment
│   ├── env-down.sh         # Stop environment
│   ├── env-reset.sh        # Reset data
│   └── health-check.sh     # Health check
```

| Environment | MCP | ChromaDB | PostgreSQL |
|-------------|-----|----------|------------|
| prod | 3001 | 8001 | 5432 |
| staging | 3101 | 8101 | 5532 |
| test | 3201 | 8201 | 5632 |

---

## 5. Documentation Status

### Summary
| Status | Count | Action |
|--------|-------|--------|
| ACTIVE | 15 | Keep updated |
| REFERENCE | 12 | Stable |
| ARCHIVE | 78 | Historical |

**Cleaned up 2026-01-13**: Archived 12 outdated V1/V3 docs, updated 4 files to V9.

### Active Docs (must maintain)
- `CLAUDE.md` - Claude Code instructions
- `README.md` - Project overview (updated to V9)
- `specs/v9-consolidation.md` - Current release
- `deployment/QUICK-START.md` - Setup guide
- `benchmarks/README.md` - Benchmark guide
- `DOCS.md` - Documentation index
- `PROJECT_STATUS.md` - This file

---

## 6. Technical Debt

### High Priority
| Item | Impact | Effort | Notes |
|------|--------|--------|-------|
| Conversation extraction quality | Quality gate | Medium | F1: 0.31-0.67, dragging overall score |
| Entity false positives | Quality gate | Medium | Precision 0.44, too much noise |

### Medium Priority
| Item | Impact | Effort | Notes |
|------|--------|--------|-------|
| Graph F1 improvement | Quality gate | Medium | Currently 0.48, target 0.60 |

### Low Priority
| Item | Impact | Effort | Notes |
|------|--------|--------|-------|
| datetime.utcnow() deprecation | Future Python | Low | 45 test warnings |
| AsyncMock unawaited warnings | Test cleanliness | Low | 16 warnings in tests |

---

## 7. Action Plan

### Completed (2026-01-13)
- ✅ Archived 12 outdated docs (V1/V3 era)
- ✅ Updated README.md to V9
- ✅ Updated mcp-server/README.md to V9
- ✅ Updated TEST_SUMMARY.md to V9
- ✅ Updated IMPLEMENTATION_SUMMARY.md to V9
- ✅ Created PROJECT_STATUS.md
- ✅ Updated DOCS.md with full doc map

### Short Term (This Sprint)

#### 3. Improve Conversation Extraction
**Effort**: 1-2 days
**Impact**: Extraction F1 +0.10
**Approach**:
- Analyze why conversations score low (0.31-0.67)
- Review extraction prompt for conversation-specific issues
- Consider conversation-specific prompt tuning

#### 4. Reduce Entity False Positives
**Effort**: 1-2 days
**Impact**: Entity F1 +0.10
**Approach**:
- Analyze what extra entities are being extracted
- Tighten entity extraction prompt
- Add confidence threshold filtering

### Medium Term (Next 2 Sprints)

#### 5. Graph Expansion Improvement
**Effort**: 2-3 days
**Impact**: Graph F1 +0.12
**Approach**:
- Analyze graph expansion mismatches
- Review edge creation logic
- Consider tuning expansion depth/breadth

#### 6. Create V9 Architecture Diagrams
**Effort**: 1 day
**Impact**: Better documentation
**Deliverables**:
- Updated component diagram
- Updated data flow diagram
- Current directory structure

### Long Term (Backlog)

#### 7. V10: Cognee Side-by-Side Comparison
**Goal**: Implement parallel MCP server using Cognee under the hood, same interface, to benchmark against our implementation.

**Spec**: `specs/v10-cognee-comparison.md`

**Phases**:
1. Cognee integration (1-2 days)
2. Response normalization (1 day)
3. Benchmark harness (1 day)
4. Evaluation & decision (1-2 days)

**Decision framework**:
- If Cognee wins by >10%: Consider migrating
- If we win by >10%: Continue custom development
- If comparable: Choose based on maintenance burden

---

## 8. Decision Log

### Pending Decisions

| Decision | Options | Recommendation | Owner |
|----------|---------|----------------|-------|
| Outdated docs | Archive vs Update | Archive (fast, clean) | - |
| README version | V7 vs V9 vs versionless | V9 | - |
| Conversation prompt | Generic vs specialized | Investigate first | - |

### Recent Decisions

| Date | Decision | Outcome |
|------|----------|---------|
| 2026-01-13 | Delete broken CI workflow | Replaced with working tests |
| 2026-01-13 | Create DOCS.md index | Easier doc maintenance |
| 2026-01-11 | Fix benchmark for dynamic categories | F1: 0.19 → 0.60 |
| 2026-01-10 | Implement edge_types/include_edges | API complete |

---

## 9. Key Files Reference

### Most Important Files
| File | Purpose |
|------|---------|
| `CLAUDE.md` | Claude Code instructions |
| `README.md` | Public project overview |
| `.claude-workspace/specs/v9-consolidation.md` | Current release spec |
| `.claude-workspace/DOCS.md` | Documentation index |
| `.claude-workspace/PROJECT_STATUS.md` | This file |

### Key Code Files
| File | Purpose |
|------|---------|
| `mcp-server/src/server.py` | Main server, 4 tools |
| `mcp-server/src/services/retrieval_service.py` | Search & graph expansion |
| `mcp-server/src/services/event_extraction_service.py` | LLM extraction |

### Key Config Files
| File | Purpose |
|------|---------|
| `deployment/docker-compose.yml` | Container orchestration |
| `deployment/.env` | Secrets (OPENAI_API_KEY) |
| `.mcp.json` | MCP client config |
| `.github/workflows/test.yml` | CI pipeline |

---

## 10. Contacts & Resources

### External Resources
- [MCP Protocol](https://modelcontextprotocol.io/)
- [ChromaDB Docs](https://docs.trychroma.com/)
- [FastMCP](https://github.com/jlowin/fastmcp)

### Commands Quick Reference
```bash
# Start prod
cd .claude-workspace/deployment && ./scripts/env-up.sh prod

# Run tests
cd .claude-workspace/implementation/mcp-server && pytest tests/unit/ -v

# Run benchmarks
cd .claude-workspace/benchmarks && python outcome_eval.py

# Check health
curl http://localhost:3001/health
```

---

## Appendix: Metrics History

| Date | MRR | NDCG | Extraction F1 | Entity F1 | Graph F1 |
|------|-----|------|---------------|-----------|----------|
| 2026-01-10 | 0.81 | 0.82 | 0.19 | 0.57 | 0.53 |
| 2026-01-11 | 0.81 | 0.82 | 0.60 | 0.58 | 0.48 |

*F1 jump from 0.19 → 0.60 was due to benchmark fix for dynamic categories*
