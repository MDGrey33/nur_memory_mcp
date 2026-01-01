# Phase 1b: recall() Tool

## ⚠️ IMPLEMENTATION HOLD
**NO COMMITS OR PUSHES UNTIL EXPLICITLY APPROVED BY USER**

## Objective

Add the `recall()` tool to server.py without modifying existing tools.

## Key Architectural Decision: Structured Conversation History

**`recall(conversation_id=...)` returns structured data, not strings to parse.**

Return format (Decision 7):
```json
{
  "turns": [
    {"role": "user", "turn_index": 0, "ts": "2025-01-01T10:00:00Z", "content": "Hello"},
    {"role": "assistant", "turn_index": 1, "ts": "2025-01-01T10:00:01Z", "content": "Hi there!"}
  ],
  "total_turns": 2,
  "conversation_id": "conv_123"
}
```

This enables reliable programmatic access without fragile string parsing.

## Prerequisites

- Phase 1a complete (remember() tool exists)

## Scope

### In Scope
- New `recall()` tool function in server.py
- Internal `_search_content()` service function (shared by V4/V5 tools)
- Structured conversation history return
- Unit tests for recall()
- Integration tests for recall()

### Out of Scope
- Modifying existing tools
- Changing collections
- Migration scripts

## Implementation

### File: `server.py`

Add after `remember()` function:

```python
@mcp.tool()
async def recall(
    query: Optional[str] = None,
    id: Optional[str] = None,
    context: Optional[str] = None,
    limit: int = 10,
    expand: bool = True,
    include_events: bool = True,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    # Conversation retrieval
    conversation_id: Optional[str] = None,
    # Advanced graph parameters
    graph_budget: int = 10,
    graph_filters: Optional[List[str]] = None,
    include_entities: bool = True,
    # Chunk context
    expand_neighbors: bool = False,
    # Filtering
    min_importance: float = 0.0,
    source: Optional[str] = None,
    sensitivity: Optional[str] = None,
) -> dict:
    """
    Find and retrieve stored content.

    Can search semantically, get by ID, or list with filters.
    By default, includes related context from the knowledge graph.

    Args:
        query: What to search for (natural language)
        id: Specific content ID to retrieve
        context: Filter by type (meeting, email, preference, etc.)
        limit: Maximum results (default 10)
        expand: Include related content via graph (default True)
        ...

    Returns:
        {results, related, entities, total_count}
    """
```

### Implementation Logic

```python
async def recall(...) -> dict:
    # Set default graph_filters if not provided
    if graph_filters is None:
        graph_filters = ["Decision", "Commitment", "QualityRisk"]

    # 1. Direct ID lookup
    if id:
        # Determine type by prefix
        if id.startswith("evt_"):
            # Event lookup
            result = await event_get_tool(id)
            return {
                "results": [result] if "error" not in result else [],
                "related": [],
                "entities": [],
                "total_count": 1 if "error" not in result else 0
            }

        else:
            # Content lookup (art_ or uid_)
            # NOTE: mem_ IDs no longer supported (no backward compatibility)
            # All content uses art_ IDs after V5 migration
            result = await artifact_get(
                artifact_id=id,
                include_content=True,
                include_chunks=expand_neighbors
            )
            if "error" in result:
                return {"results": [], "related": [], "entities": [], "total_count": 0, "error": result["error"]}

            # Get events if requested
            events = []
            if include_events:
                event_result = await event_list_for_artifact(id)
                events = event_result.get("events", [])

            return {
                "results": [{
                    "id": result.get("artifact_id"),
                    "content": result.get("content"),
                    "metadata": result.get("metadata", {}),
                    "context": result.get("metadata", {}).get("artifact_type", "document"),
                    "events": events
                }],
                "related": [],
                "entities": [],
                "total_count": 1
            }

    # 2. Conversation history retrieval (Decision 7: Structured Return)
    if conversation_id:
        # Query content collection for conversation turns
        client = chroma_manager.get_client()
        collection = get_content_collection(client)

        results = collection.get(
            where={
                "$and": [
                    {"context": "conversation"},
                    {"conversation_id": conversation_id}
                ]
            },
            include=["documents", "metadatas"]
        )

        # Build structured turn list
        turns = []
        for doc, meta in zip(results.get("documents", []), results.get("metadatas", [])):
            turns.append({
                "role": meta.get("role", "user"),
                "turn_index": meta.get("turn_index", 0),
                "ts": meta.get("ts", meta.get("ingested_at")),
                "content": doc
            })

        # Sort by turn_index
        turns.sort(key=lambda t: t["turn_index"])

        # Apply limit
        if limit:
            turns = turns[:limit]

        return {
            "turns": turns,  # Structured, not results[]
            "total_turns": len(turns),
            "conversation_id": conversation_id,
            # Standard fields for consistency
            "results": [],
            "related": [],
            "entities": []
        }

    # 3. Semantic search with optional graph expansion
    if query:
        # Validate query
        if len(query) < 2 or len(query) > 5000:
            return {"error": "Query must be between 2 and 5000 characters"}

        # Map context to collection filters
        MEMORY_CONTEXTS = ["preference", "fact", "decision", "project"]

        # Use hybrid_search for unified results
        result = await hybrid_search(
            query=query,
            limit=limit,
            include_memory=context in MEMORY_CONTEXTS if context else True,
            include_events=include_events,
            expand_neighbors=expand_neighbors,
            graph_expand=expand,
            graph_budget=graph_budget,
            graph_filters=graph_filters,
            include_entities=include_entities
        )

        if "error" in result:
            return result

        # Transform results to V5 format
        primary = result.get("primary_results", [])
        related = result.get("related_context", [])
        entities = result.get("entities", [])

        # Apply context filter if specified
        if context:
            primary = [r for r in primary if _matches_context(r, context)]

        # Apply additional filters
        if source:
            primary = [r for r in primary if r.get("metadata", {}).get("source_system") == source]
        if sensitivity:
            primary = [r for r in primary if r.get("metadata", {}).get("sensitivity") == sensitivity]
        if min_importance > 0:
            primary = [r for r in primary if r.get("metadata", {}).get("confidence", 0.5) >= min_importance]

        return {
            "results": primary[:limit],
            "related": related,
            "entities": entities,
            "total_count": len(primary)
        }

    # 4. List mode (no query, no id, no conversation_id)
    if context:
        MEMORY_CONTEXTS = ["preference", "fact", "decision", "project"]
        if context in MEMORY_CONTEXTS:
            # List memories
            result = memory_list(context, limit)
            # Parse result...
            return {"results": [], "related": [], "entities": [], "total_count": 0}

    return {"error": "Must provide query, id, conversation_id, or context filter"}


def _matches_context(result: dict, context: str) -> bool:
    """Check if result matches the requested context."""
    meta = result.get("metadata", {})
    # Memory contexts
    if context in ["preference", "fact", "decision", "project"]:
        return meta.get("type") == context
    # Artifact contexts
    artifact_type = meta.get("artifact_type", "")
    context_map = {
        "meeting": "doc",
        "email": "email",
        "document": "doc",
        "chat": "chat",
        "transcript": "transcript",
        "note": "note"
    }
    return artifact_type == context_map.get(context, context)
```

## Test Cases

### File: `tests/integration/test_recall.py`

```python
"""Integration tests for recall() tool."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_recall_services():
    """Mock services for recall testing."""
    with patch("server.embedding_service") as mock_embed, \
         patch("server.retrieval_service") as mock_retrieval, \
         patch("server.chroma_manager") as mock_chroma, \
         patch("server.graph_service") as mock_graph:

        mock_embed.generate_embedding.return_value = [0.1] * 3072

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.get_client.return_value = mock_client

        mock_retrieval.hybrid_search_v4 = AsyncMock()

        yield {
            "embed": mock_embed,
            "retrieval": mock_retrieval,
            "chroma": mock_chroma,
            "collection": mock_collection,
            "graph": mock_graph
        }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_by_query(mock_recall_services):
    """Test semantic search."""
    from server import recall

    mock_recall_services["retrieval"].hybrid_search_v4.return_value = MagicMock(
        to_dict=lambda: {
            "primary_results": [
                {"id": "art_001", "content": "Test result", "metadata": {}, "rrf_score": 0.5}
            ],
            "related_context": [],
            "entities": [],
            "expand_options": {}
        }
    )

    result = await recall(query="test query")

    assert "error" not in result
    assert len(result["results"]) == 1
    assert "total_count" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_by_artifact_id(mock_recall_services):
    """Test direct artifact lookup."""
    from server import recall

    with patch("server.artifact_get") as mock_get:
        mock_get.return_value = {
            "artifact_id": "art_123",
            "content": "Test content",
            "metadata": {"artifact_type": "doc"}
        }

        result = await recall(id="art_123")

    assert "error" not in result
    assert len(result["results"]) == 1
    assert result["results"][0]["id"] == "art_123"


# NOTE: test_recall_by_memory_id REMOVED - no backward compatibility
# mem_ IDs are not supported in V5. All content uses art_ IDs.


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_by_event_id(mock_recall_services):
    """Test direct event lookup."""
    from server import recall

    with patch("server.event_get_tool") as mock_get:
        mock_get.return_value = {
            "event_id": "evt_123",
            "category": "Decision",
            "narrative": "Team decided..."
        }

        result = await recall(id="evt_123")

    assert "error" not in result
    assert len(result["results"]) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_conversation(mock_recall_services):
    """Test conversation history retrieval - structured return (Decision 7)."""
    from server import recall

    # Mock the content collection with conversation data
    mock_recall_services["collection"].get.return_value = {
        "ids": ["art_1", "art_2"],
        "documents": ["Hello", "Hi there!"],
        "metadatas": [
            {"context": "conversation", "conversation_id": "conv_123", "turn_index": 0, "role": "user", "ts": "2025-01-01T10:00:00Z"},
            {"context": "conversation", "conversation_id": "conv_123", "turn_index": 1, "role": "assistant", "ts": "2025-01-01T10:00:01Z"}
        ]
    }

    result = await recall(conversation_id="conv_123", limit=10)

    assert "error" not in result
    assert result["conversation_id"] == "conv_123"
    assert "turns" in result  # Structured return
    assert len(result["turns"]) == 2
    assert result["turns"][0]["role"] == "user"
    assert result["turns"][0]["turn_index"] == 0
    assert result["turns"][0]["content"] == "Hello"
    assert result["turns"][1]["role"] == "assistant"
    assert result["total_turns"] == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_with_graph_expansion(mock_recall_services):
    """Test graph expansion returns related content."""
    from server import recall

    mock_recall_services["retrieval"].hybrid_search_v4.return_value = MagicMock(
        to_dict=lambda: {
            "primary_results": [
                {"id": "art_001", "content": "Primary", "metadata": {}, "rrf_score": 0.5}
            ],
            "related_context": [
                {"id": "art_002", "content": "Related via graph", "metadata": {}}
            ],
            "entities": [
                {"name": "Alice", "type": "person"}
            ],
            "expand_options": {}
        }
    )

    result = await recall(query="test", expand=True)

    assert "error" not in result
    assert len(result["related"]) == 1
    assert len(result["entities"]) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_with_context_filter(mock_recall_services):
    """Test filtering by context type."""
    from server import recall

    mock_recall_services["retrieval"].hybrid_search_v4.return_value = MagicMock(
        to_dict=lambda: {
            "primary_results": [
                {"id": "art_001", "content": "Email", "metadata": {"artifact_type": "email"}, "rrf_score": 0.5},
                {"id": "art_002", "content": "Doc", "metadata": {"artifact_type": "doc"}, "rrf_score": 0.4}
            ],
            "related_context": [],
            "entities": [],
            "expand_options": {}
        }
    )

    result = await recall(query="test", context="email")

    assert "error" not in result
    # Should filter to only email results
    assert all(r["metadata"].get("artifact_type") == "email" for r in result["results"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_with_source_filter(mock_recall_services):
    """Test filtering by source system."""
    from server import recall

    mock_recall_services["retrieval"].hybrid_search_v4.return_value = MagicMock(
        to_dict=lambda: {
            "primary_results": [
                {"id": "art_001", "content": "Gmail", "metadata": {"source_system": "gmail"}, "rrf_score": 0.5},
                {"id": "art_002", "content": "Slack", "metadata": {"source_system": "slack"}, "rrf_score": 0.4}
            ],
            "related_context": [],
            "entities": [],
            "expand_options": {}
        }
    )

    result = await recall(query="test", source="gmail")

    assert "error" not in result
    assert all(r["metadata"].get("source_system") == "gmail" for r in result["results"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_invalid_query(mock_recall_services):
    """Test query validation."""
    from server import recall

    result = await recall(query="x")  # Too short

    assert "error" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_no_params(mock_recall_services):
    """Test error when no params provided."""
    from server import recall

    result = await recall()

    assert "error" in result
```

## Success Criteria

- [ ] `recall()` function added to server.py
- [ ] All 10 test cases pass
- [ ] Existing tools still work
- [ ] Works with remember() from Phase 1a
- [ ] Code review passes

## Estimated Effort

- Implementation: ~150 lines
- Tests: ~200 lines
- Duration: 1 session

## Checklist

- [ ] Implementation complete
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Existing tests still pass
- [ ] Works with Phase 1a
- [ ] Code reviewed
- [ ] User approved
- [ ] Committed (after approval)
