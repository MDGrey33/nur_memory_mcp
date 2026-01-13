# V9: Consolidation Release

**Version**: 9.0.0
**Status**: Active
**Created**: 2026-01-10
**Supersedes**: V7.3, V8, V8.1

---

## Overview

V9 consolidates all incomplete work from V7.3 through V8.1 into a single focused release. The primary goal is to improve **extraction quality** (F1: 0.60 → 0.70) and complete the remaining API surface.

---

## Current State (as of 2026-01-11)

### What's Working
| Component | Score | Target | Status |
|-----------|-------|--------|--------|
| Retrieval MRR | 0.81 | 0.60 | ✅ PASS |
| Retrieval NDCG | 0.82 | 0.65 | ✅ PASS |
| Two-Phase Retrieval | - | - | ✅ Implemented |
| Dynamic Categories | - | - | ✅ Implemented |
| Explicit Edges (V8) | - | - | ✅ Implemented |
| `edge_types` param | V8 | - | ✅ Implemented |
| `include_edges` param | V8 | - | ✅ Implemented |
| Embedding Cache | V8.1 | - | ✅ Implemented |

### What Needs Improvement
| Component | Score | Target | Status |
|-----------|-------|--------|--------|
| Extraction F1 | **0.60** | 0.70 | ⚠️ Close (was 0.19) |
| Entity F1 | 0.58 | 0.70 | ⚠️ Needs work |
| Graph Connection F1 | 0.48 | 0.60 | ⚠️ Needs work |

### Completed Items
| Item | Source | Status |
|------|--------|--------|
| ✅ `edge_types` param | V8 | Implemented in recall() |
| ✅ `include_edges` param | V8 | Implemented in recall() |
| ✅ Embedding Cache | V8.1 | Caches embeddings for triplet scoring |
| ✅ Benchmark fixes | V9 | Fixed for dynamic categories |

---

## V9 Roadmap

### Phase 1: Extraction Quality Improvement (Priority: HIGH)

**Current State**: Extraction F1 improved from 0.19 → 0.60 after benchmark fixes for dynamic categories.

**Completed**:
- ✅ Fixed category matching to handle dynamic LLM-suggested categories
- ✅ Normalized category comparison (case-insensitive, synonym mapping)
- ✅ Updated benchmark to use fuzzy matching for event narratives

**Remaining Gap** (0.60 → 0.70):
- Conversations score lowest (F1: 0.31-0.67) - investigate extraction prompt
- Entity extraction precision is low (0.44) - too many false positives
- Consider tightening extraction prompt to reduce noise

**Success Criteria**: Extraction F1 >= 0.70 (target)

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
