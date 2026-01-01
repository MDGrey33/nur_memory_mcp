# ADR-002: Two-Phase Event Extraction with Replace-on-Success

**Status:** Accepted
**Date:** 2025-12-27
**Author:** Senior Architect
**Deciders:** Technical PM, Senior Architect, Lead Backend Engineer

---

## Context

V3 needs to extract semantic events from documents that may be chunked (900 token chunks with 100 token overlap). We must:

1. **Handle chunked documents**: Large documents (> 1200 tokens) are split into chunks
2. **Preserve evidence traceability**: Every event must link to exact source text with character offsets
3. **Deduplicate events**: Same event mentioned in multiple chunks should not create duplicates
4. **Maintain consistency**: Partial extraction failures should not leave corrupted state

We evaluated three extraction approaches:

1. **Single-pass extraction**: Process all chunks in one LLM call
2. **Incremental extraction**: Extract per chunk, append to database incrementally
3. **Two-phase with replace-on-success**: Extract per chunk (Prompt A), canonicalize (Prompt B), write atomically

---

## Decision

**We will use two-phase extraction with replace-on-success semantics.**

Implementation:

### Phase 1: Extract (Prompt A) - Per Chunk
- For each chunk, call OpenAI with Prompt A
- Input: Single chunk text
- Output: JSON with entities + events + evidence (offsets relative to chunk)
- Store results in memory (not database)

### Phase 2: Canonicalize (Prompt B) - Cross-Chunk
- Aggregate all chunk extractions
- Call OpenAI with Prompt B
- Input: All chunk results as JSON array
- Output: Canonical event list (deduplicated, merged evidence)

### Phase 3: Write Atomically
- BEGIN TRANSACTION
- DELETE old events for (artifact_uid, revision_id)
- INSERT all canonical events + evidence
- COMMIT
- Mark job DONE

---

## Consequences

### Positive

1. **Chunk-Level Accuracy**: Prompt A sees full context within each chunk
   - LLM can accurately extract events without token limit issues
   - Evidence offsets are precise (relative to chunk boundaries)

2. **Deduplication**: Prompt B merges duplicate events across chunks
   - Example: "Alice committed to Q1 delivery" mentioned in chunks 0, 2, 5
   - Prompt B outputs ONE event with 3 evidence spans

3. **Atomic Writes**: Replace-on-success guarantees consistency
   - Either ALL events written or NONE
   - No partial states in database
   - Failed extractions leave previous version intact (or no events if first run)

4. **Evidence Traceability**: Every event preserves exact character offsets
   - Offsets calculated: `chunk_start_char + chunk_relative_offset`
   - Can retrieve exact quote from ChromaDB using offsets

5. **Retryable**: If extraction fails, worker retries entire process
   - DELETE + INSERT is idempotent per revision
   - No cleanup of partial writes needed

### Negative

1. **Higher Token Cost**: Two LLM calls instead of one
   - Prompt A: N calls (one per chunk)
   - Prompt B: 1 call (all chunk results)
   - **Accepted**: Cost < $0.10/doc typical, negligible vs. value

2. **Longer Extraction Time**: Sequential processing adds latency
   - **Mitigated**: Prompt A calls can be parallelized (future optimization)
   - Current: 5-60s total, acceptable for async processing

3. **Replace Semantics**: Cannot incrementally update events
   - If user wants to re-extract with improved prompts, ALL events replaced
   - **Accepted**: Full replacement is simpler and more consistent

### Neutral

1. **LLM Quality Dependency**: Extraction quality depends on GPT-4-Turbo
   - Both two-phase and single-pass have this dependency
   - Prompt engineering is iterative regardless of approach

---

## Alternatives Considered

### Option 1: Single-Pass Extraction

**Description**: Process all chunks in one LLM call.

```python
prompt = f"""
Extract events from this document (chunked):

Chunk 0: {chunk_0_text}
Chunk 1: {chunk_1_text}
...
Chunk N: {chunk_n_text}
"""
```

**Pros**:
- Single LLM call (lower cost)
- Faster (no two-phase processing)

**Cons**:
- **Token Limit**: Large documents (10K+ tokens) exceed context window
  - GPT-4-Turbo: 128K tokens, but quality degrades after ~32K
- **Evidence Offsets**: Unclear which chunk contains each evidence span
  - Would need post-processing to map offsets back to chunks
- **Loss of Chunk Context**: LLM sees all chunks at once, may miss local context

**Verdict**: Rejected due to token limits and offset ambiguity

### Option 2: Incremental Extraction (Append-Only)

**Description**: Extract per chunk, write events to database incrementally.

```python
for chunk in chunks:
    events = extract_from_chunk(chunk)  # Prompt A
    INSERT INTO semantic_event VALUES (...) FOR EACH event
```

**Pros**:
- Simpler (no Prompt B canonicalization)
- Faster (no aggregation step)

**Cons**:
- **Duplicate Events**: Same event in multiple chunks creates N duplicates
  - Example: "Alice committed to Q1" in chunks 0, 2, 5 = 3 separate events
- **Partial Writes**: If extraction fails mid-way, database has partial events
  - Cleanup required: DELETE events for failed revision
  - Complexity: Track which events to keep vs. delete
- **No Entity Resolution**: Cannot merge "Alice", "A. Chen", "Alice Chen"

**Verdict**: Rejected due to duplicate events and partial write complexity

### Option 3: Streaming Extraction with Manual Deduplication

**Description**: Extract per chunk, deduplicate in application code.

```python
event_map = {}
for chunk in chunks:
    events = extract_from_chunk(chunk)
    for event in events:
        if event.narrative not in event_map:
            event_map[event.narrative] = event
        else:
            event_map[event.narrative].evidence.extend(event.evidence)

INSERT INTO semantic_event VALUES (...) FOR EACH unique_event
```

**Pros**:
- No Prompt B needed (lower cost)
- Application-level deduplication (deterministic)

**Cons**:
- **Naive Deduplication**: Relies on exact narrative match
  - "Alice will deliver by Q1" vs. "Alice committed to Q1 delivery" = 2 events (should be 1)
- **No Semantic Understanding**: Cannot merge paraphrased events
- **Brittle**: Requires manual rules for entity resolution

**Verdict**: Rejected due to lack of semantic deduplication

---

## Implementation Details

### Prompt A: Extract (Per Chunk)

**Purpose**: Extract entities and events from a single chunk with evidence.

**Input**:
```
You are a semantic event extraction assistant. Extract entities and events from this text chunk.

RULES:
1. Only extract what is DIRECTLY SUPPORTED by the text.
2. Evidence quotes must be <= 25 words.
3. Evidence offsets are character positions (0-indexed) within this chunk.
4. Output ONLY valid JSON.

INPUT TEXT:
---
{chunk_text}
---

OUTPUT SCHEMA: {...}
```

**Output** (JSON):
```json
{
  "entities": [
    {"name": "Alice Chen", "type": "person", "aliases": ["Alice"]}
  ],
  "events": [
    {
      "category": "Commitment",
      "event_time": "2024-03-15T14:30:00Z",
      "narrative": "Alice committed to deliver MVP by Q1",
      "subject": {"type": "project", "ref": "MVP"},
      "actors": [{"ref": "Alice Chen", "role": "owner"}],
      "confidence": 0.9,
      "evidence": [
        {
          "quote": "Alice will deliver the MVP by end of Q1",
          "start_char": 1250,
          "end_char": 1290
        }
      ]
    }
  ]
}
```

### Prompt B: Canonicalize (Cross-Chunk)

**Purpose**: Merge duplicate events and resolve entity aliases.

**Input**:
```
You are a semantic event canonicalization assistant. Merge duplicate events from multiple chunks.

RULES:
1. Merge events with same semantic meaning (even if worded differently).
2. Combine evidence from all chunks.
3. Resolve entity aliases (e.g., "Alice" = "Alice Chen").
4. Output ONLY valid JSON.

INPUT (Chunk Extractions):
---
{json.dumps(chunk_extractions, indent=2)}
---

OUTPUT SCHEMA: {...}
```

**Output** (JSON):
```json
{
  "canonical_events": [
    {
      "category": "Commitment",
      "event_time": "2024-03-15T14:30:00Z",
      "narrative": "Alice committed to deliver MVP by Q1",
      "subject": {"type": "project", "ref": "MVP"},
      "actors": [{"ref": "Alice Chen", "role": "owner"}],
      "confidence": 0.95,
      "evidence_list": [
        {
          "quote": "Alice will deliver the MVP by end of Q1",
          "start_char": 1250,  // chunk_0_start + 1250
          "end_char": 1290,
          "chunk_id": "art_abc::chunk::000::xyz"
        },
        {
          "quote": "A. Chen confirmed Q1 MVP timeline",
          "start_char": 5620,  // chunk_2_start + offset
          "end_char": 5655,
          "chunk_id": "art_abc::chunk::002::xyz"
        }
      ]
    }
  ]
}
```

### Replace-on-Success Write

```sql
BEGIN;

-- Delete old events for this revision
DELETE FROM semantic_event
WHERE artifact_uid = :uid AND revision_id = :rev;

-- Insert canonical events
FOR EACH canonical_event:
    INSERT INTO semantic_event (...) RETURNING event_id;
    FOR EACH evidence_span:
        INSERT INTO event_evidence (...);

COMMIT;

-- Mark job DONE
UPDATE event_jobs SET status = 'DONE' WHERE job_id = :job_id;
```

---

## Model Selection

### Why GPT-4-Turbo-Preview?

| Model | Context | JSON Mode | Quality | Cost |
|-------|---------|-----------|---------|------|
| **GPT-4-Turbo** | 128K | Yes (strict) | Highest | $$$ |
| GPT-3.5-Turbo | 16K | Yes | Good | $ |
| Claude Opus 4.5 | 200K | Yes | Highest | $$$$ |
| Local (Llama 3) | 8K | No | Medium | Free |

**Decision**: GPT-4-Turbo-Preview

**Rationale**:
1. **Strict JSON Mode**: Guarantees valid JSON output (no parsing errors)
2. **Context Window**: 128K tokens sufficient for large chunk lists in Prompt B
3. **Quality**: Best-in-class for structured extraction tasks
4. **Availability**: Production-ready API with SLA

**Future Consideration**: Claude Opus 4.5 (larger context, higher quality)
- Would need to validate JSON parsing reliability
- Cost comparison: ~$15/1M input tokens (similar to GPT-4-Turbo)

---

## Performance Characteristics

| Operation | Latency | Notes |
|-----------|---------|-------|
| Prompt A (per chunk) | 2-5s | Depends on chunk size |
| Prompt B (canonicalize) | 3-10s | Depends on # chunks |
| Database write | < 100ms | Atomic transaction |
| **Total per document** | **5-60s** | Scales with document size |

**Parallelization Opportunity** (Future):
- Prompt A calls are independent → can parallelize
- Potential speedup: N chunks in parallel = 2-5s regardless of N
- Estimated effort: 1 day (async API calls)

---

## Testing Strategy

### Unit Tests
1. **Prompt A Output Validation**: Assert JSON schema compliance
2. **Prompt B Deduplication**: Test that duplicates merge correctly
3. **Evidence Offset Calculation**: Verify chunk_start + relative_offset

### Integration Tests
1. **End-to-End Extraction**: Ingest document → wait for job DONE → assert events exist
2. **Retry Logic**: Simulate OpenAI 429 error → assert job retries
3. **Atomic Write**: Simulate failure after DELETE → assert no partial state

### Quality Tests
1. **Precision/Recall**: Human-labeled test corpus (50 documents)
   - Precision: % extracted events that are correct
   - Recall: % real events that were extracted
   - Target: 80%+ for both
2. **Evidence Traceability**: Assert all evidence quotes match source text

---

## Monitoring & Observability

**Metrics to Track**:
- Extraction time per document (p50, p90, p99)
- Events extracted per document (avg, max)
- Evidence spans per event (avg)
- OpenAI API errors (429, timeout, invalid JSON)
- Job retry rate (% jobs that retry at least once)

**Alerts**:
- Job failure rate > 5% in 1 hour
- OpenAI API error rate > 10% in 5 minutes
- Extraction time p99 > 5 minutes

---

## References

- [OpenAI Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- [Semantic Event Extraction](https://arxiv.org/abs/2004.04151)
- [Database Replace Semantics](https://www.postgresql.org/docs/current/sql-delete.html)

---

## Revision History

| Date | Author | Changes |
|------|--------|---------|
| 2025-12-27 | Senior Architect | Initial ADR |

---

**Status: Accepted**
