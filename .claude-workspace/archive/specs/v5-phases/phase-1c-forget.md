# Phase 1c: forget() Tool

## ⚠️ IMPLEMENTATION HOLD
**NO COMMITS OR PUSHES UNTIL EXPLICITLY APPROVED BY USER**

## Objective

Add the `forget()` tool to server.py without modifying existing tools.

## Key Architectural Decision: Guide-to-Source for Events

**`forget(evt_xxx)` returns an error with guidance to delete the source artifact instead.**

Events are derived data with evidence links to source text. Deleting events directly would:
- Orphan the source content
- Leave inconsistent state
- Skip proper cascade cleanup

Instead, the error includes the source artifact ID so users can delete correctly:

```json
{
  "deleted": false,
  "id": "evt_abc123",
  "error": "Events are derived data. Delete source artifact 'art_xyz789' instead.",
  "source_artifact_id": "art_xyz789"
}
```

## Prerequisites

- Phase 1a complete (remember() tool)
- Phase 1b complete (recall() tool)

## Scope

### In Scope
- New `forget()` tool function in server.py
- Internal `_delete_content()` service function (shared by V4/V5 tools)
- Guide-to-source error for event deletion
- Unit tests for forget()
- Integration tests for forget()

### Out of Scope
- Modifying existing delete tools
- Changing collections
- Migration scripts

## Implementation

### File: `server.py`

Add after `recall()` function:

```python
@mcp.tool()
async def forget(
    id: str,
    confirm: bool = False,
) -> dict:
    """
    Delete stored content.

    Removes content and all associated data (chunks, events, graph nodes).
    Requires confirm=True as a safety measure.

    Args:
        id: Content ID to delete (art_xxx, mem_xxx, or evt_xxx)
        confirm: Must be True to execute (safety)

    Returns:
        {deleted: bool, id: str, cascade: {chunks, events, entities}}
    """
    # 1. Safety check
    if not confirm:
        return {
            "deleted": False,
            "id": id,
            "error": "Must set confirm=True to delete content"
        }

    # 2. Validate ID format
    if not id:
        return {"deleted": False, "error": "ID is required"}

    cascade = {"chunks": 0, "events": 0, "entities": 0}

    # 3. Route by ID prefix
    if id.startswith("mem_"):
        # Delete memory
        result = memory_delete(id)
        if "Error" in result:
            return {"deleted": False, "id": id, "error": result}
        return {"deleted": True, "id": id, "cascade": cascade}

    elif id.startswith("evt_"):
        # Events are derived data - guide user to source (Decision 4)
        # Look up the source artifact ID
        event_id = id.replace("evt_", "")
        source_artifact_id = await _get_event_source_artifact(event_id)

        return {
            "deleted": False,
            "id": id,
            "error": f"Events are derived data. Delete source artifact '{source_artifact_id}' instead.",
            "source_artifact_id": source_artifact_id
        }


async def _get_event_source_artifact(event_id: str) -> str:
    """
    Look up the source artifact for an event.

    Args:
        event_id: Event UUID (without evt_ prefix)

    Returns:
        Source artifact ID (art_xxx format)
    """
    async with pg_client.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT ar.artifact_id
            FROM semantic_events se
            JOIN artifact_revision ar ON se.revision_id = ar.revision_id
            WHERE se.id = $1
        """, event_id)

        if row:
            return f"art_{row['artifact_id'][:8]}"
        return "art_unknown"

    else:
        # Delete artifact (art_ or uid_)
        result = await artifact_delete(id)
        if "error" in result:
            return {"deleted": False, "id": id, "error": result["error"]}

        # Extract cascade counts from result
        cascade["chunks"] = result.get("chunks_deleted", 0)
        cascade["events"] = result.get("events_deleted", 0)
        cascade["entities"] = result.get("entities_orphaned", 0)

        return {
            "deleted": True,
            "id": id,
            "cascade": cascade
        }
```

## Test Cases

### File: `tests/integration/test_forget.py`

```python
"""Integration tests for forget() tool."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_forget_services():
    """Mock services for forget testing."""
    with patch("server.chroma_manager") as mock_chroma, \
         patch("server.pg_client") as mock_pg:

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.get_client.return_value = mock_client

        yield {
            "chroma": mock_chroma,
            "collection": mock_collection,
            "pg": mock_pg
        }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_forget_artifact(mock_forget_services):
    """Test deleting an artifact."""
    from server import forget

    with patch("server.artifact_delete") as mock_delete:
        mock_delete.return_value = {
            "status": "deleted",
            "chunks_deleted": 3,
            "events_deleted": 2
        }

        result = await forget(id="art_123", confirm=True)

    assert result["deleted"] == True
    assert result["id"] == "art_123"
    assert result["cascade"]["chunks"] == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_forget_memory(mock_forget_services):
    """Test deleting a memory."""
    from server import forget

    with patch("server.memory_delete") as mock_delete:
        mock_delete.return_value = "Deleted memory mem_123"

        result = await forget(id="mem_123", confirm=True)

    assert result["deleted"] == True
    assert result["id"] == "mem_123"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_forget_requires_confirm(mock_forget_services):
    """Test that confirm=True is required."""
    from server import forget

    result = await forget(id="art_123", confirm=False)

    assert result["deleted"] == False
    assert "confirm=True" in result["error"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_forget_event_guides_to_source(mock_forget_services):
    """Test that events guide user to delete source artifact (Decision 4)."""
    from server import forget

    with patch("server._get_event_source_artifact") as mock_lookup:
        mock_lookup.return_value = "art_xyz789"

        result = await forget(id="evt_123", confirm=True)

    assert result["deleted"] == False
    assert "Events are derived data" in result["error"]
    assert "art_xyz789" in result["error"]
    assert result["source_artifact_id"] == "art_xyz789"
```

## Success Criteria

- [ ] `forget()` function added to server.py
- [ ] All 4 test cases pass
- [ ] Existing tools still work
- [ ] Safety flag works correctly
- [ ] Code review passes

## Estimated Effort

- Implementation: ~50 lines
- Tests: ~80 lines
- Duration: 1 session

## Checklist

- [ ] Implementation complete
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Existing tests still pass
- [ ] Code reviewed
- [ ] User approved
- [ ] Committed (after approval)
