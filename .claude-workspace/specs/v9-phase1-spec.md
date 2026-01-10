# V9 Phase 1: Extraction Quality Fix - Specification

**Task ID**: task-20260110-172229
**Status**: Ready for Implementation
**Priority**: CRITICAL

---

## Problem Statement

The extraction F1 score is **0.19** (target: 0.70). Investigation reveals:

**Root Cause**: The benchmark runs in "live" mode and times out waiting for events. The 30-second wait is insufficient for LLM-based extraction that can take 60+ seconds per document.

**Evidence**:
- Local fixture test shows meeting_002 should get F1=0.75 (6/7 events match)
- Live benchmark shows meeting_002 gets F1=0.00 (FP=0, FN=9 - zero events extracted)
- This means events ARE being extracted correctly, but benchmark times out before they're available

---

## Technical Analysis

### Extraction Pipeline Flow

```
remember(content)
    → queue extract_events job
    → event_worker processes job (30-60s with LLM calls)
    → events stored in semantic_event table
    → recall(id=artifact_id) fetches events
```

### Benchmark Wait Logic (Current)

```python
# benchmark_runner.py:425
async def _wait_and_fetch_events(self, artifact_id: str, max_wait: int = 30):
    for i in range(max_wait):
        await asyncio.sleep(2)  # Poll every 2 seconds
        # ... fetch events via recall()
```

**Problem**: `max_wait=30` means 30 iterations × 2 seconds = 60 seconds max wait. But each document can have multiple chunks, each requiring:
- Embedding generation (~1-2s per chunk)
- LLM extraction call (~5-15s per chunk)
- Entity resolution (~1-2s)

For a 3-chunk document, this easily exceeds 60 seconds.

### Why Some Documents Work (meeting_001) and Others Fail (meeting_002)

| Document | Chunks | Events | Wait Time (est) | 30s Timeout |
|----------|--------|--------|-----------------|-------------|
| meeting_001 | 1 | 5 | ~20s | OK |
| meeting_002 | 2 | 9 | ~45s | FAIL |
| meeting_005 | 3 | 12 | ~70s | FAIL |

---

## Proposed Fix

### Fix 1: Increase Benchmark Wait Timeout

**File**: `.claude-workspace/benchmarks/tests/benchmark_runner.py`

```python
# Change line 425
async def _wait_and_fetch_events(self, artifact_id: str, max_wait: int = 60):
    """Wait for event extraction to complete and return events."""
```

Also update the initial status check delay:

```python
# Add early exit if status shows job complete
result = await self._call_tool("status", {"artifact_id": artifact_id})
if result.get("job_status", {}).get("status") == "COMPLETED":
    # Job done, fetch events immediately
    break
```

### Fix 2: Check Job Status Before Polling Events

Instead of blindly polling for events, check if the extraction job has completed:

```python
async def _wait_and_fetch_events(self, artifact_id: str, max_wait: int = 90):
    """Wait for event extraction to complete and return events."""
    for i in range(max_wait):
        await asyncio.sleep(2)

        # Check job status first
        status_result = await self._call_tool("status", {"artifact_id": artifact_id})
        job_info = status_result.get("job_status", {})

        if job_info.get("status") == "FAILED":
            print(f"      [{artifact_id}] extraction FAILED: {job_info.get('error')}")
            return []

        if job_info.get("status") == "COMPLETED":
            # Job done, fetch events
            events = await self._fetch_events(artifact_id)
            return events

        # Job still pending
        if i % 10 == 0:
            print(f"      [{artifact_id}] waiting... {i*2}s (status={job_info.get('status', 'UNKNOWN')})")

    # Timeout - log warning and return whatever events exist
    print(f"      [{artifact_id}] TIMEOUT after {max_wait*2}s")
    return await self._fetch_events(artifact_id)
```

### Fix 3: Add Extraction Job Status to recall() Response

**File**: `.claude-workspace/implementation/mcp-server/src/server.py`

When recalling by ID, include job status:

```python
# In recall() for id-based retrieval
if id:
    # ... existing code ...

    # Add job status for this artifact
    job_status = None
    if pg_client:
        job_row = await pg_client.fetch_one(
            "SELECT status, error_message FROM event_jobs WHERE artifact_uid = $1 ORDER BY created_at DESC LIMIT 1",
            artifact_uid
        )
        if job_row:
            job_status = {
                "status": job_row["status"],
                "error": job_row.get("error_message")
            }

    result["job_status"] = job_status
```

---

## Implementation Tasks

| Task | File | Priority |
|------|------|----------|
| 1. Increase max_wait to 90 | benchmark_runner.py | HIGH |
| 2. Add job status check to wait loop | benchmark_runner.py | HIGH |
| 3. Add job_status to recall() response | server.py | MEDIUM |
| 4. Re-run benchmarks | - | HIGH |

---

## Success Criteria

After fixes:

| Metric | Current | Target | Pass Condition |
|--------|---------|--------|----------------|
| Extraction F1 | 0.19 | 0.70 | >= 0.50 (Phase 1) |
| meeting_002 F1 | 0.00 | ~0.75 | > 0.60 |
| meeting_005 F1 | 0.00 | ~0.70 | > 0.50 |
| No timeout errors | N/A | 0 | 0 timeouts |

---

## Verification Plan

```bash
# 1. Apply fixes
# 2. Run benchmark in live mode
cd .claude-workspace/benchmarks
python tests/benchmark_runner.py --mode=live

# 3. Check per-document F1 scores
# All documents should have F1 > 0 (no more 0.00 scores)

# 4. Compare to fixture-based expected scores
# meeting_002 should get ~0.75 (based on fixture analysis)
```

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Longer wait increases benchmark time | Accept: correctness > speed for benchmarks |
| Job status query adds latency | Minimal: single DB query |
| OpenAI rate limits | Already handled by extraction service |
