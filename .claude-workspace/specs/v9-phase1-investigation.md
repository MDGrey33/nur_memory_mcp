# V9 Phase 1: Extraction Quality Investigation

**Task ID**: task-20260110-172229
**Created**: 2026-01-10
**Status**: Complete

---

## Executive Summary

The extraction F1 score of **0.19** (target: 0.70) represents a **73% shortfall**. Root cause analysis reveals:

1. **Fixture cross-contamination** - Events from wrong documents appearing in fixtures
2. **Incomplete extraction** - LLM extracting ~50% of expected events
3. **NOT a matching threshold issue** - The algorithm is fine; events simply aren't being extracted

---

## Benchmark Results Breakdown

| Document | F1 | TP | FP | FN | Assessment |
|----------|-----|----|----|-----|------------|
| meeting_001.txt | 0.80 | 4 | 1 | 1 | GOOD |
| meeting_002.txt | 0.00 | 0 | 0 | 9 | COMPLETE FAILURE |
| meeting_003.txt | 0.20 | 1 | 4 | 4 | Poor |
| meeting_004.txt | 0.00 | 0 | 0 | 6 | COMPLETE FAILURE |
| meeting_005.txt | 0.00 | 0 | 0 | 12 | COMPLETE FAILURE |
| emails/* | Low | - | - | - | Mixed |
| decisions/* | 0.00 | 0 | 5+ | 3+ | Cross-contaminated |

**Aggregate**: Precision 0.23, Recall 0.16, F1 0.19

---

## Root Cause Analysis

### Issue 1: Fixture Cross-Contamination (CRITICAL)

**Evidence**: `decision_002.txt` fixture contains events from `meeting_005.txt`:

```
Document: decision_002.txt (Pricing Model Selection)
Expected: 3 events about pricing decision

Fixture contains:
- "James decided to reduce spending 15%" ← FROM meeting_005
- "Team agreed to revisit hiring..." ← FROM meeting_005
- "Competitor XYZ launched..." ← FROM meeting_005
```

**Cause**: Artifact ID mapping broken during concurrent fixture recording, or race condition in fixture save.

### Issue 2: Incomplete Event Extraction

**Evidence**: `meeting_005.txt` has 12 ground truth events, LLM extracted only 6:

Missing event types:
- Specific metrics (burn rate, runway numbers)
- Action items with dates
- Stakeholder announcements
- Multiple commitments

**Cause**: Either extraction prompt too narrow, or two-phase (Prompt A → Prompt B) pipeline dropping events.

### Issue 3: Narrative Mismatch (Secondary)

Some events ARE extracted but with different wording:

```
Ground truth: "David reported caching layer is 80% complete with 3x improvement"
LLM:          "David reported the new caching layer is 80% complete"
Similarity:   ~0.82 (should match)
```

This is NOT the primary cause - most failures are from missing events entirely.

---

## Hypotheses (Ranked)

| Rank | Hypothesis | Likelihood | Evidence |
|------|------------|------------|----------|
| 1 | Fixture cross-contamination | HIGH | Wrong events in decision_002 fixture |
| 2 | Event worker timing issues | HIGH | Only 50% events captured |
| 3 | Prompt B over-deduplication | MEDIUM | Chunks may suppress valid events |
| 4 | Matching threshold too strict | LOW | Matches exist but are missed |

---

## Recommended Fixes

### Fix 1: Audit and Re-record Fixtures

```bash
# 1. Check fixture integrity
grep -l "James decided to reduce spending" .claude-workspace/benchmarks/fixtures/*.json

# 2. Verify artifact_id mapping
# Each fixture should only contain events from its document

# 3. Re-record with isolated single-document processing
```

### Fix 2: Add Extraction Debug Logging

In `event_extraction_service.py`:
- Log all events from Prompt A (before dedup)
- Log events after Prompt B canonicalization
- Compare counts to identify where events are lost

### Fix 3: Increase Extraction Wait Time

In `benchmark_runner.py`:
- `MAX_WAIT = 60` (currently 30s)
- Ensure all extraction jobs complete before fixture save

### Fix 4: Review Prompt A for Completeness

Current prompt may miss:
- Metrics and specific numbers
- Multiple commitments per paragraph
- Subtle stakeholder communications

---

## Verification Plan

After fixes:
1. Run `python outcome_eval.py` - expect pass rate improvement
2. Run `python tests/benchmark_runner.py --mode=live` - expect F1 > 0.50
3. Check per-document breakdown - no more 0.00 scores on major documents
