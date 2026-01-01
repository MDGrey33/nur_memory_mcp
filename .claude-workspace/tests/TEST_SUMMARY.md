# MCP Memory Test Suite Summary

## Overview

Comprehensive testing infrastructure for MCP Memory Server covering functional tests (unit, integration, E2E) and quality benchmarks.

**Current Version**: V6.2 (with V7 Quality Benchmarks)

---

## Test Architecture

```
.claude-workspace/
├── tests/
│   └── v6/                      # V6 Functional Tests
│       ├── unit/                # Unit tests (mocked dependencies)
│       ├── integration/         # Integration tests (mocked services)
│       └── e2e/                 # End-to-end tests (real infrastructure)
├── benchmarks/                  # V7 Quality Benchmarks
│   ├── corpus/                  # Labeled test documents
│   ├── ground_truth/            # Expected events/entities
│   ├── queries/                 # Benchmark queries
│   ├── metrics/                 # Metric implementations
│   ├── fixtures/                # Recorded outputs for replay
│   ├── tests/                   # Benchmark runner + metric tests
│   └── reports/                 # Benchmark results
└── implementation/mcp-server/
    └── tests/                   # Core unit tests
        ├── unit/                # Service unit tests
        └── integration/         # Service integration tests
```

---

## Test Categories

### 1. Functional Tests (V6)

Tests that verify **features work correctly**.

| Category | Location | Tests | Description |
|----------|----------|-------|-------------|
| Core Unit | `implementation/mcp-server/tests/unit/` | 90 | Service-level unit tests |
| Core Integration | `implementation/mcp-server/tests/integration/` | 26 | Service integration |
| V6 Unit | `tests/v6/unit/` | 19 | V6 tool unit tests |
| V6 Integration | `tests/v6/integration/` | 61 | V6 tool integration tests |
| V6 E2E | `tests/v6/e2e/` | 11 | Full stack E2E tests |
| **Total** | | **207** | |

### 2. Quality Benchmarks (V7)

Tests that measure **how well features perform**.

| Category | Location | Items | Description |
|----------|----------|-------|-------------|
| Corpus | `benchmarks/corpus/` | 12 docs | Labeled test documents |
| Ground Truth | `benchmarks/ground_truth/` | 63 events, 20 entities, 5 graph queries | Expected extractions |
| Queries | `benchmarks/queries/` | 15 queries | Retrieval benchmarks |
| Metric Tests | `benchmarks/tests/` | 37 | Metric implementation tests |
| Event Fixtures | `benchmarks/fixtures/events/` | 12 | Event extraction fixtures |
| Entity Fixtures | `benchmarks/fixtures/entities/` | 12 | Entity extraction fixtures |
| Retrieval Fixtures | `benchmarks/fixtures/retrievals/` | 15 | Retrieval fixtures |
| Graph Fixtures | `benchmarks/fixtures/graph/` | 5 | Graph expansion fixtures |

---

## Running Tests

### Quick Commands

```bash
# Run all V6 functional tests
cd .claude-workspace/implementation/mcp-server
pytest ../../tests/v6 -v

# Run core unit tests only
pytest tests/unit -v

# Run V7 benchmark metrics tests
cd .claude-workspace/benchmarks
pytest tests/test_metrics.py -v

# Run V7 benchmarks (replay mode - deterministic)
python tests/benchmark_runner.py --mode=replay

# Run V7 benchmarks (live mode - real services)
python tests/benchmark_runner.py --mode=live
```

### Test Modes

| Mode | Speed | Dependencies | Use Case |
|------|-------|--------------|----------|
| Unit | Fast (~1s) | None | Local dev, CI |
| Integration | Medium (~5s) | Mocked | PR checks |
| E2E | Slow (~30s) | Docker | Pre-deploy |
| Benchmark Replay | Fast (~2s) | Fixtures | CI quality gates |
| Benchmark Live | Slow (~60s) | Full stack | Nightly/Release |

---

## V6 Tool Coverage

### remember()
- ✅ Content storage with deduplication
- ✅ Automatic chunking for long content
- ✅ Context-based ID generation
- ✅ Event extraction (async)
- ✅ Validation errors (empty content, invalid context)

### recall()
- ✅ Semantic search across content + chunks
- ✅ Graph expansion via SQL joins
- ✅ Conversation history retrieval
- ✅ Limit and filtering options

### forget()
- ✅ Cascade deletion (content → chunks → events → entities)
- ✅ Confirmation requirement
- ✅ Event ID guidance (not deletable directly)

### status()
- ✅ Health check for all services
- ✅ Collection statistics
- ✅ Version reporting

---

## V7 Quality Metrics

### Event Extraction Metrics
| Metric | Description | Threshold |
|--------|-------------|-----------|
| Precision | Correct events / Total predicted | - |
| Recall | Correct events / Total expected | - |
| F1 Score | Harmonic mean of P/R | ≥ 0.70 |

### Entity Extraction Metrics
| Metric | Description | Threshold |
|--------|-------------|-----------|
| Precision | Correct entities / Total predicted | - |
| Recall | Correct entities / Total expected | - |
| F1 Score | Harmonic mean of P/R | ≥ 0.70 |

### Retrieval Metrics
| Metric | Description | Threshold |
|--------|-------------|-----------|
| MRR | Mean Reciprocal Rank | ≥ 0.60 |
| NDCG | Normalized DCG | ≥ 0.65 |
| P@K | Precision at K | - |
| R@K | Recall at K | - |

### Graph Expansion Metrics
| Metric | Description | Threshold |
|--------|-------------|-----------|
| Connection P/R/F1 | Entity connection accuracy | ≥ 0.60 |
| Document P/R/F1 | Connected document accuracy | ≥ 0.60 |

---

## Benchmark Corpus

### Documents (12 total)
| Type | Count | Examples |
|------|-------|----------|
| Meetings | 5 | Q1 planning, engineering sync, design review |
| Emails | 3 | Timeline updates, budget revisions |
| Decisions | 2 | Mobile design, pricing model |
| Conversations | 2 | Slack threads |

### Ground Truth
- **63 labeled events** across categories:
  - Decision (19), Commitment (15), Execution (16)
  - QualityRisk (10), Feedback (1), Change (1), Stakeholder (1)
- **20 entities**: 11 people, 3 orgs, 6 projects (doc-keyed)
- **6 relationships** with evidence
- **5 graph expansion queries** with expected connections

### Query Types (15 total)
- Factual (1): "What is the launch date?"
- Entity-focused (5): "Bob's commitments", "Emma's work"
- Category search (1): "All risks"
- Topic search (4): "Pricing", "Infrastructure"
- Time-filtered (1): "Commitments this week"
- Graph expansion (1): "Connected to Alice"
- Relationship (1): "David and Bob relationship"

---

## Two-Tier Benchmark Strategy

### Tier 1: PR Benchmarks (Replay Mode)
- **When**: Every PR, CI pipeline
- **How**: Uses recorded fixtures
- **Why**: Deterministic, fast, no LLM variance
- **Command**: `python benchmark_runner.py --mode=replay`

### Tier 2: Nightly Benchmarks (Live Mode)
- **When**: Nightly builds, pre-release
- **How**: Real OpenAI/Postgres/Chroma
- **Why**: Full-fidelity quality measurement
- **Command**: `python benchmark_runner.py --mode=live`

### Recording New Fixtures
```bash
# After model/prompt changes, record new baseline
python benchmark_runner.py --record
git add fixtures/
git commit -m "Update benchmark fixtures"
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Run unit tests
        run: pytest tests/unit -v

      - name: Run integration tests
        run: pytest tests/v6/integration -v

      - name: Run benchmark (replay)
        run: |
          cd .claude-workspace/benchmarks
          python tests/benchmark_runner.py --mode=replay

  nightly:
    runs-on: ubuntu-latest
    schedule:
      - cron: '0 2 * * *'
    steps:
      - name: Run benchmark (live)
        run: |
          cd .claude-workspace/benchmarks
          python tests/benchmark_runner.py --mode=live
```

---

## Progress Tracking

See [TESTING_PROGRESS.md](./TESTING_PROGRESS.md) for current status and history.

---

## Adding New Tests

### Adding Functional Tests
1. Create test file in appropriate directory
2. Use fixtures from `conftest.py`
3. Follow naming: `test_<feature>_<scenario>.py`

### Adding Benchmark Documents
1. Add document to `benchmarks/corpus/<type>/`
2. Add ground truth events to `ground_truth/events.json`
3. Add entities to `ground_truth/entities.json`
4. Add relevant queries to `queries/queries.json`
5. Record fixtures: `python benchmark_runner.py --record`

### Adding Benchmark Queries
1. Add query to `queries/queries.json` with:
   - `id`: Unique query ID
   - `query`: Natural language query
   - `type`: Query type
   - `relevant_documents`: List with relevance scores
   - `expected_events`: Event IDs expected in results

---

## Quality Gates

| Gate | Requirement | Status |
|------|-------------|--------|
| Unit Tests | All pass | ✅ |
| Integration Tests | All pass | ✅ |
| E2E Tests | All pass (when infra up) | ✅ |
| Extraction F1 | ≥ 0.70 | Pending baseline |
| Retrieval MRR | ≥ 0.60 | Pending baseline |
| Retrieval NDCG | ≥ 0.65 | Pending baseline |

---

## Files Reference

| File | Purpose |
|------|---------|
| `tests/v6/conftest.py` | V6 test fixtures and mocks |
| `benchmarks/metrics/extraction_metrics.py` | P/R/F1 calculations |
| `benchmarks/metrics/retrieval_metrics.py` | MRR/NDCG calculations |
| `benchmarks/tests/benchmark_runner.py` | Main benchmark executor |
| `benchmarks/tests/test_metrics.py` | Metric unit tests |

---

**Last Updated**: 2026-01-01
**Version**: V6.2 + V7 Benchmarks
