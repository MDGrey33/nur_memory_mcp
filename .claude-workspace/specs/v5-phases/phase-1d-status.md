# Phase 1d: status() Tool

## ⚠️ IMPLEMENTATION HOLD
**NO COMMITS OR PUSHES UNTIL EXPLICITLY APPROVED BY USER**

## Objective

Add the `status()` tool to server.py, completing the V5 tool set.

## Prerequisites

- Phase 1a-1c complete

## Scope

### In Scope
- New `status()` tool function in server.py
- Unit tests for status()
- Update `__version__` to "5.0.0-alpha.1"

### Out of Scope
- Modifying existing tools
- Changing collections

## Implementation

### File: `server.py`

Update version at top of file:

```python
__version__ = "5.0.0-alpha.1"
```

Add after `forget()` function:

```python
@mcp.tool()
async def status(
    artifact_id: Optional[str] = None,
) -> dict:
    """
    Get system health and statistics.

    Args:
        artifact_id: Optional - check extraction job status for specific artifact

    Returns:
        {version, environment, healthy, services, counts, pending_jobs, job_status?}
    """
    # 1. Get basic health info
    health = {
        "version": __version__,
        "environment": os.getenv("ENVIRONMENT", "prod"),
        "healthy": True,
        "services": {},
        "counts": {},
        "pending_jobs": 0
    }

    # 2. Check ChromaDB
    try:
        client = chroma_manager.get_client()
        start = time.time()
        client.heartbeat()
        latency = (time.time() - start) * 1000

        # Get counts from collections
        artifacts_col = get_artifacts_collection(client)
        memory_col = get_memory_collection(client)
        chunks_col = get_artifact_chunks_collection(client)

        health["services"]["chromadb"] = {
            "status": "healthy",
            "latency_ms": round(latency, 2)
        }
        health["counts"]["artifacts"] = artifacts_col.count()
        health["counts"]["memories"] = memory_col.count()
        health["counts"]["chunks"] = chunks_col.count()

    except Exception as e:
        health["services"]["chromadb"] = {"status": "error", "error": str(e)}
        health["healthy"] = False

    # 3. Check OpenAI
    try:
        health["services"]["openai"] = {
            "status": "configured",
            "model": config.openai_embed_model
        }
    except Exception as e:
        health["services"]["openai"] = {"status": "error", "error": str(e)}

    # 4. Check PostgreSQL
    try:
        if pg_client:
            pool_size = pg_client.get_pool_size() if hasattr(pg_client, 'get_pool_size') else "unknown"
            health["services"]["postgres"] = {
                "status": "healthy",
                "pool_size": pool_size
            }

            # Get event counts
            async with pg_client.acquire() as conn:
                event_count = await conn.fetchval("SELECT COUNT(*) FROM semantic_event")
                entity_count = await conn.fetchval("SELECT COUNT(*) FROM entity")
                pending = await conn.fetchval(
                    "SELECT COUNT(*) FROM extraction_job WHERE status = 'PENDING'"
                )

            health["counts"]["events"] = event_count
            health["counts"]["entities"] = entity_count
            health["pending_jobs"] = pending

    except Exception as e:
        health["services"]["postgres"] = {"status": "error", "error": str(e)}

    # 5. Check Graph (if available)
    try:
        if graph_service:
            graph_health = await graph_service.get_health()
            health["services"]["graph"] = graph_health
    except Exception as e:
        health["services"]["graph"] = {"status": "error", "error": str(e)}

    # 6. Check specific job status if requested
    if artifact_id:
        try:
            job_result = await job_status(artifact_id)
            health["job_status"] = job_result
        except Exception as e:
            health["job_status"] = {"error": str(e)}

    return health
```

## Test Cases

### File: `tests/integration/test_status.py`

```python
"""Integration tests for status() tool."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_status_services():
    """Mock services for status testing."""
    with patch("server.chroma_manager") as mock_chroma, \
         patch("server.pg_client") as mock_pg, \
         patch("server.graph_service") as mock_graph, \
         patch("server.config") as mock_config:

        mock_client = MagicMock()
        mock_client.heartbeat.return_value = True

        mock_collection = MagicMock()
        mock_collection.count.return_value = 100
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.get_client.return_value = mock_client

        mock_config.openai_embed_model = "text-embedding-3-large"

        # Mock PostgreSQL
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=50)
        mock_pg.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pg.acquire.return_value.__aexit__ = AsyncMock()
        mock_pg.get_pool_size.return_value = 10

        # Mock graph
        mock_graph.get_health = AsyncMock(return_value={"status": "healthy", "nodes": 100})

        yield {
            "chroma": mock_chroma,
            "client": mock_client,
            "pg": mock_pg,
            "graph": mock_graph,
            "config": mock_config
        }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_healthy(mock_status_services):
    """Test status returns healthy system."""
    from server import status

    result = await status()

    assert result["healthy"] == True
    assert "version" in result
    assert "5.0.0" in result["version"]
    assert "services" in result
    assert "counts" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_with_job_check(mock_status_services):
    """Test status with specific job check."""
    from server import status

    with patch("server.job_status") as mock_job:
        mock_job.return_value = {"status": "DONE", "artifact_id": "art_123"}

        result = await status(artifact_id="art_123")

    assert "job_status" in result
    assert result["job_status"]["status"] == "DONE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_service_failure(mock_status_services):
    """Test status handles service failures gracefully."""
    from server import status

    mock_status_services["client"].heartbeat.side_effect = Exception("Connection failed")

    result = await status()

    assert result["healthy"] == False
    assert result["services"]["chromadb"]["status"] == "error"
```

## Success Criteria

- [ ] `status()` function added to server.py
- [ ] `__version__` updated to "5.0.0-alpha.1"
- [ ] All 3 test cases pass
- [ ] Existing tools still work
- [ ] All Phase 1 tools work together

## Estimated Effort

- Implementation: ~80 lines
- Tests: ~80 lines
- Duration: 1 session

## Checklist

- [ ] Implementation complete
- [ ] Version updated
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Existing tests still pass
- [ ] All V5 tools work together
- [ ] Code reviewed
- [ ] User approved
- [ ] Committed (after approval)

## Phase 1 Complete

After this phase:
- All 4 V5 tools are available: `remember`, `recall`, `forget`, `status`
- Existing 17 tools still work unchanged
- Version is 5.0.0-alpha.1
- Ready for Phase 2 (storage unification)
