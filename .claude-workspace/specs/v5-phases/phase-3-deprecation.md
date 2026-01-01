# Phase 3: Deprecation Warnings

## ⚠️ SKIPPED - CLEAN SLATE

**This phase has been removed. V5 is a clean-slate implementation.**

There are no legacy tools to deprecate. Legacy tools don't exist in clean slate.

For V5 implementation, see:
- Phase 1: `.claude-workspace/specs/v5-phases/phase-1-implementation.md`
- Phase 2: `.claude-workspace/specs/v5-phases/phase-2-cleanup.md`

---

## Original Content (ARCHIVED - Do Not Implement)

## Key Architectural Decision: Shared Service Layer (No Sync Wrapper Hacks)

**Old tools call shared internal service functions - NOT `run_until_complete()` wrappers.**

Per Decision 2: Calling async tools from sync wrappers via `asyncio.get_event_loop().run_until_complete()` breaks in environments with an already-running loop.

Instead:
- Create shared internal service functions (`_store_content()`, `_search_content()`, `_delete_content()`)
- Both old sync tools AND new async tools call these shared functions
- Old tools remain sync but call sync versions of internal functions
- No event-loop tricks required

## Prerequisites

- Phase 1a-1d complete (all V5 tools exist)
- Phase 2a-2b complete (migration done, new collections in use)

## Scope

### In Scope
- Add deprecation warnings to 13 old tools
- Old tools call shared internal service functions (NOT new tools directly)
- Update README.md with V5 interface
- Update version to "5.0.0-beta"

### Out of Scope
- Removing old tools (that's Phase 4)
- Removing old collections

## Implementation

### File: `server.py`

Update version:

```python
__version__ = "5.0.0-beta"
```

Add deprecation helper:

```python
import warnings

def deprecated_tool(old_name: str, new_name: str, new_params: str):
    """Log deprecation warning for old tool."""
    warnings.warn(
        f"{old_name}() is deprecated. Use {new_name}({new_params}) instead. "
        f"Will be removed in v5.1.0.",
        DeprecationWarning,
        stacklevel=3
    )
    logger.warning(f"DEPRECATED: {old_name}() called. Use {new_name}() instead.")
```

First, add shared internal service functions (sync versions):

```python
# =============================================================================
# INTERNAL SERVICE FUNCTIONS (Decision 2: Shared Service Layer)
# =============================================================================
# These sync functions are called by BOTH old sync tools and new async tools.
# No run_until_complete() hacks needed - old tools stay sync, new tools stay async.

def _store_content_sync(
    content: str,
    context: str,
    source: str = "manual",
    importance: float = 0.5,
    **kwargs
) -> dict:
    """
    Sync version of content storage for deprecated tools.

    Calls the same underlying ChromaDB/PostgreSQL operations
    as the async version, but using sync clients.
    """
    # Use sync ChromaDB client operations
    client = chroma_manager.get_client()
    collection = get_content_collection(client)

    # Generate embedding (OpenAI client has sync method)
    embedding = embedding_service.generate_embedding(content)

    # Build metadata
    metadata = {
        "context": context,
        "source_system": source,
        "importance": importance,
        **kwargs
    }

    # Generate artifact ID
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:8]
    artifact_id = f"art_{content_hash}"

    # Store in ChromaDB (sync operation)
    collection.add(
        ids=[artifact_id],
        documents=[content],
        metadatas=[metadata],
        embeddings=[embedding]
    )

    # Queue event extraction job (uses sync pg client)
    job_id = job_queue_service.enqueue_job_sync(artifact_id)

    return {
        "id": artifact_id,
        "context": context,
        "events_queued": job_id is not None,
        "status": "stored"
    }


def _search_content_sync(query: str, limit: int = 10, **kwargs) -> dict:
    """Sync version of content search for deprecated tools."""
    # Use sync retrieval operations
    ...


def _delete_content_sync(id: str) -> dict:
    """Sync version of content deletion for deprecated tools."""
    # Use sync deletion operations
    ...
```

Then update old tools to call shared functions (NO run_until_complete):

```python
@mcp.tool()
def memory_store(
    content: str,
    type: str,
    confidence: float = 0.5,
    conversation_id: Optional[str] = None
) -> str:
    """
    [DEPRECATED] Store a memory. Use remember() instead.
    """
    deprecated_tool("memory_store", "remember", f"context='{type}'")

    # Call shared sync service function (NOT async tool)
    result = _store_content_sync(
        content=content,
        context=type,  # preference, fact, decision, project
        importance=confidence,
        conversation_id=conversation_id
    )

    if "error" in result:
        return f"Error: {result['error']}"

    return f"Stored memory [{result['id']}]: {content[:50]}..."


@mcp.tool()
def memory_search(
    query: str,
    limit: int = 5,
    min_confidence: float = 0.0
) -> str:
    """
    [DEPRECATED] Search memories. Use recall() instead.
    """
    deprecated_tool("memory_search", "recall", "query=..., min_importance=...")

    # Call shared sync service function (NOT async tool)
    result = _search_content_sync(
        query=query,
        limit=limit,
        min_importance=min_confidence
    )

    if "error" in result:
        return f"Error: {result['error']}"

    return format_memory_results(result["results"])


@mcp.tool()
def memory_list(
    type: Optional[str] = None,
    limit: int = 20
) -> str:
    """
    [DEPRECATED] List memories. Use recall() instead.
    """
    deprecated_tool("memory_list", "recall", "context='{type}'")

    # Call shared sync service function
    result = _search_content_sync(
        context=type,
        limit=limit
    )

    if "error" in result:
        return f"Error: {result['error']}"

    return format_memory_list(result["results"])


@mcp.tool()
def memory_delete(memory_id: str) -> str:
    """
    [DEPRECATED] Delete a memory. Use forget() instead.
    """
    deprecated_tool("memory_delete", "forget", "id=..., confirm=True")

    # Call shared sync service function
    result = _delete_content_sync(id=memory_id)

    if not result.get("deleted"):
        return f"Error: {result.get('error', 'Delete failed')}"

    return f"Deleted memory {memory_id}"


@mcp.tool()
def history_append(
    conversation_id: str,
    role: str,
    content: str,
    turn_index: int
) -> str:
    """
    [DEPRECATED] Append to history. Use remember() instead.
    """
    deprecated_tool("history_append", "remember", "context='conversation'")

    # Call shared sync service function
    result = _store_content_sync(
        content=content,
        context="conversation",
        conversation_id=conversation_id,
        turn_index=turn_index,
        role=role
    )

    if "error" in result:
        return f"Error: {result['error']}"

    return f"Appended turn {turn_index} to {conversation_id}"


@mcp.tool()
def history_get(
    conversation_id: str,
    limit: int = 16
) -> str:
    """
    [DEPRECATED] Get conversation history. Use recall() instead.
    """
    deprecated_tool("history_get", "recall", "conversation_id=...")

    # Call shared sync service function
    result = _search_content_sync(
        conversation_id=conversation_id,
        limit=limit
    )

    if "error" in result:
        return f"Error: {result['error']}"

    return format_history(result.get("turns", []))


@mcp.tool()
async def artifact_ingest(...) -> dict:
    """
    [DEPRECATED] Ingest an artifact. Use remember() instead.
    """
    deprecated_tool("artifact_ingest", "remember", "context='document|email|meeting'")

    # Map artifact_type to context
    context_map = {
        "email": "email",
        "doc": "document",
        "chat": "chat",
        "transcript": "transcript",
        "note": "note"
    }

    result = await remember(
        content=content,
        context=context_map.get(artifact_type, "document"),
        source=source_system,
        title=title,
        author=author,
        participants=participants,
        date=ts,
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

    # Add backward-compatible fields
    if "error" not in result:
        result["artifact_id"] = result["id"]
        result["is_chunked"] = result.get("is_chunked", False)
        result["num_chunks"] = result.get("num_chunks", 0)

    return result


# Similar wrappers for:
# - artifact_search -> recall(query=...)
# - artifact_get -> recall(id=...)
# - artifact_delete -> forget(id=..., confirm=True)
# - hybrid_search -> recall(query=..., expand=True)
# - event_search_tool -> recall(query=..., include_events=True)
# - event_get_tool -> recall(id="evt_...")
# - embedding_health -> status()
# - job_status -> status(artifact_id=...)
```

### File: `README.md`

Add V5 interface section:

```markdown
## V5 Interface (New)

V5 simplifies the API from 17 tools to 4:

### remember() - Store anything

```python
remember(
    content="Meeting notes from Q4 planning",
    context="meeting",      # meeting, email, preference, fact, etc.
    source="slack",
    importance=0.8
)
```

### recall() - Find anything

```python
recall(query="Q4 planning decisions")
recall(id="art_123")
recall(context="meeting", limit=5)
recall(conversation_id="conv_123")
```

### forget() - Delete anything

```python
forget(id="art_123", confirm=True)
```

### status() - System health

```python
status()
```

### Migration Guide

| Old Tool | New Tool |
|----------|----------|
| `memory_store` | `remember(context="fact")` |
| `artifact_ingest` | `remember(context="document")` |
| `history_append` | `remember(context="conversation")` |
| `memory_search` | `recall(query=...)` |
| `hybrid_search` | `recall(query=..., expand=True)` |
| `artifact_get` | `recall(id=...)` |
| `memory_delete` | `forget(id=..., confirm=True)` |
| `artifact_delete` | `forget(id=..., confirm=True)` |
```

## Test Cases

### File: `tests/unit/test_deprecation.py`

```python
"""Tests for deprecation warnings."""

import pytest
import warnings


def test_memory_store_warns():
    """Test memory_store emits deprecation warning."""
    from server import memory_store

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        # Call with mock would be needed
        # memory_store("test", "fact")

        # Should capture deprecation warning
        # assert len(w) == 1
        # assert "deprecated" in str(w[0].message).lower()


def test_deprecated_tools_still_work():
    """Test deprecated tools still function correctly."""
    # Verify backward compatibility
    pass


def test_deprecated_tools_call_new_tools():
    """Test deprecated tools delegate to new tools."""
    # Verify delegation
    pass
```

## Success Criteria

- [ ] All 13 old tools emit deprecation warnings
- [ ] Old tools call new tools internally
- [ ] Backward compatibility maintained
- [ ] README updated with V5 interface
- [ ] Version updated to "5.0.0-beta"
- [ ] All tests pass

## Estimated Effort

- Implementation: ~200 lines (wrappers)
- Documentation: ~100 lines
- Tests: ~50 lines
- Duration: 1 session

## Checklist

- [ ] Deprecation warnings added
- [ ] Old tools delegate to new tools
- [ ] Backward compatibility tested
- [ ] README updated
- [ ] Version updated
- [ ] All tests pass
- [ ] Code reviewed
- [ ] User approved
- [ ] Committed (after approval)
