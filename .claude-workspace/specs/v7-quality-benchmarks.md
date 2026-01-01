# V7 Specification: Quality Benchmark Suite

**Version**: 7.0.0
**Status**: MVP Implemented
**Created**: 2026-01-01
**Updated**: 2026-01-01
**Author**: Claude Development Team

---

## Executive Summary

V7 introduces a comprehensive **quality benchmark suite** to measure and validate the accuracy of MCP Memory's AI-powered features:

- Event extraction
- Entity resolution
- Recall relevance (ranking quality)
- Graph expansion (V6: SQL-join expansion from events/entities)

This spec also defines a **practical execution strategy** so benchmarks are stable and actionable:

- Deterministic, fast **PR benchmarks** (record/replay fixtures)
- Full-fidelity **nightly/release benchmarks** (real OpenAI + Postgres + Chroma)

---

## Problem Statement

### Current State

MCP Memory V6 has **functional tests** that verify features work, but **no quality tests** that measure how well they work.

| Feature | Functional Test | Quality Benchmark |
|---------|-----------------|-------------------|
| Event extraction | "Events get extracted" | "Correct events extracted with 85%+ F1" |
| Entity resolution | "Entities are found" | "People/orgs correctly identified" |
| Recall search | "Results returned" | "Relevant results ranked higher" |
| Graph expansion | "Related docs returned" | "Connections are meaningful" |

### The Gap

```
Current Tests:
  ✅ remember() stores content
  ✅ recall() returns results
  ✅ events get queued for extraction
  ✅ graph expansion returns related items

Missing Tests:
  ❌ Are the extracted events CORRECT?
  ❌ Are search results RELEVANT?
  ❌ Are graph connections MEANINGFUL?
  ❌ What's our precision/recall/F1?
```

### Why This Matters

1. **No visibility into quality degradation** - Model updates, prompt changes, or code refactors could silently degrade extraction quality
2. **No baseline for improvement** - Can't measure if changes improve or hurt quality
3. **No confidence in production** - Deploying without knowing actual accuracy
4. **User trust** - Users need to know the system returns accurate, relevant results

### Real-World Failure Modes

| Failure | Impact | Currently Detectable? |
|---------|--------|----------------------|
| LLM extracts wrong event type | "Commitment" labeled as "Decision" | ❌ No |
| Entity resolution misses a person | Graph connections incomplete | ❌ No |
| Search returns irrelevant top result | User loses trust | ❌ No |
| Graph expands to unrelated docs | Noise in context | ❌ No |

---

## Proposed Solution

### Overview

Create a benchmark suite with:
1. **Labeled test corpus** - Documents with ground-truth annotations
2. **Quality metrics** - Precision, Recall, F1, MRR, NDCG
3. **Automated evaluation** - Run benchmarks deterministically on PRs and full-fidelity on schedule
4. **Quality gates** - Prevent regressions with stable gating (nightly/release)

### Execution Strategy (Deterministic PRs + Full-Fidelity Nightly)

Quality evaluation that depends on a live LLM and external services is inherently non-deterministic (model updates, sampling, rate limits, network). To avoid flaky CI while still measuring real quality, V7 uses a two-tier strategy:

#### Tier 1: PR Benchmarks (Deterministic, Fast, Blocking)

Goal: ensure evaluation code, scoring logic, and benchmark harness don’t regress.

- Run in **record/replay mode** using **frozen fixtures**:
  - frozen event extraction outputs
  - frozen entity outputs
  - frozen retrieval result lists for fixed queries (or frozen embeddings + deterministic ranking)
- PR gating checks:
  - benchmark runner completes
  - metric computations match expected values
  - no unexpected drift in fixture outputs (unless explicitly re-recorded)

#### Tier 2: Nightly/Release Benchmarks (Real, Non-Deterministic, Gated at Release)

Goal: measure real-world system quality against a labeled corpus using the current production-like configuration.

- Runs with **real OpenAI + Postgres + Chroma**
- Produces a report + trend history
- Used to gate **releases** (or alert on degradation), not individual PRs

### Architecture

```
.claude-workspace/benchmarks/
├── corpus/                      # Labeled test documents
│   ├── meetings/               # Meeting notes (10-15 docs)
│   ├── emails/                 # Email threads (10-15 docs)
│   ├── decisions/              # Decision documents (5-10 docs)
│   └── conversations/          # Chat logs (5-10 docs)
│
├── ground_truth/               # Expected outputs
│   ├── events.json             # Document ID -> expected events
│   ├── entities.json           # Document ID -> expected entities
│   └── relevance.json          # Query -> ranked document relevance
│
├── queries/                    # Test query sets
│   ├── semantic_queries.json   # Natural language queries
│   └── entity_queries.json     # Entity-focused queries
│
├── tests/
│   ├── test_event_extraction.py
│   ├── test_entity_resolution.py
│   ├── test_recall_relevance.py
│   └── test_graph_expansion.py
│
├── metrics/
│   ├── extraction_metrics.py   # Precision, Recall, F1
│   ├── retrieval_metrics.py    # MRR, NDCG, MAP
│   └── graph_metrics.py        # Connection accuracy
│
├── reports/
│   └── benchmark_report.html   # Generated quality report
│
└── run_benchmarks.py           # Main benchmark runner
```

### Non-Goals (kept as functional tests, not “quality benchmarks”)

These are critical use cases but should remain as deterministic functional/integration tests (outside this benchmark suite):

- `remember()` idempotency/dedup behavior
- `forget()` confirm flag and cascade deletion behavior
- `recall(conversation_id=...)` ordering/limit behavior
- `recall(id="evt_...")` direct event lookup behavior

---

## Component 1: Event Extraction Benchmarks

### Ground Truth Schema

```json
{
  "document_id": "meeting_001",
  "expected_events": [
    {
      "category": "Decision",
      "description": "Launch product on April 1st",
      "actor": "Alice Chen",
      "confidence": "high"
    },
    {
      "category": "Commitment",
      "description": "Deliver API by March 25th",
      "actor": "Bob Smith",
      "due_date": "2024-03-25",
      "confidence": "high"
    }
  ]
}
```

### Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| **Precision** | TP / (TP + FP) | > 80% |
| **Recall** | TP / (TP + FN) | > 75% |
| **F1 Score** | 2 * (P * R) / (P + R) | > 77% |
| **Category Accuracy** | Correct category / Total | > 85% |
| **Actor Accuracy** | Correct actor / Total | > 80% |

### Matching Logic

```python
def events_match(expected: Event, extracted: Event) -> bool:
    """
    Two events match if:
    1. Same category (Decision, Commitment, etc.)
    2. Narrative/description match using deterministic normalization first
       (casefold, punctuation stripping, number/date normalization)
    3. Actor matches (fuzzy name matching)

    Optional (nightly only):
    - semantic similarity > threshold using a pinned embedding model/version
    """
    category_match = expected.category == extracted.category
    desc_similarity = semantic_similarity(expected.description, extracted.description)
    actor_match = fuzzy_name_match(expected.actor, extracted.actor)

    return category_match and desc_similarity > 0.8 and actor_match
```

> **Note:** For deterministic PR benchmarks, prefer matching on normalized text + stable IDs (doc_id + evidence spans) and avoid embedding-based similarity unless the embedding model/version is pinned and results are recorded.

---

## Component 2: Entity Resolution Benchmarks

### Ground Truth Schema

```json
{
  "document_id": "meeting_001",
  "expected_entities": [
    {
      "name": "Alice Chen",
      "type": "PERSON",
      "role": "Product Manager",
      "mentions": ["Alice", "Alice Chen", "AC"]
    },
    {
      "name": "Project Alpha",
      "type": "PROJECT",
      "mentions": ["Alpha", "Project Alpha", "the project"]
    }
  ]
}
```

### Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| **Entity Precision** | Extracted entities that are correct | > 85% |
| **Entity Recall** | Expected entities that were found | > 80% |
| **Deduplication Accuracy** | Same entity mentions merged correctly | > 90% |
| **Type Accuracy** | Correct entity type (PERSON, ORG, PROJECT) | > 90% |

---

## Component 3: Recall Relevance Benchmarks

### Ground Truth Schema

```json
{
  "queries": [
    {
      "query": "What decisions did Alice make about pricing?",
      "relevant_documents": [
        {"id": "meeting_001", "relevance": 3},
        {"id": "meeting_005", "relevance": 2},
        {"id": "email_012", "relevance": 1}
      ]
    }
  ]
}
```

Relevance scale:
- **3**: Highly relevant (directly answers query)
- **2**: Relevant (contains useful context)
- **1**: Marginally relevant (tangentially related)
- **0**: Not relevant

### Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| **MRR** | Mean Reciprocal Rank | > 0.7 |
| **NDCG@5** | Normalized DCG at top 5 | > 0.75 |
| **NDCG@10** | Normalized DCG at top 10 | > 0.8 |
| **Precision@3** | Precision at top 3 results | > 0.8 |
| **Recall@10** | Recall at top 10 results | > 0.9 |

### Metric Formulas

```python
def mrr(queries: List[QueryResult]) -> float:
    """Mean Reciprocal Rank - where does first relevant result appear?"""
    reciprocal_ranks = []
    for q in queries:
        for rank, doc in enumerate(q.results, 1):
            if doc.is_relevant:
                reciprocal_ranks.append(1.0 / rank)
                break
        else:
            reciprocal_ranks.append(0.0)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)

def ndcg_at_k(results: List[Doc], relevance: Dict[str, int], k: int) -> float:
    """Normalized Discounted Cumulative Gain"""
    dcg = sum(
        relevance.get(doc.id, 0) / log2(rank + 1)
        for rank, doc in enumerate(results[:k], 1)
    )
    ideal_order = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum(rel / log2(rank + 1) for rank, rel in enumerate(ideal_order, 1))
    return dcg / idcg if idcg > 0 else 0.0
```

---

## Component 4: Graph Expansion Benchmarks

### What “Graph Expansion” Means in V6

V6 does **not** require an external graph database. “Graph expansion” means:

- Seed events/entities found for primary results (from Postgres)
- Expand to **related events** via SQL joins (shared entities/actors/subjects, category filters, budget)
- Return related context items with reasons and optional evidence spans

### Ground Truth Schema

```json
{
  "seed_document": "meeting_001",
  "expected_connections": [
    {
      "document_id": "meeting_005",
      "connection_reason": "shared_entity",
      "entity": "Alice Chen",
      "relevance": "high"
    },
    {
      "document_id": "email_003",
      "connection_reason": "shared_event",
      "event": "Product launch decision",
      "relevance": "medium"
    }
  ],
  "expected_not_connected": [
    "meeting_099"  // Unrelated document
  ]
}
```

### Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| **Connection Precision** | Returned connections that are valid | > 85% |
| **Connection Recall** | Expected connections that were found | > 75% |
| **False Positive Rate** | Unrelated docs incorrectly connected | < 10% |
| **Hop Accuracy** | Correct relationship path | > 80% |

> **Implementation note:** prefer scoring **related events/context items** rather than “related documents” unless the implementation explicitly returns document IDs for expanded items.

---

## Test Corpus Design

### Document Categories

| Category | Count | Characteristics |
|----------|-------|-----------------|
| **Meeting Notes** | 15 | Multi-person, decisions, action items |
| **Email Threads** | 15 | Back-and-forth, commitments, questions |
| **Decision Records** | 10 | Formal decisions, rationale, stakeholders |
| **Chat Logs** | 10 | Informal, quick exchanges, context needed |

### Corpus Properties

1. **Diverse content types** - Various domains (engineering, product, sales)
2. **Varying complexity** - Simple single-event docs to complex multi-event
3. **Entity overlap** - Same people/projects across documents (for graph testing)
4. **Realistic noise** - Typos, abbreviations, informal language
5. **Edge cases** - Ambiguous events, unclear actors, implicit decisions

### Example Document

```markdown
# meeting_001.txt

Subject: Q1 Planning - Product Launch
Date: 2024-03-15
Attendees: Alice Chen (PM), Bob Smith (Eng Lead), Carol Davis (Design)

## Discussion

Alice presented the Q1 roadmap. Key points:

1. **Launch Date**: After discussion, Alice decided we will launch on April 1st.
   This gives us 2 weeks buffer before the conference.

2. **Pricing**: The team agreed to go with a freemium model. Bob raised concerns
   about infrastructure costs, but Alice confirmed budget approval.

## Action Items

- Bob: Complete API refactor by March 25th
- Carol: Finalize UI mockups by March 20th
- Alice: Send launch announcement draft by March 18th

## Next Steps

Follow-up meeting scheduled for March 22nd to review progress.
```

### Ground Truth for meeting_001

```json
{
  "document_id": "meeting_001",
  "events": [
    {
      "category": "Decision",
      "description": "Launch on April 1st",
      "actor": "Alice Chen",
      "evidence": "Alice decided we will launch on April 1st"
    },
    {
      "category": "Decision",
      "description": "Use freemium pricing model",
      "actor": "Team",
      "evidence": "The team agreed to go with a freemium model"
    },
    {
      "category": "Commitment",
      "description": "Complete API refactor",
      "actor": "Bob Smith",
      "due_date": "2024-03-25",
      "evidence": "Bob: Complete API refactor by March 25th"
    },
    {
      "category": "Commitment",
      "description": "Finalize UI mockups",
      "actor": "Carol Davis",
      "due_date": "2024-03-20",
      "evidence": "Carol: Finalize UI mockups by March 20th"
    },
    {
      "category": "Commitment",
      "description": "Send launch announcement draft",
      "actor": "Alice Chen",
      "due_date": "2024-03-18",
      "evidence": "Alice: Send launch announcement draft by March 18th"
    }
  ],
  "entities": [
    {"name": "Alice Chen", "type": "PERSON", "role": "PM"},
    {"name": "Bob Smith", "type": "PERSON", "role": "Eng Lead"},
    {"name": "Carol Davis", "type": "PERSON", "role": "Design"},
    {"name": "Q1 Planning", "type": "PROJECT"}
  ]
}
```

---

## Implementation Plan

### Phase 1: Corpus Creation (Week 1)

1. Create an initial **MVP corpus (10–15 labeled documents)**, then grow toward 50+
2. Define ground truth for events and entities
3. Create an initial **MVP query set (10–15 queries)**, then grow toward 30+
4. Define expected graph connections

### Phase 2: Metrics Implementation (Week 2)

1. Implement extraction metrics (precision, recall, F1)
2. Implement retrieval metrics (MRR, NDCG)
3. Implement graph metrics (connection accuracy)
4. Create matching/comparison logic

### Phase 3: Test Runner (Week 3)

1. Build benchmark runner script
2. Integrate with pytest
3. Generate HTML reports
4. Add CI/CD integration

### Phase 4: Baseline & Tuning (Week 4)

1. Run initial benchmarks
2. Establish baseline metrics
3. Identify improvement areas
4. Tune prompts/thresholds

---

## Quality Gates

### Release Criteria

| Metric | Minimum | Target | Blocking? |
|--------|---------|--------|-----------|
| Event Extraction F1 | 70% | 80% | Yes |
| Entity Resolution F1 | 75% | 85% | Yes |
| Recall MRR | 0.6 | 0.75 | Yes |
| Recall NDCG@10 | 0.7 | 0.85 | No |
| Graph Precision | 75% | 85% | No |

### CI/CD Integration

```yaml
# .github/workflows/benchmarks.yml
name: Quality Benchmarks

on:
  pull_request:
    paths:
      - 'src/services/**'
      - 'src/tools/**'
  schedule:
    - cron: '0 6 * * 1'  # Weekly Monday 6am

jobs:
  benchmarks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Run PR Benchmarks (deterministic record/replay)
        if: github.event_name == 'pull_request'
        run: python run_benchmarks.py --mode=replay --report

      - name: Run Nightly Benchmarks (full-fidelity)
        if: github.event_name != 'pull_request'
        run: python run_benchmarks.py --mode=live --report

      - name: Check Quality Gates
        run: python check_quality_gates.py --fail-on-regression --mode=${{ github.event_name == 'pull_request' && 'replay' || 'live' }}

      - name: Upload Report
        uses: actions/upload-artifact@v3
        with:
          name: benchmark-report
          path: reports/benchmark_report.html
```

### Benchmark Modes

`run_benchmarks.py` supports:

- `--mode=replay` (PR default): use frozen fixtures under `.claude-workspace/benchmarks/fixtures/`
- `--mode=live` (nightly/release): run against real services (OpenAI/Postgres/Chroma)

---

## Success Criteria

### MVP Complete (2026-01-01):

- [x] 12 labeled test documents created (MVP target: 10-15)
- [x] Ground truth defined (63 events, 20 entities)
- [x] 15 test queries with relevance judgments (MVP target: 10-15)
- [x] Extraction metrics implemented (P/R/F1) with 37 unit tests
- [x] Retrieval metrics implemented (MRR, NDCG)
- [x] Graph metrics implemented (connection P/R) - metric function only
- [x] Benchmark runner with strict replay mode (fails on missing fixtures)
- [x] Complete fixtures for all 12 docs and 15 queries
- [x] Documentation complete (README, TEST_SUMMARY, TESTING_PROGRESS)

### Completed Beyond MVP:

- [x] Entity extraction wired into benchmark runner
- [x] Graph expansion ground truth dataset (5 queries, 17 entity connections)
- [x] Graph expansion wired into benchmark runner
- [x] Entity fixtures for all 12 documents
- [x] Graph fixtures for all 5 queries
- [x] All 4 benchmark dimensions running end-to-end

### Current Status: Replay Mode Complete

The benchmark suite runs all 4 dimensions in replay mode with complete fixtures:
- Events: 12/12 fixtures, 63 ground truth events
- Entities: 12/12 fixtures, 20 unique entities (61 mentions across docs)
- Retrieval: 15/15 fixtures
- Graph: 5/5 fixtures

### Live Mode (Tested, V6 Prompt Issue Found):

- [x] Test live mode against real V6 server with Docker stack
- [x] Validate MCP protocol handling (session, SSE responses, reconnection)
- [x] Tune extraction polling timeouts for real LLM latency (2s intervals, 60 max)
- [ ] **V6 Extraction Prompt Fix Required**: LLM returns plural categories (Commitments, Decisions)
  instead of required singular forms (Commitment, Decision), causing events to be filtered.
  - See worker logs: `Invalid category: Commitments`, `Invalid category: Decisions`
  - This is a V6 extraction prompt issue in `event_extraction.py`, not a benchmark issue
  - Once fixed, live mode recording will produce meaningful fixtures
- [ ] Record real (non-synthetic) fixtures after V6 prompt fix

### Future Scope:

- [ ] Expand to 50+ labeled documents
- [ ] Expand to 30+ queries
- [ ] Add cross-document event linking benchmarks
- [ ] CI/CD integration with GitHub Actions
- [ ] Quality gate enforcement on PRs

### Stretch Goals:

- [ ] A/B testing framework for prompt changes
- [ ] Regression detection with alerting
- [ ] Benchmark leaderboard for different model versions
- [ ] Automatic prompt optimization based on metrics

---

## Appendix: Event Categories

| Category | Description | Example |
|----------|-------------|---------|
| **Decision** | A choice that was made | "We decided to use React" |
| **Commitment** | A promise to do something | "I'll have it done by Friday" |
| **QualityRisk** | A risk or concern raised | "This might not scale" |
| **Execution** | Work completed or progress | "Finished the API integration" |
| **Collaboration** | Request or offer of help | "Can you review this PR?" |
| **Feedback** | Opinion or evaluation | "The design looks great" |
| **Change** | Modification to plans | "We're pushing the deadline" |
| **Stakeholder** | Person/team mentioned | "Need to loop in legal" |

---

## References

- [Information Retrieval Metrics](https://en.wikipedia.org/wiki/Evaluation_measures_(information_retrieval))
- [Named Entity Recognition Evaluation](https://aclanthology.org/W03-0419/)
- [BEIR Benchmark](https://github.com/beir-cellar/beir) - Retrieval benchmark inspiration
- [SQuAD Evaluation](https://rajpurkar.github.io/SQuAD-explorer/) - F1 matching approach
