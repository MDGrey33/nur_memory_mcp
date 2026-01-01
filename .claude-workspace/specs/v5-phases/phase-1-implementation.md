# Phase 1: Implementation

## ⚠️ IMPLEMENTATION HOLD
**NO COMMITS OR PUSHES UNTIL EXPLICITLY APPROVED BY USER**

## Objective

Build the complete V5 system from scratch: 4 tools, internal services, and V5 collections.

## Prerequisites

- None (clean slate)

## Scope

### In Scope
- `get_content_collection()` and `get_chunks_collection()` functions
- Internal services: `_store_content()`, `_search_content()`, `_delete_content()`
- `remember()` tool with chunking, embedding, event extraction
- `recall()` tool with hybrid search, graph expansion
- `forget()` tool with cascade deletion
- `status()` tool with V5 counts
- Conversation turn event gating
- Unit tests
- Integration tests

### Out of Scope
- Legacy code (doesn't exist in clean slate)
- Migration scripts (clean slate)
- E2E tests (Phase 2)

## Implementation

### 1. Collections (collections.py)

```python
def get_content_collection(client: HttpClient) -> Collection:
    """
    Get or create the unified content collection (V5).

    Args:
        client: ChromaDB client

    Returns:
        Content collection instance
    """
    return client.get_or_create_collection(
        name="content",
        embedding_function=None,
        metadata={
            "description": "Unified content storage (V5)",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072
        }
    )


def get_chunks_collection(client: HttpClient) -> Collection:
    """
    Get or create the chunks collection (V5).

    Args:
        client: ChromaDB client

    Returns:
        Chunks collection instance
    """
    return client.get_or_create_collection(
        name="chunks",
        embedding_function=None,
        metadata={
            "description": "Content chunks (V5)",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072
        }
    )
```

### 2. Internal Services (server.py)

```python
# =============================================================================
# INTERNAL SERVICES (V5)
# =============================================================================

async def _store_content(
    content: str,
    context: str,
    source: str = "manual",
    importance: float = 0.5,
    **kwargs
) -> dict:
    """
    Internal service to store content.

    Used by remember() tool.
    """
    client = chroma_manager.get_client()
    content_col = get_content_collection(client)

    # Generate ID
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
    artifact_id = f"art_{content_hash}"

    # Generate embedding
    embedding = embedding_service.generate_embedding(content)

    # Build metadata
    metadata = {
        "context": context,
        "source_system": source,
        "importance": importance,
        "ingested_at": datetime.utcnow().isoformat(),
        **kwargs
    }

    # Check if chunking needed (>= 900 tokens)
    token_count = chunking_service.count_tokens(content)
    is_chunked = token_count >= 900

    if is_chunked:
        # Chunk the content
        chunks = chunking_service.chunk_text(content, max_tokens=900, overlap=100)

        # Store each chunk
        chunks_col = get_chunks_collection(client)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{artifact_id}::chunk::{i:03d}"
            chunk_embedding = embedding_service.generate_embedding(chunk)
            chunks_col.add(
                ids=[chunk_id],
                documents=[chunk],
                metadatas=[{
                    "content_id": artifact_id,
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                }],
                embeddings=[chunk_embedding]
            )

    # Store main content
    content_col.add(
        ids=[artifact_id],
        documents=[content],
        metadatas=[{**metadata, "is_chunked": is_chunked}],
        embeddings=[embedding]
    )

    # Queue event extraction (Decision 1: Semantic Unification)
    # Exception: Short conversation turns skip extraction
    should_extract = True
    if context == "conversation" and token_count < 100:
        should_extract = False

    job_id = None
    if should_extract:
        job_id = await job_queue_service.enqueue_extraction(artifact_id)

    return {
        "id": artifact_id,
        "context": context,
        "is_chunked": is_chunked,
        "num_chunks": len(chunks) if is_chunked else 0,
        "events_queued": job_id is not None,
        "status": "stored"
    }


async def _search_content(
    query: str = None,
    id: str = None,
    context: str = None,
    limit: int = 10,
    expand: bool = True,
    conversation_id: str = None,
    **kwargs
) -> dict:
    """
    Internal service to search content.

    Used by recall() tool.
    """
    client = chroma_manager.get_client()

    # Direct ID lookup
    if id:
        if id.startswith("evt_"):
            # Event lookup
            return await _get_event(id)
        else:
            # Content lookup (art_ only)
            if not id.startswith("art_"):
                return {"error": f"Invalid ID format. Use art_xxx. Got: {id}"}

            content_col = get_content_collection(client)
            result = content_col.get(ids=[id], include=["documents", "metadatas"])

            if not result["ids"]:
                return {"results": [], "error": f"Content not found: {id}"}

            return {
                "results": [{
                    "id": result["ids"][0],
                    "content": result["documents"][0],
                    "metadata": result["metadatas"][0]
                }],
                "related": [],
                "entities": [],
                "total_count": 1
            }

    # Conversation history retrieval (Decision 5: Structured Conversation History)
    if conversation_id:
        content_col = get_content_collection(client)
        result = content_col.get(
            where={
                "$and": [
                    {"context": "conversation"},
                    {"conversation_id": conversation_id},
                ]
            },
            include=["documents", "metadatas"],
        )

        turns = []
        for doc, meta in zip(result.get("documents", []), result.get("metadatas", [])):
            turns.append(
                {
                    "role": meta.get("role", "user"),
                    "turn_index": meta.get("turn_index", 0),
                    "ts": meta.get("ts", meta.get("ingested_at")),
                    "content": doc,
                }
            )

        turns.sort(key=lambda t: t["turn_index"])
        if limit:
            turns = turns[:limit]

        return {
            "turns": turns,
            "total_turns": len(turns),
            "conversation_id": conversation_id,
            # Keep standard keys present for client uniformity
            "results": [],
            "related": [],
            "entities": [],
        }

    # Semantic search
    if query:
        # Use internal hybrid search with graph expansion (V5 keeps the V4 retrieval pipeline under the hood).
        return await hybrid_search(
            query=query,
            limit=limit,
            graph_expand=expand,
            **kwargs
        )

    return {"error": "Must provide query or id"}


async def _delete_content(id: str, confirm: bool = False) -> dict:
    """
    Internal service to delete content.

    Used by forget() tool.
    """
    if not confirm:
        return {"error": "Must set confirm=True to delete"}

    # Validate ID format (Decision 6: Single ID Family)
    if id.startswith("evt_"):
        # Get source artifact for guidance
        source_id = await _get_event_source_artifact(id)
        return {
            "error": f"Events are derived data. Delete source artifact '{source_id}' instead.",
            "source_artifact_id": source_id
        }

    if not id.startswith("art_"):
        return {"error": f"Invalid ID format. Use art_xxx. Got: {id}"}

    client = chroma_manager.get_client()
    deleted_count = 0

    # Delete from content collection
    content_col = get_content_collection(client)
    try:
        content_col.delete(ids=[id])
        deleted_count += 1
    except Exception as e:
        logger.error(f"Failed to delete content {id}: {e}")

    # Delete chunks
    chunks_col = get_chunks_collection(client)
    try:
        # Find chunks by content_id
        results = chunks_col.get(where={"content_id": id})
        chunk_ids = results.get("ids", [])
        if chunk_ids:
            chunks_col.delete(ids=chunk_ids)
            deleted_count += len(chunk_ids)
    except Exception as e:
        logger.error(f"Failed to delete chunks for {id}: {e}")

    # Delete events from PostgreSQL
    events_deleted = await _delete_events_for_artifact(id)

    # Delete from graph
    entities_deleted = await _delete_graph_nodes_for_artifact(id)

    return {
        "deleted": True,
        "id": id,
        "cascade": {
            "chunks": len(chunk_ids) if chunk_ids else 0,
            "events": events_deleted,
            "entities": entities_deleted
        }
    }
```

### 3. Tools (server.py)

See main spec Section 3 for full tool signatures.

Key implementation notes:

**remember():**
- Calls `_store_content()` internally
- Validates `context` against VALID_CONTEXTS
- For `context="conversation"`, requires `conversation_id` and `turn_index`

**recall():**
- Calls `_search_content()` internally
- For `conversation_id`, returns structured `{turns: [...]}` format (Decision 5)
- For `id`, validates prefix is `art_` or `evt_`

**forget():**
- Calls `_delete_content()` internally
- Only accepts `art_` IDs (Decision 6)
- Returns guidance for `evt_` IDs (Decision 4)

**status():**
- Reports V5 collections (content, chunks)
- Reports Postgres table counts
- Reports Postgres entity/event counts; graph expansion uses Postgres joins

### 4. Conversation Turn Event Gating

Per Decision 1, conversation turns < 100 tokens skip event extraction:

```python
# In _store_content():
should_extract = True
if context == "conversation" and token_count < 100:
    should_extract = False
    logger.info(f"Skipping event extraction for short conversation turn ({token_count} tokens)")
```

## Test Cases

### Unit Tests

**test_collections.py:**
```python
def test_get_content_collection(mock_chroma_client):
    """Test get_content_collection returns correct collection."""
    collection = get_content_collection(mock_chroma_client)
    assert collection is not None
    call_args = mock_chroma_client.get_or_create_collection.call_args
    assert call_args[1]["name"] == "content"

def test_get_chunks_collection(mock_chroma_client):
    """Test get_chunks_collection returns correct collection."""
    collection = get_chunks_collection(mock_chroma_client)
    assert collection is not None
    call_args = mock_chroma_client.get_or_create_collection.call_args
    assert call_args[1]["name"] == "chunks"
```

### Integration Tests

**test_remember.py:**
```python
@pytest.mark.asyncio
async def test_remember_document(mock_services):
    """Test remembering a document stores correctly."""

@pytest.mark.asyncio
async def test_remember_returns_art_id(mock_services):
    """Test remember returns art_ prefixed ID."""

@pytest.mark.asyncio
async def test_remember_triggers_events(mock_services):
    """Test remember queues event extraction."""

@pytest.mark.asyncio
async def test_remember_conversation_short_skips_events(mock_services):
    """Test short conversation turns skip event extraction."""
```

**test_recall.py:**
```python
@pytest.mark.asyncio
async def test_recall_by_query(mock_services):
    """Test semantic search."""

@pytest.mark.asyncio
async def test_recall_by_art_id(mock_services):
    """Test direct lookup with art_ ID."""

@pytest.mark.asyncio
async def test_recall_rejects_invalid_id(mock_services):
    """Test recall rejects mem_, hist_, etc."""

@pytest.mark.asyncio
async def test_recall_conversation_structured(mock_services):
    """Test conversation retrieval returns {turns: [...]}."""
```

**test_forget.py:**
```python
@pytest.mark.asyncio
async def test_forget_requires_confirm(mock_services):
    """Test forget requires confirm=True."""

@pytest.mark.asyncio
async def test_forget_art_id(mock_services):
    """Test forget works with art_ ID."""

@pytest.mark.asyncio
async def test_forget_evt_returns_guidance(mock_services):
    """Test evt_ ID returns guidance error."""

@pytest.mark.asyncio
async def test_forget_invalid_id_error(mock_services):
    """Test invalid ID prefix returns error."""
```

**test_status.py:**
```python
@pytest.mark.asyncio
async def test_status_returns_v5_structure(mock_services):
    """Test status returns V5 counts."""

@pytest.mark.asyncio
async def test_status_reports_content_collection(mock_services):
    """Test status includes content collection."""
```

## Success Criteria

- [ ] `get_content_collection()` works
- [ ] `get_chunks_collection()` works
- [ ] `_store_content()` stores and chunks correctly
- [ ] `_search_content()` searches and validates IDs
- [ ] `_delete_content()` cascades correctly
- [ ] `remember()` tool works
- [ ] `recall()` tool works with structured conversation return
- [ ] `forget()` tool works with guidance for evt_ IDs
- [ ] `status()` reports V5 counts
- [ ] Conversation turn event gating works
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Version is "5.0.0-alpha"

## Checklist

- [ ] Collection functions added
- [ ] Internal services implemented
- [ ] remember() tool implemented
- [ ] recall() tool implemented
- [ ] forget() tool implemented
- [ ] status() tool implemented
- [ ] Event gating for conversations
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Version updated to "5.0.0-alpha"
- [ ] Code reviewed
- [ ] User approved
- [ ] Committed (after approval)
