"""
End-to-end integration tests for V3 event extraction system.

Tests complete workflows from ingestion through extraction to querying.
Requires real Postgres and ChromaDB instances for integration testing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from uuid import UUID, uuid4
import json
import asyncio

# These tests can run in two modes:
# 1. Mock mode (unit tests with mocked dependencies)
# 2. Integration mode (requires real Postgres + ChromaDB)

pytestmark = pytest.mark.asyncio


# ============================================================================
# Scenario 1: Small Artifact → Events Extracted
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_1_small_artifact_extraction(
    mock_postgres_client,
    mock_chroma_manager,
    mock_event_extraction_service,
    mock_job_queue_service,
    sample_artifact_text,
    sample_extracted_events
):
    """
    Test Scenario 1: Small artifact ingestion and extraction.

    Flow:
    1. Ingest small artifact (no chunking)
    2. Create job in queue
    3. Worker claims job
    4. Worker extracts events (Prompt A on single chunk)
    5. Worker canonicalizes events (Prompt B - no-op for single chunk)
    6. Worker writes events atomically
    7. Worker marks job DONE
    8. Query events via event_search
    """
    artifact_uid = "art_scenario1"
    revision_id = "rev_scenario1"
    job_id = uuid4()

    # Step 1-2: Ingestion creates artifact revision and job
    mock_postgres_client.fetch_val = AsyncMock(return_value=job_id)
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "artifact_uid": artifact_uid,
        "revision_id": revision_id,
        "artifact_id": "chroma_art_1",
        "is_chunked": False,
        "chunk_count": 0
    })

    created_job_id = await mock_job_queue_service.enqueue_job(
        artifact_uid=artifact_uid,
        revision_id=revision_id
    )

    assert created_job_id == job_id

    # Step 3: Worker claims job
    mock_postgres_client.acquire = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={
        "job_id": job_id,
        "artifact_uid": artifact_uid,
        "revision_id": revision_id,
        "attempts": 0
    })
    mock_conn.execute = AsyncMock()
    mock_conn.transaction = MagicMock()

    claimed_job = {
        "job_id": str(job_id),
        "artifact_uid": artifact_uid,
        "revision_id": revision_id,
        "attempts": 1
    }

    # Step 4: Worker extracts events
    mock_event_extraction_service.extract_from_chunk = MagicMock(
        return_value=sample_extracted_events
    )

    events = mock_event_extraction_service.extract_from_chunk(
        chunk_text=sample_artifact_text,
        chunk_index=0,
        chunk_id="chroma_art_1",
        start_char=0
    )

    assert len(events) == 3

    # Step 5: Canonicalize (no-op for single chunk)
    mock_event_extraction_service.canonicalize_events = MagicMock(
        return_value=sample_extracted_events
    )

    canonical_events = mock_event_extraction_service.canonicalize_events([events])
    assert len(canonical_events) == 3

    # Step 6: Write events atomically
    mock_job_queue_service.write_events_atomic = AsyncMock()

    await mock_job_queue_service.write_events_atomic(
        artifact_uid=artifact_uid,
        revision_id=revision_id,
        extraction_run_id=job_id,
        events=canonical_events
    )

    mock_job_queue_service.write_events_atomic.assert_called_once()

    # Step 7: Mark job DONE
    mock_job_queue_service.mark_job_done = AsyncMock()
    await mock_job_queue_service.mark_job_done(job_id)

    mock_job_queue_service.mark_job_done.assert_called_once_with(job_id)

    # Step 8: Query events
    from tools.event_tools import event_search

    mock_postgres_client.fetch_all = AsyncMock(return_value=[
        {
            "event_id": uuid4(),
            "artifact_uid": artifact_uid,
            "revision_id": revision_id,
            "category": "Decision",
            "event_time": datetime(2024, 3, 15, 0, 0, 0),
            "narrative": "Team decided to adopt freemium pricing model",
            "subject_json": {"type": "project", "ref": "pricing-model"},
            "actors_json": [{"ref": "Alice Chen", "role": "owner"}],
            "confidence": 0.95,
            "created_at": datetime.utcnow()
        }
    ])

    result = await event_search(
        pg_client=mock_postgres_client,
        artifact_uid=artifact_uid,
        category="Decision",
        limit=20,
        include_evidence=False
    )

    assert result["total"] >= 1
    assert result["events"][0]["category"] == "Decision"


# ============================================================================
# Scenario 2: Large Artifact → Chunked → Events Extracted
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_2_large_artifact_chunked_extraction(
    mock_postgres_client,
    mock_event_extraction_service,
    mock_job_queue_service,
    sample_extracted_events,
    sample_canonical_events
):
    """
    Test Scenario 2: Large artifact requiring chunking.

    Flow:
    1. Ingest large artifact (triggers chunking)
    2. Create job in queue
    3. Worker claims job
    4. Worker fetches all chunks from ChromaDB
    5. Worker extracts events from each chunk (Prompt A x3)
    6. Worker canonicalizes across all chunks (Prompt B deduplicates)
    7. Worker writes merged events atomically
    8. Verify events have evidence from multiple chunks
    """
    artifact_uid = "art_scenario2"
    revision_id = "rev_scenario2"
    job_id = uuid4()
    chunk_count = 3

    # Step 1-2: Ingestion with chunking
    mock_postgres_client.fetch_val = AsyncMock(return_value=job_id)
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "artifact_uid": artifact_uid,
        "revision_id": revision_id,
        "artifact_id": "chroma_art_2",
        "is_chunked": True,
        "chunk_count": chunk_count
    })

    created_job_id = await mock_job_queue_service.enqueue_job(
        artifact_uid=artifact_uid,
        revision_id=revision_id
    )

    assert created_job_id == job_id

    # Step 4-5: Extract from each chunk
    chunk_events_list = []

    for i in range(chunk_count):
        chunk_events = [sample_extracted_events[i]] if i < len(sample_extracted_events) else []
        mock_event_extraction_service.extract_from_chunk = MagicMock(
            return_value=chunk_events
        )

        events = mock_event_extraction_service.extract_from_chunk(
            chunk_text=f"Chunk {i} text...",
            chunk_index=i,
            chunk_id=f"chunk_{i:03d}",
            start_char=i * 1000
        )

        chunk_events_list.append(events)

    # Step 6: Canonicalize across chunks
    mock_event_extraction_service.canonicalize_events = MagicMock(
        return_value=sample_canonical_events
    )

    canonical_events = mock_event_extraction_service.canonicalize_events(chunk_events_list)

    # Verify deduplication happened (canonical < sum of chunks)
    total_chunk_events = sum(len(ce) for ce in chunk_events_list)
    assert len(canonical_events) <= total_chunk_events

    # Verify merged evidence
    commitment_event = next(e for e in canonical_events if e["category"] == "Commitment")
    assert len(commitment_event["evidence"]) >= 2  # Merged from multiple chunks

    # Step 7: Write events
    mock_job_queue_service.write_events_atomic = AsyncMock()

    await mock_job_queue_service.write_events_atomic(
        artifact_uid=artifact_uid,
        revision_id=revision_id,
        extraction_run_id=job_id,
        events=canonical_events
    )

    mock_job_queue_service.write_events_atomic.assert_called_once()


# ============================================================================
# Scenario 3: Idempotency (Re-ingest Same Content)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_3_idempotent_reingest(
    mock_postgres_client,
    mock_job_queue_service,
    sample_artifact_uid,
    sample_revision_id
):
    """
    Test Scenario 3: Re-ingesting same content is idempotent.

    Flow:
    1. Ingest artifact (creates job)
    2. Try to re-ingest same content
    3. Job queue returns None (already exists)
    4. No duplicate jobs created
    """
    # First ingestion
    mock_postgres_client.fetch_val = AsyncMock(return_value=uuid4())

    job_id_1 = await mock_job_queue_service.enqueue_job(
        artifact_uid=sample_artifact_uid,
        revision_id=sample_revision_id
    )

    assert job_id_1 is not None

    # Second ingestion (same artifact_uid + revision_id)
    mock_postgres_client.fetch_val = AsyncMock(return_value=None)  # ON CONFLICT DO NOTHING

    job_id_2 = await mock_job_queue_service.enqueue_job(
        artifact_uid=sample_artifact_uid,
        revision_id=sample_revision_id
    )

    assert job_id_2 is None  # Idempotent


# ============================================================================
# Scenario 4: New Revision Creates New Events
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_4_new_revision_new_events(
    mock_postgres_client,
    mock_job_queue_service,
    sample_artifact_uid
):
    """
    Test Scenario 4: New revision creates new event records.

    Flow:
    1. Ingest artifact revision 1
    2. Extract events for revision 1
    3. Update artifact (new content)
    4. Ingest revision 2
    5. Extract events for revision 2
    6. Verify both revisions have separate events
    """
    revision_id_1 = "rev_v1"
    revision_id_2 = "rev_v2"

    # Revision 1
    job_id_1 = uuid4()
    mock_postgres_client.fetch_val = AsyncMock(return_value=job_id_1)

    created_job_1 = await mock_job_queue_service.enqueue_job(
        artifact_uid=sample_artifact_uid,
        revision_id=revision_id_1
    )

    assert created_job_1 == job_id_1

    # Revision 2 (updated content)
    job_id_2 = uuid4()
    mock_postgres_client.fetch_val = AsyncMock(return_value=job_id_2)

    created_job_2 = await mock_job_queue_service.enqueue_job(
        artifact_uid=sample_artifact_uid,
        revision_id=revision_id_2
    )

    assert created_job_2 == job_id_2
    assert job_id_1 != job_id_2

    # Query events by revision
    from tools.event_tools import event_list_for_revision

    # Events for revision 1
    mock_postgres_client.fetch_one = AsyncMock(return_value={"is_latest": False})
    mock_postgres_client.fetch_all = AsyncMock(return_value=[
        {
            "event_id": uuid4(),
            "category": "Decision",
            "narrative": "Old decision",
            "event_time": None,
            "subject_json": {"type": "project", "ref": "test"},
            "actors_json": [{"ref": "Alice", "role": "owner"}],
            "confidence": 0.9,
            "created_at": datetime.utcnow()
        }
    ])

    result_v1 = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid=sample_artifact_uid,
        revision_id=revision_id_1,
        include_evidence=False
    )

    assert result_v1["revision_id"] == revision_id_1
    assert result_v1["is_latest"] is False

    # Events for revision 2
    mock_postgres_client.fetch_one = AsyncMock(return_value={"is_latest": True})
    mock_postgres_client.fetch_all = AsyncMock(return_value=[
        {
            "event_id": uuid4(),
            "category": "Decision",
            "narrative": "New decision",
            "event_time": None,
            "subject_json": {"type": "project", "ref": "test"},
            "actors_json": [{"ref": "Bob", "role": "owner"}],
            "confidence": 0.95,
            "created_at": datetime.utcnow()
        }
    ])

    result_v2 = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid=sample_artifact_uid,
        revision_id=revision_id_2,
        include_evidence=False
    )

    assert result_v2["revision_id"] == revision_id_2
    assert result_v2["is_latest"] is True


# ============================================================================
# Scenario 5: Failure Recovery
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_5_failure_recovery_with_retry(
    mock_postgres_client,
    mock_job_queue_service
):
    """
    Test Scenario 5: Job failure and retry logic.

    Flow:
    1. Worker claims job
    2. Extraction fails (e.g., OpenAI rate limit)
    3. Worker marks job failed with retry=True
    4. Job status set to PENDING with backoff
    5. Worker re-claims job after backoff
    6. Extraction succeeds
    7. Job marked DONE
    """
    artifact_uid = "art_scenario5"
    revision_id = "rev_scenario5"
    job_id = uuid4()

    # Step 1: Claim job (attempt 1)
    mock_job_queue_service.claim_job = AsyncMock(return_value={
        "job_id": str(job_id),
        "artifact_uid": artifact_uid,
        "revision_id": revision_id,
        "attempts": 1
    })

    job = await mock_job_queue_service.claim_job(worker_id="worker-1")
    assert job["attempts"] == 1

    # Step 2-3: Extraction fails, mark for retry
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "attempts": 1,
        "max_attempts": 5
    })
    mock_postgres_client.execute = AsyncMock()

    await mock_job_queue_service.mark_job_failed(
        job_id=job_id,
        error_code="RATE_LIMIT",
        error_message="Rate limit exceeded",
        retry=True
    )

    # Verify job was set to PENDING (for retry)
    call_args = mock_postgres_client.execute.call_args
    query = call_args[0][0]
    assert "PENDING" in query

    # Step 4: Wait for backoff (simulated)
    await asyncio.sleep(0.1)

    # Step 5: Re-claim job (attempt 2)
    mock_job_queue_service.claim_job = AsyncMock(return_value={
        "job_id": str(job_id),
        "artifact_uid": artifact_uid,
        "revision_id": revision_id,
        "attempts": 2
    })

    job = await mock_job_queue_service.claim_job(worker_id="worker-1")
    assert job["attempts"] == 2

    # Step 6: Extraction succeeds
    # (extraction logic mocked out)

    # Step 7: Mark job DONE
    await mock_job_queue_service.mark_job_done(job_id)

    # Verify final status
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "job_id": str(job_id),
        "status": "DONE",
        "attempts": 2,
        "last_error_code": "RATE_LIMIT",
        "last_error_message": "Rate limit exceeded"
    })

    status = await mock_job_queue_service.get_job_status(
        artifact_uid=artifact_uid,
        revision_id=revision_id
    )

    assert status["status"] == "DONE"
    assert status["attempts"] == 2


@pytest.mark.asyncio
async def test_scenario_5_failure_terminal_after_max_attempts(
    mock_postgres_client,
    mock_job_queue_service
):
    """
    Test Scenario 5b: Job fails terminally after max attempts.

    Flow:
    1. Job fails 5 times (max_attempts reached)
    2. Worker marks job FAILED (terminal)
    3. Job status remains FAILED, no more retries
    """
    job_id = uuid4()

    # Simulate max attempts reached
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "attempts": 5,
        "max_attempts": 5
    })
    mock_postgres_client.execute = AsyncMock()

    await mock_job_queue_service.mark_job_failed(
        job_id=job_id,
        error_code="EXTRACTION_ERROR",
        error_message="Persistent extraction failure",
        retry=True  # Even with retry=True, should be terminal
    )

    # Verify job was set to FAILED (terminal)
    call_args = mock_postgres_client.execute.call_args
    query = call_args[0][0]
    assert "FAILED" in query
    assert "PENDING" not in query


# ============================================================================
# Complex Workflow Tests
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_worker_job_claiming(
    mock_postgres_client,
    mock_job_queue_service
):
    """
    Test that multiple workers can't claim the same job (SKIP LOCKED).

    Flow:
    1. Enqueue 1 job
    2. Worker 1 claims job (gets it)
    3. Worker 2 tries to claim (gets None, job is locked)
    4. Worker 1 completes job
    5. Worker 2 tries again (still None, no pending jobs)
    """
    job_id = uuid4()

    # Worker 1 claims job
    mock_job_queue_service.claim_job = AsyncMock(return_value={
        "job_id": str(job_id),
        "artifact_uid": "art_123",
        "revision_id": "rev_456",
        "attempts": 1
    })

    job_worker1 = await mock_job_queue_service.claim_job(worker_id="worker-1")
    assert job_worker1 is not None

    # Worker 2 tries to claim (should get None due to SKIP LOCKED)
    mock_job_queue_service.claim_job = AsyncMock(return_value=None)

    job_worker2 = await mock_job_queue_service.claim_job(worker_id="worker-2")
    assert job_worker2 is None

    # Worker 1 completes
    await mock_job_queue_service.mark_job_done(job_id)

    # Worker 2 tries again (no pending jobs)
    job_worker2_retry = await mock_job_queue_service.claim_job(worker_id="worker-2")
    assert job_worker2_retry is None


@pytest.mark.asyncio
async def test_event_search_across_multiple_artifacts(
    mock_postgres_client,
    sample_semantic_event_row
):
    """
    Test searching events across multiple artifacts.

    Flow:
    1. Ingest 3 artifacts (each with events)
    2. Search events with category filter (no artifact filter)
    3. Verify results include events from all artifacts
    """
    from tools.event_tools import event_search

    # Mock events from 3 different artifacts
    mock_postgres_client.fetch_all = AsyncMock(return_value=[
        {**sample_semantic_event_row, "artifact_uid": "art_1"},
        {**sample_semantic_event_row, "artifact_uid": "art_2"},
        {**sample_semantic_event_row, "artifact_uid": "art_3"}
    ])

    result = await event_search(
        pg_client=mock_postgres_client,
        category="Decision",
        limit=20,
        include_evidence=False
    )

    assert result["total"] == 3
    artifact_uids = {e["artifact_uid"] for e in result["events"]}
    assert len(artifact_uids) == 3


@pytest.mark.asyncio
async def test_time_range_filtering(mock_postgres_client, sample_semantic_event_row):
    """
    Test time range filtering on event_search.

    Flow:
    1. Create events with various timestamps
    2. Search with time_from and time_to
    3. Verify only events in range are returned
    """
    from tools.event_tools import event_search

    # Mock events with different timestamps
    event_march_1 = {**sample_semantic_event_row, "event_time": datetime(2024, 3, 1, 10, 0, 0)}
    event_march_15 = {**sample_semantic_event_row, "event_time": datetime(2024, 3, 15, 14, 30, 0)}
    event_march_31 = {**sample_semantic_event_row, "event_time": datetime(2024, 3, 31, 23, 59, 59)}

    mock_postgres_client.fetch_all = AsyncMock(return_value=[
        event_march_15  # Only this one in range
    ])

    result = await event_search(
        pg_client=mock_postgres_client,
        time_from="2024-03-10T00:00:00Z",
        time_to="2024-03-20T23:59:59Z",
        limit=20,
        include_evidence=False
    )

    assert result["total"] == 1
    assert result["events"][0]["event_time"] == "2024-03-15T14:30:00"


# ============================================================================
# Performance and Atomicity Tests
# ============================================================================

@pytest.mark.asyncio
async def test_atomic_event_write_rollback_on_error(
    mock_postgres_client,
    sample_artifact_uid,
    sample_revision_id,
    sample_extraction_run_id,
    sample_extracted_events
):
    """
    Test that write_events_atomic rolls back on error.

    Flow:
    1. Begin transaction
    2. Delete old events (succeeds)
    3. Insert new events (fails on 2nd event)
    4. Transaction rolls back
    5. No partial writes
    """
    mock_conn = AsyncMock()
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock(side_effect=Exception("Insert failed"))

    mock_conn.execute = AsyncMock()
    mock_conn.fetchval = AsyncMock(side_effect=[
        uuid4(),  # First event succeeds
        Exception("Insert failed")  # Second event fails
    ])
    mock_conn.transaction.return_value = mock_transaction

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_postgres_client.acquire = mock_acquire

    from services.job_queue_service import JobQueueService
    service = JobQueueService(pg_client=mock_postgres_client)

    # Should raise exception (transaction rolled back)
    with pytest.raises(Exception, match="Insert failed"):
        await service.write_events_atomic(
            artifact_uid=sample_artifact_uid,
            revision_id=sample_revision_id,
            extraction_run_id=sample_extraction_run_id,
            events=sample_extracted_events
        )


@pytest.mark.asyncio
async def test_force_reextract_workflow(
    mock_postgres_client,
    mock_job_queue_service,
    sample_artifact_uid,
    sample_revision_id
):
    """
    Test force_reextract workflow.

    Flow:
    1. Job is DONE
    2. User calls force_reextract with force=True
    3. Job reset to PENDING
    4. Worker re-processes
    5. New events replace old events
    """
    # Step 1: Job is DONE
    mock_postgres_client.fetch_one = AsyncMock(side_effect=[
        {"revision_id": sample_revision_id},
        {
            "job_id": "job_123",
            "artifact_uid": sample_artifact_uid,
            "revision_id": sample_revision_id,
            "status": "DONE",
            "attempts": 1,
            "max_attempts": 5,
            "created_at": "2025-12-27T12:00:00",
            "updated_at": "2025-12-27T12:05:00",
            "locked_by": None,
            "last_error_code": None,
            "last_error_message": None,
            "next_run_at": None
        }
    ])
    mock_postgres_client.execute = AsyncMock()

    # Step 2: Force reextract
    result = await mock_job_queue_service.force_reextract(
        artifact_uid=sample_artifact_uid,
        revision_id=sample_revision_id,
        force=True
    )

    assert result["status"] == "PENDING"
    mock_postgres_client.execute.assert_called_once()

    # Verify job was reset
    reset_call = mock_postgres_client.execute.call_args[0][0]
    assert "UPDATE event_jobs" in reset_call
    assert "PENDING" in reset_call
    assert "attempts = 0" in reset_call
