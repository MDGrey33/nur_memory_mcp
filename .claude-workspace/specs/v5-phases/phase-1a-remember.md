# Phase 1a: remember() Tool

## ⚠️ IMPLEMENTATION HOLD
**NO COMMITS OR PUSHES UNTIL EXPLICITLY APPROVED BY USER**

## Objective

Add the `remember()` tool to server.py without modifying existing tools.

## Key Architectural Decision: Semantic Unification

**ALL `remember()` calls create artifact revisions and queue for event extraction. No exceptions.**

This means:
- `remember(content="User prefers dark mode", context="preference")` → creates artifact → queues event extraction
- `remember(content="Meeting notes...", context="meeting")` → creates artifact → queues event extraction
- Same pipeline for ALL content types

Simple types (preference, fact, decision, project) become single-chunk artifacts with the same extraction pipeline as documents.

## Scope

### In Scope
- New `remember()` tool function in server.py
- Internal `_store_content()` service function (shared by V4/V5 tools)
- Unit tests for remember()
- Integration tests for remember()

### Out of Scope
- Modifying existing tools
- Changing collections
- Migration scripts
- Deprecation warnings

## Implementation

### File: `server.py`

Add after line ~1330 (after existing tools, before lifecycle):

```python
# ============================================================================
# V5 TOOLS - Unified Interface
# ============================================================================

@mcp.tool()
async def remember(
    content: str,
    context: Optional[str] = None,
    source: Optional[str] = None,
    importance: float = 0.5,
    title: Optional[str] = None,
    author: Optional[str] = None,
    participants: Optional[List[str]] = None,
    date: Optional[str] = None,
    # Conversation tracking
    conversation_id: Optional[str] = None,
    turn_index: Optional[int] = None,
    role: Optional[str] = None,
    # Advanced metadata
    sensitivity: str = "normal",
    visibility_scope: str = "me",
    retention_policy: str = "forever",
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    # Source metadata
    document_date: Optional[str] = None,
    source_type: Optional[str] = None,
    document_status: Optional[str] = None,
    author_title: Optional[str] = None,
    distribution_scope: Optional[str] = None,
) -> dict:
    """
    Store content for long-term recall.

    Everything stored is automatically:
    - Chunked if large (>900 tokens, per Decision 3)
    - Embedded for semantic search
    - Analyzed for events (decisions, commitments, etc.)
    - Added to the knowledge graph

    Args:
        content: What to remember (text, up to 10MB)
        context: Type (meeting, email, preference, fact, conversation, etc.)
        source: Origin (gmail, slack, manual, user)
        importance: Priority 0.0-1.0 (default 0.5)
        ...

    Returns:
        {id, context, events_queued, status}
    """
```

### Implementation Logic

**Key Change: Unified Pipeline (Decision 1)**

ALL content types go through the same artifact ingestion pipeline. No special handling for preference/fact/decision/project that would skip event extraction.

```python
async def remember(...) -> dict:
    # 1. Validate inputs
    VALID_CONTEXTS = [
        "meeting", "email", "document", "chat", "transcript", "note",
        "preference", "fact", "decision", "project", "conversation"
    ]

    if context and context not in VALID_CONTEXTS:
        return {"error": f"Invalid context: {context}"}

    if not content or len(content) > 10_000_000:
        return {"error": "Content must be between 1 and 10,000,000 characters"}

    # 2. Handle conversation context (special case - turn-based storage)
    if context == "conversation":
        if not conversation_id or turn_index is None:
            return {"error": "conversation_id and turn_index required for context='conversation'"}
        # Store as artifact for consistency, but with conversation metadata
        result = await _store_content(
            content=content,
            context="conversation",
            source=source or "user",
            metadata={
                "conversation_id": conversation_id,
                "turn_index": turn_index,
                "role": role or "user"
            }
        )
        return {
            "id": result.get("artifact_id"),
            "context": "conversation",
            "conversation_id": conversation_id,
            "turn_index": turn_index,
            "events_queued": result.get("job_id") is not None,
            "status": "stored"
        }

    # 3. ALL other contexts use unified artifact pipeline
    # This includes preference, fact, decision, project, meeting, email, etc.
    # They ALL get event extraction - no exceptions (Decision 1: Semantic Unification)

    context_to_artifact_type = {
        "meeting": "doc",
        "email": "email",
        "document": "doc",
        "chat": "chat",
        "transcript": "transcript",
        "note": "note",
        "preference": "note",    # Simple types become note artifacts
        "fact": "note",          # with context in metadata
        "decision": "note",
        "project": "note",
        None: "doc"
    }

    result = await _store_content(
        content=content,
        context=context or "document",
        artifact_type=context_to_artifact_type.get(context, "doc"),
        source=source or "manual",
        importance=importance,
        title=title,
        author=author,
        participants=participants,
        date=date,
        sensitivity=sensitivity,
        visibility_scope=visibility_scope,
        retention_policy=retention_policy,
        source_id=source_id,
        source_url=source_url,
        document_date=document_date,
        source_type=source_type,
        document_status=document_status,
        author_title=author_title,
        distribution_scope=distribution_scope
    )

    if "error" in result:
        return result

    return {
        "id": result.get("artifact_id"),
        "artifact_uid": result.get("artifact_uid"),
        "context": context or "document",
        "is_chunked": result.get("is_chunked", False),
        "events_queued": result.get("job_id") is not None,  # ALWAYS True for content
        "status": "stored"
    }


async def _store_content(
    content: str,
    context: str,
    artifact_type: str = "doc",
    source: str = "manual",
    importance: float = 0.5,
    **kwargs
) -> dict:
    """
    Internal service function for storing content.

    Used by both remember() and artifact_ingest() to ensure
    consistent behavior (Decision 8: Internal Service Layer).

    ALL content goes through:
    1. Chunking (if > 900 tokens)
    2. Embedding generation
    3. ChromaDB storage
    4. PostgreSQL revision record
    5. Event extraction job queue
    6. Graph update (via worker)
    """
    # Implementation uses existing artifact_ingest internals
    # but ensures all content types trigger event extraction
    ...
```

## Test Cases

### File: `tests/integration/test_remember.py`

```python
"""Integration tests for remember() tool."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_remember_services():
    """Mock services for remember testing."""
    with patch("server.embedding_service") as mock_embed, \
         patch("server.chunking_service") as mock_chunk, \
         patch("server.chroma_manager") as mock_chroma, \
         patch("server.config") as mock_config, \
         patch("server.pg_client") as mock_pg, \
         patch("server.job_queue_service") as mock_job:

        mock_embed.generate_embedding.return_value = [0.1] * 3072
        mock_embed.generate_embeddings_batch.return_value = [[0.1] * 3072]
        mock_chunk.should_chunk.return_value = (False, 100)
        mock_chunk.count_tokens.return_value = 100

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.add.return_value = None
        mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.get_client.return_value = mock_client

        mock_config.openai_embed_model = "text-embedding-3-large"
        mock_config.openai_embed_dims = 3072

        mock_job.enqueue_job = AsyncMock(return_value="job-123")

        yield {
            "embed": mock_embed,
            "chunk": mock_chunk,
            "chroma": mock_chroma,
            "collection": mock_collection,
            "pg": mock_pg,
            "job": mock_job
        }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remember_document(mock_remember_services):
    """Test remembering a document."""
    from server import remember

    result = await remember(
        content="Meeting notes from Q4 planning session.",
        context="meeting",
        source="slack",
        title="Q4 Planning"
    )

    assert "error" not in result
    assert result["context"] == "meeting"
    assert "id" in result
    assert result["status"] == "stored"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remember_preference(mock_remember_services):
    """Test remembering a preference - goes through full pipeline."""
    from server import remember

    # Preferences now use the same artifact pipeline (Decision 1)
    result = await remember(
        content="User prefers dark mode",
        context="preference"
    )

    assert "error" not in result
    assert result["context"] == "preference"
    assert "art_" in result["id"]  # Now an artifact, not mem_
    assert result["events_queued"] == True  # Events ALWAYS queued


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remember_conversation(mock_remember_services):
    """Test remembering conversation turn - uses artifact pipeline."""
    from server import remember

    # Conversations now use artifact pipeline too (Decision 1)
    result = await remember(
        content="Hello, how can I help?",
        context="conversation",
        conversation_id="conv_123",
        turn_index=0,
        role="assistant"
    )

    assert "error" not in result
    assert result["context"] == "conversation"
    assert result["conversation_id"] == "conv_123"
    assert result["turn_index"] == 0
    assert "art_" in result["id"]  # Now an artifact
    assert result["events_queued"] == True  # Events queued


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remember_conversation_missing_params(mock_remember_services):
    """Test conversation requires conversation_id and turn_index."""
    from server import remember

    result = await remember(
        content="Hello",
        context="conversation"
        # Missing conversation_id and turn_index
    )

    assert "error" in result
    assert "conversation_id" in result["error"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remember_invalid_context(mock_remember_services):
    """Test invalid context is rejected."""
    from server import remember

    result = await remember(
        content="Test content",
        context="invalid_context"
    )

    assert "error" in result
    assert "Invalid context" in result["error"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remember_empty_content(mock_remember_services):
    """Test empty content is rejected."""
    from server import remember

    result = await remember(content="")

    assert "error" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remember_with_metadata(mock_remember_services):
    """Test remembering with full metadata."""
    from server import remember

    result = await remember(
        content="Important email about project deadline.",
        context="email",
        source="gmail",
        importance=0.9,
        title="Project Deadline",
        author="alice@example.com",
        participants=["bob@example.com"],
        date="2025-01-01T10:00:00Z",
        sensitivity="sensitive",
        visibility_scope="team"
    )

    assert "error" not in result
    assert result["status"] == "stored"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remember_triggers_events(mock_remember_services):
    """Test that remember queues event extraction."""
    from server import remember

    mock_remember_services["chunk"].should_chunk.return_value = (False, 500)

    result = await remember(
        content="We decided to launch the product in March.",
        context="meeting"
    )

    assert "error" not in result
    assert result["events_queued"] == True
```

## Success Criteria

- [ ] `remember()` function added to server.py
- [ ] All 8 test cases pass
- [ ] Existing tools still work (run existing test suite)
- [ ] No changes to collections.py
- [ ] Code review passes

## Estimated Effort

- Implementation: ~100 lines
- Tests: ~150 lines
- Duration: 1 session

## Checklist

- [ ] Implementation complete
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Existing tests still pass
- [ ] Code reviewed
- [ ] User approved
- [ ] Committed (after approval)
