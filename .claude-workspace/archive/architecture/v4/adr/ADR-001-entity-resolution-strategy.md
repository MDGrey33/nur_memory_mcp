# ADR-001: Entity Resolution Strategy

**Status:** Accepted
**Date:** 2025-12-28
**Deciders:** Senior Architect, Technical PM
**Context Level:** V4 Graph-backed Context Expansion

---

## Context

V4 introduces graph-backed context expansion to `hybrid_search`, which requires identifying relationships between semantic events across documents. The core challenge is **entity resolution**: determining when "Alice Chen" in document A refers to the same person as "A. Chen" in document B.

### The Problem

V3 stores actors and subjects as string references in JSONB columns (`actors_json`, `subject_json`). These strings are not linked across documents:

```json
// Document A
{"actors": [{"ref": "Alice Chen", "role": "owner"}]}

// Document B
{"actors": [{"ref": "A. Chen", "role": "contributor"}]}
```

Without entity resolution, the graph cannot answer: "What other events involve Alice Chen?"

### Requirements

1. **High Accuracy**: Must correctly merge "Alice Chen" and "A. Chen" (same person)
2. **Avoid False Merges**: Must NOT merge "Alice Chen (Engineer at Acme)" with "Alice Chen (Designer at OtherCorp)"
3. **Evidence Trail**: Preserve which surface forms appeared in which documents
4. **Reasonable Cost**: Target ~$0.02/document for entity resolution
5. **Performance**: Entity resolution should not significantly slow ingestion

### Options Considered

#### Option A: Exact String Matching Only

Simply match entities with identical normalized names.

**Pros:**
- Fast (O(1) lookup)
- Zero LLM cost
- Deterministic

**Cons:**
- "Alice Chen" and "A. Chen" never match
- High false negative rate (different surface forms for same entity)
- Graph connectivity would be poor

#### Option B: Fuzzy String Matching (Levenshtein Distance)

Use edit distance algorithms to find similar names.

**Pros:**
- Handles minor variations ("Alice" vs "Alicia")
- No LLM cost
- Fast

**Cons:**
- "Bob Chen" and "Rob Chen" would incorrectly match
- Cannot use context (role, org) for disambiguation
- High false positive rate for common names

#### Option C: Embedding-Only Matching

Generate embeddings for entity names + context, use vector similarity.

**Pros:**
- Semantic similarity captures context
- Can encode role/org information
- Moderate cost (~$0.0001/entity)

**Cons:**
- Cannot explain decisions
- Threshold tuning is difficult
- May still produce false positives for similar-but-different entities

#### Option D: Two-Phase (Embedding + LLM Confirmation)

1. **Phase A**: Generate embedding for entity context, find candidates with similarity > 0.85
2. **Phase B**: Call LLM to confirm merge decision for each candidate pair

**Pros:**
- Embedding pre-filter reduces LLM calls from O(n^2) to O(candidates)
- LLM sees full context for high-stakes decisions
- Can output "uncertain" to avoid premature merges
- Explainable decisions (LLM provides reasoning)

**Cons:**
- Higher cost than pure embedding approach
- Slight latency increase for entity resolution
- Requires LLM call per candidate pair

---

## Decision

**We will implement Option D: Two-Phase (Embedding + LLM Confirmation)**

### Rationale

1. **Quality is Critical**: Entity resolution errors compound across the graph. A false merge corrupts all downstream relationships. The LLM confirmation step provides the precision needed for high-stakes decisions.

2. **Cost is Manageable**: The embedding pre-filter dramatically reduces LLM calls:
   - 1000 entities, 3 candidates avg = 3000 LLM calls total
   - At $0.001/call = $3 for 1000 entities
   - This is ~$0.003/document (negligible vs. extraction cost)

3. **Context Enables Disambiguation**: The LLM can use role, organization, and email to distinguish "Alice Chen at Acme" from "Alice Chen at OtherCorp" - something no string matching can do.

4. **Graceful Uncertainty Handling**: When the LLM cannot decide confidently, it outputs "uncertain" and we create a `POSSIBLY_SAME` edge instead of forcing a potentially wrong merge. This preserves the signal for later manual review.

---

## Implementation Details

### Phase A: Candidate Generation

```python
async def find_dedup_candidates(
    entity_type: str,
    context_embedding: list[float],
    threshold: float = 0.85
) -> list[Entity]:
    """
    Find candidate entities for deduplication using embedding similarity.

    SQL:
    SELECT * FROM entity
    WHERE entity_type = $type
      AND context_embedding <=> $embedding < (1 - $threshold)
    ORDER BY context_embedding <=> $embedding
    LIMIT 5
    """
```

**Embedding Context String:**
```
"{canonical_name}, {type}, {role}, {org}"
Example: "Alice Chen, person, Engineering Manager, Acme Corp"
```

### Phase B: LLM Confirmation

```python
async def confirm_merge_with_llm(
    entity_a: Entity,
    entity_b: Entity,
    context_a: dict,
    context_b: dict
) -> MergeDecision:
    """
    Call LLM to confirm whether two entities are the same.

    Returns:
        MergeDecision with:
        - decision: "same" | "different" | "uncertain"
        - canonical_name: Best name to use (if "same")
        - reason: Explanation for the decision
    """
```

**LLM Prompt:**
```
You are determining if two entity mentions refer to the same real-world entity.

ENTITY A (from document "{title_a}"):
- Name: "{name_a}"
- Type: {type_a}
- Context: {context_a}

ENTITY B (from document "{title_b}"):
- Name: "{name_b}"
- Type: {type_b}
- Context: {context_b}

Rules:
- "same" = High confidence these refer to the same real-world entity
- "different" = High confidence these are different entities
- "uncertain" = Not enough information to decide confidently

Return JSON:
{"decision": "same|different|uncertain", "canonical_name": "...", "reason": "..."}
```

### Decision Actions

| Decision | Action |
|----------|--------|
| `same` | Merge: link mention to existing entity, add alias |
| `different` | Create new entity |
| `uncertain` | Create new entity, set `needs_review=true`, add `POSSIBLY_SAME` edge |

---

## Consequences

### Positive

1. **High Accuracy**: LLM confirmation with context prevents most false merges
2. **Explainable**: Every merge decision has a reason that can be audited
3. **Graceful Degradation**: "Uncertain" decisions don't corrupt the graph
4. **Future-Proof**: Review queue enables manual disambiguation later
5. **Efficient Pre-filter**: Embedding similarity keeps LLM costs manageable

### Negative

1. **Increased Latency**: ~100ms per candidate pair for LLM call
2. **Additional Cost**: ~$0.001 per candidate pair
3. **Complexity**: Two-phase logic is more complex than simple matching
4. **LLM Dependency**: Entity resolution fails if OpenAI API is unavailable

### Mitigations

| Risk | Mitigation |
|------|------------|
| LLM unavailable | Fall back to embedding-only with conservative threshold (0.95) |
| High candidate count | Cap at 5 candidates per entity |
| Cost overrun | Log cost per document, alert if >$0.05/doc |
| False uncertain | Batch manual review periodically |

---

## Related ADRs

- **ADR-002**: Graph Database Choice (Apache AGE)
- **ADR-003**: Entity Resolution Timing
- **ADR-004**: Graph Model Simplification

---

## References

- V4 Brief: `/v4.md`
- V4 Specification: `/.claude-workspace/specs/v4-specification.md`
- V3 Architecture: `/.claude-workspace/architecture/v3-architecture.md`
