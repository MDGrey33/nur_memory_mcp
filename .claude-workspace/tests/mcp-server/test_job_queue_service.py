"""
Unit tests for JobQueueService.

Tests job creation, claiming, retry logic, and atomic event writes.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from uuid import UUID, uuid4
import json

from services.job_queue_service import JobQueueService


# ============================================================================
# Service Initialization Tests
# ============================================================================

def test_service_initialization(mock_postgres_client):
    """Test that JobQueueService initializes correctly."""
    service = JobQueueService(pg_client=mock_postgres_client, max_attempts=5)

    assert service.pg == mock_postgres_client
    assert service.max_attempts == 5


# ============================================================================
# Enqueue Job Tests
# ============================================================================

@pytest.mark.asyncio
async def test_enqueue_job_creates_new_job(mock_postgres_client, sample_job_id):
    """Test that enqueue_job creates a new job."""
    mock_postgres_client.fetch_val = AsyncMock(return_value=sample_job_id)

    service = JobQueueService(pg_client=mock_postgres_client)

    job_id = await service.enqueue_job(
        artifact_uid="art_123",
        revision_id="rev_456",
        job_type="extract_events"
    )

    assert job_id == sample_job_id
    mock_postgres_client.fetch_val.assert_called_once()
    call_args = mock_postgres_client.fetch_val.call_args
    assert "INSERT INTO event_jobs" in call_args[0][0]
    assert "ON CONFLICT" in call_args[0][0]


@pytest.mark.asyncio
async def test_enqueue_job_returns_none_if_exists(mock_postgres_client):
    """Test that enqueue_job returns None if job already exists (idempotent)."""
    mock_postgres_client.fetch_val = AsyncMock(return_value=None)

    service = JobQueueService(pg_client=mock_postgres_client)

    job_id = await service.enqueue_job(
        artifact_uid="art_123",
        revision_id="rev_456",
        job_type="extract_events"
    )

    assert job_id is None


@pytest.mark.asyncio
async def test_enqueue_job_uses_max_attempts(mock_postgres_client, sample_job_id):
    """Test that enqueue_job uses configured max_attempts."""
    mock_postgres_client.fetch_val = AsyncMock(return_value=sample_job_id)

    service = JobQueueService(pg_client=mock_postgres_client, max_attempts=10)

    await service.enqueue_job(
        artifact_uid="art_123",
        revision_id="rev_456"
    )

    call_args = mock_postgres_client.fetch_val.call_args
    # max_attempts should be passed as parameter
    assert call_args[0][4] == 10


@pytest.mark.asyncio
async def test_enqueue_job_raises_on_database_error(mock_postgres_client):
    """Test that enqueue_job raises exception on database error."""
    mock_postgres_client.fetch_val = AsyncMock(side_effect=Exception("DB error"))

    service = JobQueueService(pg_client=mock_postgres_client)

    with pytest.raises(Exception, match="DB error"):
        await service.enqueue_job(
            artifact_uid="art_123",
            revision_id="rev_456"
        )


# ============================================================================
# Claim Job Tests
# ============================================================================

@pytest.mark.asyncio
async def test_claim_job_claims_pending_job(mock_postgres_client, sample_job_id):
    """Test that claim_job atomically claims a pending job."""
    mock_conn = AsyncMock()
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock()

    mock_row = {
        "job_id": sample_job_id,
        "artifact_uid": "art_123",
        "revision_id": "rev_456",
        "attempts": 0
    }

    mock_conn.fetchrow = AsyncMock(return_value=mock_row)
    mock_conn.execute = AsyncMock()
    mock_conn.transaction.return_value = mock_transaction

    # Mock acquire context manager
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_postgres_client.acquire = mock_acquire

    service = JobQueueService(pg_client=mock_postgres_client)

    job = await service.claim_job(worker_id="worker-1")

    assert job is not None
    assert job["job_id"] == str(sample_job_id)
    assert job["artifact_uid"] == "art_123"
    assert job["revision_id"] == "rev_456"
    assert job["attempts"] == 1  # 0 + 1

    # Verify SELECT FOR UPDATE SKIP LOCKED was used
    select_call = mock_conn.fetchrow.call_args[0][0]
    assert "FOR UPDATE SKIP LOCKED" in select_call

    # Verify job was updated to PROCESSING
    update_call = mock_conn.execute.call_args[0][0]
    assert "UPDATE event_jobs" in update_call
    assert "PROCESSING" in update_call


@pytest.mark.asyncio
async def test_claim_job_returns_none_if_no_jobs(mock_postgres_client):
    """Test that claim_job returns None if no jobs available."""
    mock_conn = AsyncMock()
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock()

    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.transaction.return_value = mock_transaction

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_postgres_client.acquire = mock_acquire

    service = JobQueueService(pg_client=mock_postgres_client)

    job = await service.claim_job(worker_id="worker-1")

    assert job is None


@pytest.mark.asyncio
async def test_claim_job_increments_attempts(mock_postgres_client, sample_job_id):
    """Test that claim_job increments the attempts counter."""
    mock_conn = AsyncMock()
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock()

    mock_row = {
        "job_id": sample_job_id,
        "artifact_uid": "art_123",
        "revision_id": "rev_456",
        "attempts": 2  # Already tried twice
    }

    mock_conn.fetchrow = AsyncMock(return_value=mock_row)
    mock_conn.execute = AsyncMock()
    mock_conn.transaction.return_value = mock_transaction

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_postgres_client.acquire = mock_acquire

    service = JobQueueService(pg_client=mock_postgres_client)

    job = await service.claim_job(worker_id="worker-1")

    assert job["attempts"] == 3  # 2 + 1


# ============================================================================
# Mark Job Done Tests
# ============================================================================

@pytest.mark.asyncio
async def test_mark_job_done_updates_status(mock_postgres_client, sample_job_id):
    """Test that mark_job_done sets status to DONE."""
    mock_postgres_client.execute = AsyncMock()

    service = JobQueueService(pg_client=mock_postgres_client)

    await service.mark_job_done(sample_job_id)

    mock_postgres_client.execute.assert_called_once()
    call_args = mock_postgres_client.execute.call_args
    query = call_args[0][0]
    assert "UPDATE event_jobs" in query
    assert "DONE" in query
    assert call_args[0][1] == sample_job_id


# ============================================================================
# Mark Job Failed Tests
# ============================================================================

@pytest.mark.asyncio
async def test_mark_job_failed_with_retry(mock_postgres_client, sample_job_id):
    """Test that mark_job_failed retries if attempts < max_attempts."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "attempts": 2,
        "max_attempts": 5
    })
    mock_postgres_client.execute = AsyncMock()

    service = JobQueueService(pg_client=mock_postgres_client)

    await service.mark_job_failed(
        job_id=sample_job_id,
        error_code="TIMEOUT",
        error_message="Request timed out",
        retry=True
    )

    # Should set status to PENDING (for retry)
    call_args = mock_postgres_client.execute.call_args
    query = call_args[0][0]
    assert "UPDATE event_jobs" in query
    assert "PENDING" in query
    assert "next_run_at" in query

    # Check error tracking
    assert call_args[0][2] == "TIMEOUT"
    assert call_args[0][3] == "Request timed out"


@pytest.mark.asyncio
async def test_mark_job_failed_terminal_failure(mock_postgres_client, sample_job_id):
    """Test that mark_job_failed sets FAILED if max attempts reached."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "attempts": 5,
        "max_attempts": 5
    })
    mock_postgres_client.execute = AsyncMock()

    service = JobQueueService(pg_client=mock_postgres_client)

    await service.mark_job_failed(
        job_id=sample_job_id,
        error_code="EXTRACTION_ERROR",
        error_message="Failed to extract events",
        retry=True
    )

    # Should set status to FAILED (terminal)
    call_args = mock_postgres_client.execute.call_args
    query = call_args[0][0]
    assert "UPDATE event_jobs" in query
    assert "FAILED" in query


@pytest.mark.asyncio
async def test_mark_job_failed_without_retry(mock_postgres_client, sample_job_id):
    """Test that mark_job_failed sets FAILED if retry=False."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "attempts": 1,
        "max_attempts": 5
    })
    mock_postgres_client.execute = AsyncMock()

    service = JobQueueService(pg_client=mock_postgres_client)

    await service.mark_job_failed(
        job_id=sample_job_id,
        error_code="VALIDATION_ERROR",
        error_message="Invalid input",
        retry=False
    )

    # Should set status to FAILED (not retryable)
    call_args = mock_postgres_client.execute.call_args
    query = call_args[0][0]
    assert "FAILED" in query


@pytest.mark.asyncio
async def test_mark_job_failed_exponential_backoff(mock_postgres_client, sample_job_id):
    """Test that mark_job_failed uses exponential backoff for retries."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "attempts": 3,
        "max_attempts": 5
    })
    mock_postgres_client.execute = AsyncMock()

    service = JobQueueService(pg_client=mock_postgres_client)

    with patch("services.job_queue_service.datetime") as mock_datetime:
        mock_now = datetime(2025, 12, 27, 12, 0, 0)
        mock_datetime.utcnow.return_value = mock_now

        await service.mark_job_failed(
            job_id=sample_job_id,
            error_code="TIMEOUT",
            error_message="Request timed out",
            retry=True
        )

        call_args = mock_postgres_client.execute.call_args
        # Attempts = 3, so backoff = 30 * (2 ** 3) = 240 seconds
        next_run_at = call_args[0][1]
        expected = mock_now + timedelta(seconds=240)
        assert next_run_at == expected


# ============================================================================
# Get Job Status Tests
# ============================================================================

@pytest.mark.asyncio
async def test_get_job_status_with_revision_id(mock_postgres_client, sample_event_job_row):
    """Test that get_job_status returns job status for specific revision."""
    mock_postgres_client.fetch_one = AsyncMock(return_value=sample_event_job_row)

    service = JobQueueService(pg_client=mock_postgres_client)

    status = await service.get_job_status(
        artifact_uid="art_test_abc123",
        revision_id="rev_test_def456"
    )

    assert status is not None
    assert status["artifact_uid"] == "art_test_abc123"
    assert status["revision_id"] == "rev_test_def456"
    assert status["status"] == "PENDING"


@pytest.mark.asyncio
async def test_get_job_status_without_revision_id(mock_postgres_client):
    """Test that get_job_status gets latest revision if not specified."""
    mock_postgres_client.fetch_one = AsyncMock(side_effect=[
        {"revision_id": "rev_latest"},
        {
            "job_id": UUID("12345678-1234-5678-1234-567812345678"),
            "artifact_uid": "art_123",
            "revision_id": "rev_latest",
            "status": "DONE",
            "attempts": 1,
            "max_attempts": 5,
            "created_at": datetime(2025, 12, 27, 12, 0, 0),
            "updated_at": datetime(2025, 12, 27, 12, 5, 0),
            "locked_by": "worker-1",
            "last_error_code": None,
            "last_error_message": None,
            "next_run_at": None
        }
    ])

    service = JobQueueService(pg_client=mock_postgres_client)

    status = await service.get_job_status(artifact_uid="art_123")

    assert status is not None
    assert status["revision_id"] == "rev_latest"
    assert status["status"] == "DONE"


@pytest.mark.asyncio
async def test_get_job_status_returns_none_if_not_found(mock_postgres_client):
    """Test that get_job_status returns None if job not found."""
    mock_postgres_client.fetch_one = AsyncMock(return_value=None)

    service = JobQueueService(pg_client=mock_postgres_client)

    status = await service.get_job_status(
        artifact_uid="art_nonexistent",
        revision_id="rev_nonexistent"
    )

    assert status is None


# ============================================================================
# Write Events Atomic Tests
# ============================================================================

@pytest.mark.asyncio
async def test_write_events_atomic_deletes_old_events(
    mock_postgres_client,
    sample_artifact_uid,
    sample_revision_id,
    sample_extraction_run_id,
    sample_extracted_events
):
    """Test that write_events_atomic deletes old events before inserting new ones."""
    mock_conn = AsyncMock()
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock()

    mock_conn.execute = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
    mock_conn.transaction.return_value = mock_transaction

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_postgres_client.acquire = mock_acquire

    service = JobQueueService(pg_client=mock_postgres_client)

    await service.write_events_atomic(
        artifact_uid=sample_artifact_uid,
        revision_id=sample_revision_id,
        extraction_run_id=sample_extraction_run_id,
        events=sample_extracted_events[:1]  # Just one event for simplicity
    )

    # Check that DELETE was called first
    delete_call = mock_conn.execute.call_args_list[0]
    assert "DELETE FROM semantic_event" in delete_call[0][0]


@pytest.mark.asyncio
async def test_write_events_atomic_inserts_events_and_evidence(
    mock_postgres_client,
    sample_artifact_uid,
    sample_revision_id,
    sample_extraction_run_id,
    sample_extracted_events
):
    """Test that write_events_atomic inserts events and evidence."""
    mock_conn = AsyncMock()
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock()

    event_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    mock_conn.execute = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=event_id)
    mock_conn.transaction.return_value = mock_transaction

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_postgres_client.acquire = mock_acquire

    service = JobQueueService(pg_client=mock_postgres_client)

    await service.write_events_atomic(
        artifact_uid=sample_artifact_uid,
        revision_id=sample_revision_id,
        extraction_run_id=sample_extraction_run_id,
        events=sample_extracted_events[:1]
    )

    # Check that event was inserted
    fetchval_call = mock_conn.fetchval.call_args[0][0]
    assert "INSERT INTO semantic_event" in fetchval_call

    # Check that evidence was inserted
    execute_calls = [call[0][0] for call in mock_conn.execute.call_args_list]
    evidence_inserts = [call for call in execute_calls if "INSERT INTO event_evidence" in call]
    assert len(evidence_inserts) > 0


@pytest.mark.asyncio
async def test_write_events_atomic_handles_multiple_events(
    mock_postgres_client,
    sample_artifact_uid,
    sample_revision_id,
    sample_extraction_run_id,
    sample_extracted_events
):
    """Test that write_events_atomic handles multiple events."""
    mock_conn = AsyncMock()
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock()

    mock_conn.execute = AsyncMock()
    mock_conn.fetchval = AsyncMock(side_effect=[
        UUID(f"event-{i:08x}-0000-0000-0000-000000000000")
        for i in range(len(sample_extracted_events))
    ])
    mock_conn.transaction.return_value = mock_transaction

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_postgres_client.acquire = mock_acquire

    service = JobQueueService(pg_client=mock_postgres_client)

    await service.write_events_atomic(
        artifact_uid=sample_artifact_uid,
        revision_id=sample_revision_id,
        extraction_run_id=sample_extraction_run_id,
        events=sample_extracted_events
    )

    # Check that all events were inserted
    assert mock_conn.fetchval.call_count == len(sample_extracted_events)


@pytest.mark.asyncio
async def test_write_events_atomic_parses_event_time(
    mock_postgres_client,
    sample_artifact_uid,
    sample_revision_id,
    sample_extraction_run_id
):
    """Test that write_events_atomic parses ISO8601 event_time."""
    mock_conn = AsyncMock()
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock()

    mock_conn.execute = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
    mock_conn.transaction.return_value = mock_transaction

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_postgres_client.acquire = mock_acquire

    service = JobQueueService(pg_client=mock_postgres_client)

    events = [
        {
            "category": "Decision",
            "narrative": "Test event",
            "event_time": "2024-03-15T14:30:00Z",
            "subject": {"type": "project", "ref": "test"},
            "actors": [{"ref": "Alice", "role": "owner"}],
            "confidence": 0.9,
            "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
        }
    ]

    await service.write_events_atomic(
        artifact_uid=sample_artifact_uid,
        revision_id=sample_revision_id,
        extraction_run_id=sample_extraction_run_id,
        events=events
    )

    # Check that event_time was passed
    fetchval_call = mock_conn.fetchval.call_args[0]
    # event_time is the 4th parameter (index 3)
    event_time_param = fetchval_call[4]
    assert event_time_param is not None
    assert isinstance(event_time_param, datetime)


# ============================================================================
# Force Reextract Tests
# ============================================================================

@pytest.mark.asyncio
async def test_force_reextract_resets_done_job_with_force(
    mock_postgres_client,
    sample_artifact_uid,
    sample_revision_id
):
    """Test that force_reextract resets DONE job when force=True."""
    mock_postgres_client.fetch_one = AsyncMock(side_effect=[
        {"revision_id": sample_revision_id},  # Latest revision
        {  # Existing job status
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

    service = JobQueueService(pg_client=mock_postgres_client)

    result = await service.force_reextract(
        artifact_uid=sample_artifact_uid,
        revision_id=sample_revision_id,
        force=True
    )

    assert result["status"] == "PENDING"
    assert "force=true" in result["message"]
    mock_postgres_client.execute.assert_called_once()


@pytest.mark.asyncio
async def test_force_reextract_skips_done_job_without_force(mock_postgres_client):
    """Test that force_reextract skips DONE job when force=False."""
    mock_postgres_client.fetch_one = AsyncMock(side_effect=[
        {"revision_id": "rev_latest"},
        {
            "job_id": "job_123",
            "artifact_uid": "art_123",
            "revision_id": "rev_latest",
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

    service = JobQueueService(pg_client=mock_postgres_client)

    result = await service.force_reextract(
        artifact_uid="art_123",
        force=False
    )

    assert result["status"] == "DONE"
    assert "use force=true" in result["message"]


@pytest.mark.asyncio
async def test_force_reextract_creates_job_if_not_exists(
    mock_postgres_client,
    sample_job_id
):
    """Test that force_reextract creates job if it doesn't exist."""
    mock_postgres_client.fetch_one = AsyncMock(side_effect=[
        {"revision_id": "rev_latest"},
        None  # No existing job
    ])
    mock_postgres_client.fetch_val = AsyncMock(return_value=sample_job_id)

    service = JobQueueService(pg_client=mock_postgres_client)

    result = await service.force_reextract(
        artifact_uid="art_123",
        force=True
    )

    assert result["status"] == "PENDING"
    assert "enqueued" in result["message"]
    mock_postgres_client.fetch_val.assert_called_once()
