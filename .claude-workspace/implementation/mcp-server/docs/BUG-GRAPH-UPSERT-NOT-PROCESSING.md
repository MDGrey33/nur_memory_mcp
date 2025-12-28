# Bug Report: Graph Upsert Jobs Not Processing Correctly

## Summary
Graph upsert jobs (`graph_upsert`) are being incorrectly processed as event extraction jobs (`extract_events`), causing the AGE graph to remain empty even after successful event extraction.

## Severity
**High** - This bug prevents the V4 graph expansion feature from working entirely.

## Symptoms
1. After event extraction completes, `graph_upsert` jobs are created but graph remains empty
2. Entities and events exist in PostgreSQL relational tables but not in AGE graph
3. `hybrid_search` with `graph_expand=true` returns "0 related items"
4. Worker logs show "Processing extract_events job" for graph_upsert job IDs

## Root Cause
**File:** `src/services/job_queue_service.py`
**Method:** `claim_job()` (lines 75-131)

The `claim_job()` method has two bugs:

### Bug 1: No job_type filter in query
```python
# Line 90-98 - Missing job_type filter
select_query = """
SELECT job_id, artifact_uid, revision_id, attempts
FROM event_jobs
WHERE status = 'PENDING'
  AND next_run_at <= now()
ORDER BY created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1
"""
```
This query claims ANY pending job regardless of type (extract_events or graph_upsert).

### Bug 2: job_type not returned in result
```python
# Lines 122-127 - job_type not included
return {
    "job_id": str(job_id),
    "artifact_uid": row["artifact_uid"],
    "revision_id": row["revision_id"],
    "attempts": row["attempts"] + 1
}
```

## Impact Chain
1. Worker calls `claim_job()` which claims graph_upsert job
2. Worker receives job dict without `job_type` field
3. Worker routes to `_process_extract_events_job()` unconditionally
4. Graph_upsert job is processed as extract_events
5. A NEW graph_upsert job is enqueued (infinite loop)
6. Graph nodes/edges are never created

## Worker Flow (Buggy)
**File:** `src/worker/event_worker.py`
**Method:** `process_one_job()` (lines 179-193)

```python
async def process_one_job(self) -> None:
    # BUG: claim_job() returns ANY job type
    job = await self.job_service.claim_job(self.worker_id)

    if job:
        # BUG: Always routes to extract_events regardless of actual job_type
        await self._process_extract_events_job(job)
        return

    # This code is NEVER reached for graph_upsert jobs
    # because claim_job() already claimed them above
    if self.enable_v4 and self.graph_service:
        job = await self.job_service.claim_job_by_type(self.worker_id, "graph_upsert")
        if job:
            await self._process_graph_upsert_job(job)
```

## Evidence from Logs
```
2025-12-28 15:36:12,380 - job_queue - INFO - Enqueued graph_upsert job 6b783437-1d19-4934-b6bd-99e3b464c27e
...
2025-12-28 15:36:13,400 - event_worker - INFO - Processing extract_events job 6b783437-1d19-4934-b6bd-99e3b464c27e
```
Note: Job ID `6b783437...` is a `graph_upsert` job being processed as `extract_events`.

## Suggested Fixes

### Option A: Fix claim_job() to filter by type (Recommended)
```python
async def claim_job(self, worker_id: str, job_type: str = "extract_events") -> Optional[Dict[str, Any]]:
    # Add job_type filter to query
    select_query = """
    SELECT job_id, job_type, artifact_uid, revision_id, attempts
    FROM event_jobs
    WHERE status = 'PENDING'
      AND job_type = $1
      AND next_run_at <= now()
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
    """
    row = await conn.fetchrow(select_query, job_type)

    # Include job_type in return
    return {
        "job_id": str(job_id),
        "job_type": row["job_type"],
        "artifact_uid": row["artifact_uid"],
        "revision_id": row["revision_id"],
        "attempts": row["attempts"] + 1
    }
```

### Option B: Fix worker to use claim_job_by_type
```python
async def process_one_job(self) -> None:
    # Use type-specific claim
    job = await self.job_service.claim_job_by_type(self.worker_id, "extract_events")

    if job:
        await self._process_extract_events_job(job)
        return

    if self.enable_v4 and self.graph_service:
        job = await self.job_service.claim_job_by_type(self.worker_id, "graph_upsert")
        if job:
            await self._process_graph_upsert_job(job)
```

### Option C: Check job_type and route dynamically
```python
async def process_one_job(self) -> None:
    # Fix claim_job to return job_type first
    job = await self.job_service.claim_job(self.worker_id)

    if not job:
        return

    job_type = job.get("job_type", "extract_events")

    if job_type == "extract_events":
        await self._process_extract_events_job(job)
    elif job_type == "graph_upsert" and self.enable_v4:
        await self._process_graph_upsert_job(job)
    else:
        logger.warning(f"Unknown job type: {job_type}")
```

## Files to Modify
1. `src/services/job_queue_service.py` - Fix `claim_job()` method
2. `src/worker/event_worker.py` - Update `process_one_job()` routing

## Testing Steps
1. Reset any stuck jobs: `UPDATE event_jobs SET status = 'PENDING', locked_at = NULL WHERE status = 'PROCESSING';`
2. Clear existing data: `TRUNCATE entity, semantic_event, event_actor, event_subject CASCADE;`
3. Ingest a test artifact via MCP
4. Run worker: `docker exec -w /app/src mcp-server python -m worker`
5. Verify:
   - Job log shows "Processing graph_upsert job" (not extract_events)
   - `SELECT * FROM cypher('nur', $$ MATCH (n) RETURN n $$)` returns nodes
   - `hybrid_search` with `graph_expand=true` returns related items

## Current State
| Component | Status |
|-----------|--------|
| Entity extraction | Working |
| Event extraction | Working |
| Relational storage (entity, semantic_event) | Working |
| graph_upsert job enqueueing | Working |
| graph_upsert job processing | **BROKEN** |
| AGE graph nodes/edges | **EMPTY** |

## Related Code Locations
- `src/services/job_queue_service.py:75-131` - `claim_job()` bug location
- `src/services/job_queue_service.py:615-675` - `claim_job_by_type()` (works correctly)
- `src/worker/event_worker.py:179-193` - `process_one_job()` routing
- `src/worker/event_worker.py:385-469` - `_process_graph_upsert_job()` (never executed)
- `src/services/graph_service.py` - Graph upsert methods (untested due to bug)

## Database Schema Reference
```sql
-- event_jobs table
CREATE TABLE event_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type TEXT NOT NULL DEFAULT 'extract_events',  -- 'extract_events' or 'graph_upsert'
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    ...
    UNIQUE(artifact_uid, revision_id, job_type)
);
```

## Environment
- PostgreSQL with Apache AGE 1.6.0 on port 5433
- MCP Server on port 3001
- Worker runs inside mcp-server container: `docker exec -w /app/src mcp-server python -m worker`
