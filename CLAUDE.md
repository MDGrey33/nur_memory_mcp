# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical Rules

1. **NEVER commit or push without explicit user permission** - Always ask before running `git commit` or `git push`
2. **Be careful with destructive operations** - Ask before deleting untracked files, production data, or user configs. Git-tracked files can be modified freely (they're recoverable).
3. **NEVER expose secrets** - Never log, commit, or display API keys, passwords, or tokens

## Project Overview

MCP Memory Server v7 - A Model Context Protocol server for persistent memory with semantic event extraction, graph-backed context expansion, and quality benchmarks. Built with Python, FastMCP, ChromaDB, and PostgreSQL with Apache AGE.

## Essential Commands

### Environment Management (Recommended)

```bash
cd .claude-workspace/deployment

# Start/stop environments (per ADR-005)
./scripts/env-up.sh prod          # Start production (waits for healthy)
./scripts/env-up.sh staging       # Start staging
./scripts/env-up.sh test          # Start test

./scripts/env-down.sh prod        # Stop production
./scripts/env-down.sh staging -v  # Stop staging and remove volumes
./scripts/env-reset.sh test       # Full reset (refuses prod for safety)

# Health check
./scripts/health-check.sh         # Check prod (default)
./scripts/health-check.sh staging # Check staging
./scripts/health-check.sh --json  # Output as JSON
```

### Environments (per ADR-005)

| Environment | MCP Port | ChromaDB | PostgreSQL | Use Case |
|-------------|----------|----------|------------|----------|
| prod | 3001 | 8001 | 5432 | Production, Claude Code |
| staging | 3101 | 8101 | 5532 | Pre-production testing |
| test | 3201 | 8201 | 5632 | CI/CD, E2E testing |

*Uses single `docker-compose.yml` with `.env.{prod,staging,test}` files*

### Running the Server Manually

```bash
cd .claude-workspace/implementation/mcp-server
pip install -r requirements.txt
python src/server.py              # MCP server on :3001
python -m src.worker              # Event extraction worker (separate terminal)
```

### Running Tests

```bash
# Unit tests (inside container or with venv activated)
cd .claude-workspace/implementation/mcp-server
pytest tests/unit/ -v

# Run single test file
pytest tests/unit/services/test_retrieval_service.py -v

# Run specific test
pytest tests/unit/services/test_chunking_service.py::test_chunk_text -v

# V6 integration tests
cd .claude-workspace/tests/v6
pytest integration/ -v

# E2E tests (requires running services)
python .claude-workspace/tests/e2e/full_user_simulation.py
```

### Quality Benchmarks

```bash
cd .claude-workspace/benchmarks

# Quick outcome test (~$0.006/run)
python outcome_eval.py

# Full benchmark suite (replay mode - no API calls)
python tests/benchmark_runner.py --mode=replay

# Live mode (requires services + OpenAI)
python tests/benchmark_runner.py --mode=live
```

### Database Operations

```bash
cd .claude-workspace/deployment

# Reset all data (wipes volumes and restarts)
./scripts/env-reset.sh test       # Reset test environment
./scripts/env-reset.sh staging    # Reset staging environment
./scripts/env-reset.sh prod --force  # Reset prod (requires --force)

# Or flush data only (keeps containers running)
./flush-data.sh

# Run migrations
docker exec -i mcp-memory-prod-postgres-1 psql -U events -d events < ../implementation/mcp-server/migrations/XXX.sql
```

## Architecture

### Data Flow

```
remember(content) → ChromaDB (embeddings) + Postgres (events/entities)
                           ↓                      ↓
                    content/chunks         semantic_event, entity,
                    collections            event_actor, event_subject
                           ↓                      ↓
recall(query) ←──────── Vector search ←──── Graph expansion (SQL joins)
```

### Key Components

**Server Entry Point**: `src/server.py`
- FastMCP server with 4 tools: `remember`, `recall`, `forget`, `status`
- Streamable HTTP transport on port 3001

**Services** (`src/services/`):
- `retrieval_service.py` - Hybrid search with RRF ranking and graph expansion
- `event_extraction_service.py` - LLM-based extraction (8 event categories)
- `entity_resolution_service.py` - Entity deduplication and linking
- `job_queue_service.py` - Background job management for extraction
- `embedding_service.py` - OpenAI embeddings
- `chunking_service.py` - Document chunking with overlap

**Storage** (`src/storage/`):
- `chroma_client.py` - ChromaDB connection
- `postgres_client.py` - PostgreSQL with Apache AGE
- `collections.py` - V5+ content/chunks collections

**Worker** (`src/worker/`):
- `event_worker.py` - Background processor for extraction and graph upsert jobs

### Event Categories

V7.3 uses dynamic categories (LLM-suggested, not fixed enum). Common categories include: `Decision`, `Commitment`, `Execution`, `Collaboration`, `QualityRisk`, `Feedback`, `Change`, `Stakeholder`.

### Graph Model

V8 (current): SQL-based graph with explicit edges:
- `event_actor`/`event_subject` tables link entities to events
- `entity_edge` table stores named relationships (MANAGES, DECIDED, COMMITTED_TO, etc.)
- Graph expansion finds related documents through both shared entities AND explicit edges

**Edge Categories**: Interpersonal (MANAGES, WORKS_WITH), Ownership (ASSIGNED_TO, COMMITTED_TO), Decisions (DECIDED, APPROVED), Causality (CAUSED, BLOCKED), Reference (RELATES_TO)

## Roadmap

### V9: Consolidation Release (Current)

**Status**: Active

**Consolidates**: V7.3 (triplet scoring), V8 (API completion), V8.1 (embedding cache)

**Completed**:
- ✅ `edge_types` and `include_edges` params added to recall()
- ✅ Embedding cache for triplet scoring
- ✅ Benchmark fixes for dynamic categories

**Remaining**:
- Extraction quality improvements (F1: 0.60 → 0.70)
- Entity resolution improvements (F1: 0.58 → 0.70)
- Graph expansion improvements (F1: 0.48 → 0.60)

**Spec**: `.claude-workspace/specs/v9-consolidation.md`

### Current Benchmark Status (2026-01-11)

| Component | Score | Target | Status |
|-----------|-------|--------|--------|
| Retrieval MRR | 0.81 | 0.60 | ✅ PASS |
| Retrieval NDCG | 0.82 | 0.65 | ✅ PASS |
| Extraction F1 | 0.60 | 0.70 | ⚠️ Close |
| Entity F1 | 0.58 | 0.70 | ⚠️ Needs work |
| Graph Conn F1 | 0.48 | 0.60 | ⚠️ Needs work |

## Claude Mind Development Workflow

This project uses an autonomous development workflow. Quick commands:

| Command | Purpose |
|---------|---------|
| `/build [task]` | Start autonomous development cycle |
| `/status` | Check progress |
| `/approve` | Approve completed work |
| `/feedback [comments]` | Request changes |

For full workflow details (phases, agents, skills):
```
@import .claude/docs/claude-mind.md
```

### Related Documentation

```
@import .claude/docs/workflow.md
@import .claude/docs/quality-gates.md
@import .claude/docs/learning-system.md
```

## Configuration

Environment variables in `.claude-workspace/deployment/.env`:
- `OPENAI_API_KEY` - Required for embeddings and extraction
- `EVENTS_DB_DSN` - Postgres connection string
- `CHROMA_HOST` / `CHROMA_PORT` - ChromaDB connection
- `MCP_PORT` - Server port (default 3000, mapped to 3001)

## MCP Client Configuration

For Claude Code (`.mcp.json`):
```json
{
  "mcpServers": {
    "memory": {
      "type": "http",
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

Note: `type` field is required; trailing slash on URL is important.

## Additional Documentation

### Deployment (read when deploying or managing environments)
- **Quick Start**: `.claude-workspace/deployment/QUICK-START.md` - 30-second setup
- **Cheatsheet**: `.claude-workspace/deployment/CHEATSHEET.md` - Commands & ports quick reference
- **Environments Guide**: `.claude-workspace/deployment/ENVIRONMENTS.md` - Detailed port configs, troubleshooting
- **Deployment README**: `.claude-workspace/deployment/README.md` - Full deployment guide

### Architecture & Quality (read when designing or benchmarking)
- **V7 Benchmarks Spec**: `.claude-workspace/specs/v7-quality-benchmarks.md` - Quality metrics details
- **V9 Consolidation**: `.claude-workspace/specs/v9-consolidation.md` - Current release spec

### Documentation Index
- **DOCS.md**: `.claude-workspace/DOCS.md` - Full documentation index with categories (active/reference/archive)
