"""
Unit tests for V3 MCP event tools.

Tests event_search, event_get, event_list_for_revision, and job_status tools.
"""

import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from uuid import UUID

from tools.event_tools import (
    event_search,
    event_get,
    event_list_for_revision,
    EVENT_CATEGORIES
)


# ============================================================================
# Event Search Tests
# ============================================================================

@pytest.mark.asyncio
async def test_event_search_basic(mock_postgres_client, sample_semantic_event_row):
    """Test basic event search without filters."""
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    result = await event_search(
        pg_client=mock_postgres_client,
        limit=20,
        include_evidence=False
    )

    assert "events" in result
    assert len(result["events"]) == 1
    assert result["events"][0]["category"] == "Decision"
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_event_search_with_category_filter(mock_postgres_client, sample_semantic_event_row):
    """Test event search with category filter."""
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    result = await event_search(
        pg_client=mock_postgres_client,
        category="Decision",
        limit=20,
        include_evidence=False
    )

    assert "events" in result
    assert result["filters_applied"]["category"] == "Decision"

    # Verify SQL query includes category filter
    call_args = mock_postgres_client.fetch_all.call_args
    query = call_args[0][0]
    assert "e.category = $" in query


@pytest.mark.asyncio
async def test_event_search_with_time_range(mock_postgres_client, sample_semantic_event_row):
    """Test event search with time range filters."""
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    result = await event_search(
        pg_client=mock_postgres_client,
        time_from="2024-03-01T00:00:00Z",
        time_to="2024-03-31T23:59:59Z",
        limit=20,
        include_evidence=False
    )

    assert "events" in result
    assert "time_from" in result["filters_applied"]
    assert "time_to" in result["filters_applied"]

    # Verify SQL query includes time filters
    call_args = mock_postgres_client.fetch_all.call_args
    query = call_args[0][0]
    assert "e.event_time >=" in query
    assert "e.event_time <=" in query


@pytest.mark.asyncio
async def test_event_search_with_artifact_filter(mock_postgres_client, sample_semantic_event_row):
    """Test event search filtered by artifact_uid."""
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    result = await event_search(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        limit=20,
        include_evidence=False
    )

    assert "events" in result
    assert result["filters_applied"]["artifact_uid"] == "art_test_abc123"

    # Verify SQL query includes artifact filter
    call_args = mock_postgres_client.fetch_all.call_args
    query = call_args[0][0]
    assert "e.artifact_uid = $" in query


@pytest.mark.asyncio
async def test_event_search_with_text_query(mock_postgres_client, sample_semantic_event_row):
    """Test event search with full-text search on narrative."""
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    result = await event_search(
        pg_client=mock_postgres_client,
        query="pricing",
        limit=20,
        include_evidence=False
    )

    assert "events" in result
    assert result["filters_applied"]["query"] == "pricing"

    # Verify SQL query includes FTS
    call_args = mock_postgres_client.fetch_all.call_args
    query = call_args[0][0]
    assert "to_tsvector" in query
    assert "to_tsquery" in query


@pytest.mark.asyncio
async def test_event_search_with_evidence(
    mock_postgres_client,
    sample_semantic_event_row,
    sample_event_evidence_rows
):
    """Test event search includes evidence when requested."""
    mock_postgres_client.fetch_all = AsyncMock(side_effect=[
        [sample_semantic_event_row],
        sample_event_evidence_rows
    ])

    result = await event_search(
        pg_client=mock_postgres_client,
        limit=20,
        include_evidence=True
    )

    assert "events" in result
    assert len(result["events"]) == 1
    event = result["events"][0]
    assert "evidence" in event
    assert len(event["evidence"]) == 2
    assert event["evidence"][0]["quote"] == "decided to adopt a freemium pricing model"


@pytest.mark.asyncio
async def test_event_search_invalid_limit(mock_postgres_client):
    """Test event search rejects invalid limit."""
    result = await event_search(
        pg_client=mock_postgres_client,
        limit=0
    )

    assert "error" in result
    assert result["error_code"] == "INVALID_PARAMETER"


@pytest.mark.asyncio
async def test_event_search_invalid_limit_too_high(mock_postgres_client):
    """Test event search rejects limit > 100."""
    result = await event_search(
        pg_client=mock_postgres_client,
        limit=200
    )

    assert "error" in result
    assert result["error_code"] == "INVALID_PARAMETER"


@pytest.mark.asyncio
async def test_event_search_invalid_category(mock_postgres_client):
    """Test event search rejects invalid category."""
    result = await event_search(
        pg_client=mock_postgres_client,
        category="InvalidCategory"
    )

    assert "error" in result
    assert result["error_code"] == "INVALID_CATEGORY"
    assert "valid_categories" in result["details"]


@pytest.mark.asyncio
async def test_event_search_handles_database_error(mock_postgres_client):
    """Test event search handles database errors gracefully."""
    mock_postgres_client.fetch_all = AsyncMock(side_effect=Exception("DB error"))

    result = await event_search(
        pg_client=mock_postgres_client,
        limit=20
    )

    assert "error" in result
    assert result["error_code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_event_search_orders_by_time_desc(mock_postgres_client):
    """Test that event_search orders results by event_time DESC."""
    mock_postgres_client.fetch_all = AsyncMock(return_value=[])

    await event_search(
        pg_client=mock_postgres_client,
        limit=20,
        include_evidence=False
    )

    call_args = mock_postgres_client.fetch_all.call_args
    query = call_args[0][0]
    assert "ORDER BY e.event_time DESC NULLS LAST" in query


# ============================================================================
# Event Get Tests
# ============================================================================

@pytest.mark.asyncio
async def test_event_get_success(
    mock_postgres_client,
    sample_event_id,
    sample_semantic_event_row,
    sample_event_evidence_rows
):
    """Test successful retrieval of single event."""
    mock_postgres_client.fetch_one = AsyncMock(return_value=sample_semantic_event_row)
    mock_postgres_client.fetch_all = AsyncMock(return_value=sample_event_evidence_rows)

    result = await event_get(
        pg_client=mock_postgres_client,
        event_id=str(sample_event_id)
    )

    assert "event_id" in result
    assert result["category"] == "Decision"
    assert result["narrative"] == "Team decided to adopt freemium pricing model"
    assert "evidence" in result
    assert len(result["evidence"]) == 2


@pytest.mark.asyncio
async def test_event_get_with_evt_prefix(
    mock_postgres_client,
    sample_event_id,
    sample_semantic_event_row,
    sample_event_evidence_rows
):
    """Test event_get handles evt_ prefix in event_id."""
    mock_postgres_client.fetch_one = AsyncMock(return_value=sample_semantic_event_row)
    mock_postgres_client.fetch_all = AsyncMock(return_value=sample_event_evidence_rows)

    result = await event_get(
        pg_client=mock_postgres_client,
        event_id=f"evt_{sample_event_id}"
    )

    assert "event_id" in result
    assert "error" not in result


@pytest.mark.asyncio
async def test_event_get_not_found(mock_postgres_client):
    """Test event_get returns error if event not found."""
    mock_postgres_client.fetch_one = AsyncMock(return_value=None)

    result = await event_get(
        pg_client=mock_postgres_client,
        event_id="87654321-4321-8765-4321-876543218765"
    )

    assert "error" in result
    assert result["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_event_get_invalid_uuid(mock_postgres_client):
    """Test event_get returns error for invalid UUID format."""
    result = await event_get(
        pg_client=mock_postgres_client,
        event_id="invalid-uuid"
    )

    assert "error" in result
    assert result["error_code"] == "INVALID_PARAMETER"


@pytest.mark.asyncio
async def test_event_get_handles_database_error(
    mock_postgres_client,
    sample_event_id
):
    """Test event_get handles database errors gracefully."""
    mock_postgres_client.fetch_one = AsyncMock(side_effect=Exception("DB error"))

    result = await event_get(
        pg_client=mock_postgres_client,
        event_id=str(sample_event_id)
    )

    assert "error" in result
    assert result["error_code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_event_get_includes_all_fields(
    mock_postgres_client,
    sample_event_id,
    sample_semantic_event_row,
    sample_event_evidence_rows
):
    """Test that event_get includes all expected fields."""
    mock_postgres_client.fetch_one = AsyncMock(return_value=sample_semantic_event_row)
    mock_postgres_client.fetch_all = AsyncMock(return_value=sample_event_evidence_rows)

    result = await event_get(
        pg_client=mock_postgres_client,
        event_id=str(sample_event_id)
    )

    required_fields = [
        "event_id", "artifact_uid", "revision_id", "category",
        "event_time", "narrative", "subject", "actors",
        "confidence", "evidence", "extraction_run_id", "created_at"
    ]

    for field in required_fields:
        assert field in result, f"Missing field: {field}"


# ============================================================================
# Event List for Revision Tests
# ============================================================================

@pytest.mark.asyncio
async def test_event_list_for_revision_with_revision_id(
    mock_postgres_client,
    sample_semantic_event_row
):
    """Test listing events for specific revision."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={"is_latest": True})
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    result = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        revision_id="rev_test_def456",
        include_evidence=False
    )

    assert "events" in result
    assert result["artifact_uid"] == "art_test_abc123"
    assert result["revision_id"] == "rev_test_def456"
    assert result["is_latest"] is True
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_event_list_for_revision_without_revision_id(
    mock_postgres_client,
    sample_semantic_event_row
):
    """Test listing events for latest revision when not specified."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={
        "revision_id": "rev_latest",
        "is_latest": True
    })
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    result = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        include_evidence=False
    )

    assert "events" in result
    assert result["revision_id"] == "rev_latest"
    assert result["is_latest"] is True


@pytest.mark.asyncio
async def test_event_list_for_revision_artifact_not_found(mock_postgres_client):
    """Test error when artifact not found."""
    mock_postgres_client.fetch_one = AsyncMock(return_value=None)

    result = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_nonexistent",
        include_evidence=False
    )

    assert "error" in result
    assert result["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_event_list_for_revision_revision_not_found(mock_postgres_client):
    """Test error when specific revision not found."""
    mock_postgres_client.fetch_one = AsyncMock(return_value=None)

    result = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        revision_id="rev_nonexistent",
        include_evidence=False
    )

    assert "error" in result
    assert result["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_event_list_for_revision_with_evidence(
    mock_postgres_client,
    sample_semantic_event_row,
    sample_event_evidence_rows
):
    """Test listing events with evidence included."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={"is_latest": True})
    mock_postgres_client.fetch_all = AsyncMock(side_effect=[
        [sample_semantic_event_row],
        sample_event_evidence_rows
    ])

    result = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        revision_id="rev_test_def456",
        include_evidence=True
    )

    assert "events" in result
    event = result["events"][0]
    assert "evidence" in event
    assert len(event["evidence"]) == 2


@pytest.mark.asyncio
async def test_event_list_for_revision_empty_results(mock_postgres_client):
    """Test listing events returns empty list if no events."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={"is_latest": True})
    mock_postgres_client.fetch_all = AsyncMock(return_value=[])

    result = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        revision_id="rev_test_def456",
        include_evidence=False
    )

    assert "events" in result
    assert len(result["events"]) == 0
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_event_list_for_revision_handles_database_error(mock_postgres_client):
    """Test event_list_for_revision handles database errors gracefully."""
    mock_postgres_client.fetch_one = AsyncMock(side_effect=Exception("DB error"))

    result = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        include_evidence=False
    )

    assert "error" in result
    assert result["error_code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_event_list_for_revision_orders_by_time(mock_postgres_client):
    """Test that events are ordered by event_time DESC."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={"is_latest": True})
    mock_postgres_client.fetch_all = AsyncMock(return_value=[])

    await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        revision_id="rev_test_def456",
        include_evidence=False
    )

    call_args = mock_postgres_client.fetch_all.call_args_list[0]
    query = call_args[0][0]
    assert "ORDER BY event_time DESC NULLS LAST" in query


# ============================================================================
# Integration Tests (Multiple Tools)
# ============================================================================

@pytest.mark.asyncio
async def test_search_then_get_event(
    mock_postgres_client,
    sample_event_id,
    sample_semantic_event_row,
    sample_event_evidence_rows
):
    """Test workflow: search for events, then get specific event."""
    # First search
    mock_postgres_client.fetch_all = AsyncMock(side_effect=[
        [sample_semantic_event_row],
        sample_event_evidence_rows
    ])

    search_result = await event_search(
        pg_client=mock_postgres_client,
        query="pricing",
        limit=20,
        include_evidence=False
    )

    assert len(search_result["events"]) == 1
    found_event_id = search_result["events"][0]["event_id"]

    # Then get details
    mock_postgres_client.fetch_one = AsyncMock(return_value=sample_semantic_event_row)
    mock_postgres_client.fetch_all = AsyncMock(return_value=sample_event_evidence_rows)

    get_result = await event_get(
        pg_client=mock_postgres_client,
        event_id=found_event_id
    )

    assert get_result["event_id"] == found_event_id
    assert len(get_result["evidence"]) == 2


@pytest.mark.asyncio
async def test_list_for_artifact_then_search_category(
    mock_postgres_client,
    sample_semantic_event_row
):
    """Test workflow: list events for artifact, then filter by category."""
    # First list all events for artifact
    mock_postgres_client.fetch_one = AsyncMock(return_value={"is_latest": True})
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    list_result = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        include_evidence=False
    )

    assert list_result["total"] == 1

    # Then search with category filter
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    search_result = await event_search(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        category="Decision",
        limit=20,
        include_evidence=False
    )

    assert search_result["total"] == 1
    assert search_result["filters_applied"]["category"] == "Decision"


# ============================================================================
# Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_event_search_with_all_filters(mock_postgres_client, sample_semantic_event_row):
    """Test event search with all possible filters applied."""
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    result = await event_search(
        pg_client=mock_postgres_client,
        query="pricing decision",
        category="Decision",
        time_from="2024-03-01T00:00:00Z",
        time_to="2024-03-31T23:59:59Z",
        artifact_uid="art_test_abc123",
        limit=10,
        include_evidence=False
    )

    assert "events" in result
    filters = result["filters_applied"]
    assert "query" in filters
    assert "category" in filters
    assert "time_from" in filters
    assert "time_to" in filters
    assert "artifact_uid" in filters


@pytest.mark.asyncio
async def test_event_get_with_no_evidence(
    mock_postgres_client,
    sample_event_id,
    sample_semantic_event_row
):
    """Test event_get when event has no evidence (edge case)."""
    mock_postgres_client.fetch_one = AsyncMock(return_value=sample_semantic_event_row)
    mock_postgres_client.fetch_all = AsyncMock(return_value=[])

    result = await event_get(
        pg_client=mock_postgres_client,
        event_id=str(sample_event_id)
    )

    assert "evidence" in result
    assert len(result["evidence"]) == 0


@pytest.mark.asyncio
async def test_event_list_for_revision_non_latest(mock_postgres_client, sample_semantic_event_row):
    """Test listing events for a non-latest revision."""
    mock_postgres_client.fetch_one = AsyncMock(return_value={"is_latest": False})
    mock_postgres_client.fetch_all = AsyncMock(return_value=[sample_semantic_event_row])

    result = await event_list_for_revision(
        pg_client=mock_postgres_client,
        artifact_uid="art_test_abc123",
        revision_id="rev_old_456",
        include_evidence=False
    )

    assert "events" in result
    assert result["is_latest"] is False
    assert result["revision_id"] == "rev_old_456"
