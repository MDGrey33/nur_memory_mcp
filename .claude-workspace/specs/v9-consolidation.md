# V9: Consolidation Release

**Version**: 9.0.0
**Status**: Active
**Created**: 2026-01-10
**Supersedes**: V7.3, V8, V8.1

---

## Overview

V9 consolidates all incomplete work from V7.3 through V8.1 into a single focused release. The primary goal is to fix the **extraction quality gap** (F1: 0.19 vs target 0.70) and complete the remaining API surface.

---

## Current State (as of 2026-01-10)

### What's Working
| Component | Score | Target | Status |
|-----------|-------|--------|--------|
| Retrieval MRR | 0.81 | 0.60 | PASS |
| Retrieval NDCG | 0.82 | 0.65 | PASS |
| Two-Phase Retrieval | - | - | Implemented |
| Dynamic Categories | - | - | Implemented |
| Explicit Edges (V8) | - | - | Implemented |

### What's Broken
| Component | Score | Target | Status |
|-----------|-------|--------|--------|
| Extraction F1 | **0.19** | 0.70 | CRITICAL |
| Entity F1 | 0.57 | 0.70 | Needs work |
| Graph Connection F1 | 0.53 | 0.60 | Close |

### What's Incomplete
| Item | Source | Description |
|------|--------|-------------|
| Triplet Scoring | V7.3 | Disabled (2.4x latency without embedding cache) |
| Embedding Cache | V8.1 | Store embeddings in DB for events/entities |
| `edge_types` param | V8 | Filter recall() by relationship type |
| `include_edges` param | V8 | Return edge details in response |

---

## V9 Roadmap

### Phase 1: Extraction Quality Fix (Priority: CRITICAL)

**Problem**: Extraction F1 is 0.19 - LLM extracts events but they don't match ground truth.

**Investigation Tasks**:
1. Analyze benchmark mismatches - what's being extracted vs expected
2. Check category alignment - are LLM categories matching ground truth labels?
3. Review extraction prompt - is it producing parseable, consistent output?
4. Check entity matching logic - are actors/subjects being matched correctly?

**Potential Fixes**:
- Normalize categories before comparison (case, synonyms)
- Loosen matching criteria (semantic similarity vs exact match)
- Update ground truth to match LLM's natural output
- Tune extraction prompt for consistency

**Success Criteria**: Extraction F1 >= 0.50 (interim), >= 0.70 (target)

### Phase 2: API Completion

Complete the V8 API surface:

```python
recall(
    query: str,
    # ... existing params ...

    # V9: Complete V8 API
    edge_types: List[str] = None,    # Filter by relationship type
    include_edges: bool = False,      # Return edge details
)
```

**Response additions**:
```json
{
  "results": [...],
  "related": [...],
  "entities": [...],
  "edges": [
    {
      "source": "Bob Smith",
      "target": "Alice Chen",
      "type": "MANAGES",
      "confidence": 0.9,
      "evidence": "Bob oversees Alice's work"
    }
  ]
}
```

**Files to modify**:
- `src/server.py` - Add params to recall() tool
- `src/services/retrieval_service.py` - Implement filtering and edge return

### Phase 3: Triplet Scoring (Performance-Gated)

Re-enable triplet scoring with proper caching:

1. **Add embedding columns** to `semantic_event` and `entity` tables
2. **Cache embeddings** during extraction (event_worker.py)
3. **Use cached embeddings** in triplet scoring (retrieval_service.py)
4. **Benchmark** - must not exceed 1.2x baseline latency

**Schema changes**:
```sql
ALTER TABLE semantic_event ADD COLUMN embedding vector(3072);
ALTER TABLE entity ADD COLUMN embedding vector(3072);

CREATE INDEX idx_event_embedding ON semantic_event USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_entity_embedding ON entity USING ivfflat (embedding vector_cosine_ops);
```

**Success Criteria**:
- Triplet scoring enabled
- Latency <= 1.2x baseline
- Quality maintained or improved

---

## Benchmark Targets

| Metric | Current | V9 Target |
|--------|---------|-----------|
| Extraction F1 | 0.19 | **0.70** |
| Entity F1 | 0.57 | **0.70** |
| Graph Connection F1 | 0.53 | **0.60** |
| Retrieval MRR | 0.81 | >= 0.60 (maintain) |
| Retrieval NDCG | 0.82 | >= 0.65 (maintain) |

---

## Files Reference

| File | Purpose |
|------|---------|
| `src/server.py` | API params |
| `src/services/retrieval_service.py` | Edge filtering, triplet scoring |
| `src/services/event_extraction_service.py` | Extraction prompt tuning |
| `src/worker/event_worker.py` | Embedding caching |
| `deployment/init.sql` | Schema changes |
| `benchmarks/tests/benchmark_runner.py` | Quality validation |

---

## Superseded Specs

The following specs are now closed and consolidated into V9:

- `v7.3-phase1-implementation.md` - Triplet scoring moved to V9 Phase 3
- `v8-explicit-edges.md` - API completion moved to V9 Phase 2
- V8.1 (planned, never specced) - Embedding cache moved to V9 Phase 3

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-10 | Consolidate V7.3/V8/V8.1 into V9 | Too many open items across versions |
| 2026-01-10 | Prioritize extraction fix | F1=0.19 is the critical blocker |
