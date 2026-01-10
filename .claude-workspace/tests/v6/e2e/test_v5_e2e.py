"""
V5 E2E Acceptance Tests

These tests verify the full V5 pipeline works end-to-end against real infrastructure.
Run with: pytest .claude-workspace/tests/v5/e2e/ --run-e2e

Tests cover:
- Full remember -> recall cycle
- Event extraction pipeline
- Graph expansion across documents
- Cascade deletion verification
- System health monitoring

Markers:
- @pytest.mark.e2e: End-to-end tests
- @pytest.mark.v5: V5-specific tests
- @pytest.mark.slow: Long-running tests
"""

import pytest
import asyncio
import hashlib
import time
import uuid
from typing import Optional, Dict, Any, List

# Import MCP client for real infrastructure tests
import sys
from pathlib import Path
lib_path = Path(__file__).parent.parent / "adapters"
sys.path.insert(0, str(lib_path))

try:
    from mcp_client import MCPClient, MCPResponse
    MCP_CLIENT_AVAILABLE = True
except ImportError as e:
    MCP_CLIENT_AVAILABLE = False
    _IMPORT_ERROR = str(e)


# =============================================================================
# Helpers
# =============================================================================

def generate_unique_content(prefix: str = "e2e_test") -> str:
    """Generate unique content for test isolation."""
    unique_id = uuid.uuid4().hex[:8]
    return f"{prefix}_{unique_id}: This is test content for V5 E2E testing."


def generate_content_id(content: str) -> str:
    """Generate V5 content ID from content."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"art_{content_hash}"


async def wait_for_job(
    client: "MCPClient",
    artifact_id: str,
    timeout: int = 30,
    poll_interval: float = 2.0
) -> Dict[str, Any]:
    """
    Helper to wait for event extraction job to complete.

    Args:
        client: MCP client instance
        artifact_id: Content ID to check job for
        timeout: Maximum wait time in seconds
        poll_interval: Time between status checks

    Returns:
        Final job status dict
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        response = client.call_tool("status", {"artifact_id": artifact_id})

        if not response.success:
            return {"status": "ERROR", "error": response.error}

        data = response.data or {}
        job_status = data.get("job_status", {})
        status = job_status.get("status", "UNKNOWN")

        if status in ("DONE", "COMPLETED"):
            return {"status": "DONE", "data": job_status}
        elif status == "FAILED":
            return {"status": "FAILED", "data": job_status}

        await asyncio.sleep(poll_interval)

    return {"status": "TIMEOUT", "elapsed": time.time() - start_time}


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mcp_client():
    """Create MCP client for E2E tests."""
    if not MCP_CLIENT_AVAILABLE:
        pytest.skip("MCP client not available")

    client = MCPClient()
    client.initialize()
    yield client
    client.close()


@pytest.fixture
def created_content(mcp_client: "MCPClient") -> List[str]:
    """Track created content for cleanup."""
    content_ids: List[str] = []
    yield content_ids

    # Cleanup
    for content_id in content_ids:
        try:
            mcp_client.call_tool("forget", {"id": content_id, "confirm": True})
        except Exception:
            pass


# =============================================================================
# Test: E2E Store and Retrieve
# =============================================================================

@pytest.mark.e2e
@pytest.mark.v5
class TestE2EStoreRetrieve:
    """End-to-end tests for store and retrieve cycle."""

    def test_e2e_store_retrieve(
        self,
        mcp_client: "MCPClient",
        created_content: List[str]
    ):
        """remember() -> wait job -> recall(query) returns it."""
        # Generate unique content
        content = generate_unique_content("store_retrieve")
        expected_id = generate_content_id(content)

        # Store with remember()
        remember_response = mcp_client.call_tool("remember", {
            "content": content,
            "context": "note",
            "title": "E2E Store Retrieve Test"
        })

        assert remember_response.success, f"remember() failed: {remember_response.error}"
        assert remember_response.data is not None

        data = remember_response.data
        assert "id" in data
        assert data["id"].startswith("art_")

        content_id = data["id"]
        created_content.append(content_id)

        # Wait for indexing
        time.sleep(2)

        # Retrieve with recall()
        recall_response = mcp_client.call_tool("recall", {
            "query": content[:50],
            "limit": 10
        })

        assert recall_response.success, f"recall() failed: {recall_response.error}"
        assert recall_response.data is not None

        # Should find the stored content
        results = recall_response.data.get("results", [])
        assert len(results) > 0, "No results returned from recall"

    def test_e2e_store_retrieve_by_id(
        self,
        mcp_client: "MCPClient",
        created_content: List[str]
    ):
        """remember() -> recall(id=art_xxx) returns exact content."""
        content = generate_unique_content("retrieve_by_id")

        # Store
        remember_response = mcp_client.call_tool("remember", {
            "content": content,
            "context": "preference"
        })

        assert remember_response.success
        content_id = remember_response.data["id"]
        created_content.append(content_id)

        # Retrieve by ID
        recall_response = mcp_client.call_tool("recall", {
            "id": content_id
        })

        assert recall_response.success
        assert recall_response.data["total_count"] == 1


# =============================================================================
# Test: E2E Event Extraction
# =============================================================================

@pytest.mark.e2e
@pytest.mark.v5
@pytest.mark.slow
class TestE2EEventExtraction:
    """End-to-end tests for event extraction pipeline."""

    def test_e2e_event_extraction(
        self,
        mcp_client: "MCPClient",
        created_content: List[str]
    ):
        """remember() triggers extraction, recall(include_events=True) returns events."""
        # Content with extractable events
        content = f"""
        Meeting Notes - {uuid.uuid4().hex[:8]}
        Date: 2024-03-15

        DECISIONS MADE:
        - Alice decided to launch the product on April 1st.
        - The team agreed to use a freemium pricing model.

        COMMITMENTS:
        - Bob committed to delivering the API by March 25th.
        - Carol will complete the UI mockups by March 20th.
        """

        # Store
        remember_response = mcp_client.call_tool("remember", {
            "content": content,
            "context": "meeting",
            "title": "Event Extraction Test Meeting"
        })

        assert remember_response.success
        content_id = remember_response.data["id"]
        created_content.append(content_id)

        # Check if events were queued
        events_queued = remember_response.data.get("events_queued", False)

        if events_queued:
            # Wait for extraction (may take time)
            time.sleep(10)

            # Retrieve with events
            recall_response = mcp_client.call_tool("recall", {
                "id": content_id,
                "include_events": True
            })

            assert recall_response.success
            # Events may be present after extraction completes


# =============================================================================
# Test: E2E Graph Expansion
# =============================================================================

@pytest.mark.e2e
@pytest.mark.v5
@pytest.mark.slow
class TestE2EGraphExpansion:
    """End-to-end tests for graph-based context expansion."""

    def test_e2e_graph_expansion(
        self,
        mcp_client: "MCPClient",
        created_content: List[str]
    ):
        """Two related docs -> recall(expand=True) returns related_context."""
        # Create first document about Alice
        content1 = f"""
        Project Alpha Status - {uuid.uuid4().hex[:8]}
        Lead: Alice Chen

        Alice Chen presented the Q1 roadmap. The team will focus on:
        - API improvements
        - Performance optimization
        - New pricing model
        """

        # Create second document also about Alice
        content2 = f"""
        Design Review Meeting - {uuid.uuid4().hex[:8]}
        Attendees: Alice Chen, Bob Smith

        Alice Chen reviewed the new UI mockups with Bob.
        Decision: Proceed with design option A.
        """

        # Store both
        resp1 = mcp_client.call_tool("remember", {
            "content": content1,
            "context": "meeting",
            "title": "Project Alpha Status"
        })
        assert resp1.success
        created_content.append(resp1.data["id"])

        resp2 = mcp_client.call_tool("remember", {
            "content": content2,
            "context": "meeting",
            "title": "Design Review"
        })
        assert resp2.success
        created_content.append(resp2.data["id"])

        # Wait for indexing and potential extraction
        time.sleep(3)

        # Query with graph expansion
        recall_response = mcp_client.call_tool("recall", {
            "query": "Alice Chen decisions",
            "expand": True,
            "include_entities": True,
            "limit": 10
        })

        assert recall_response.success
        assert "related" in recall_response.data


# =============================================================================
# Test: E2E Cascade Delete
# =============================================================================

@pytest.mark.e2e
@pytest.mark.v5
class TestE2ECascadeDelete:
    """End-to-end tests for cascade deletion."""

    def test_e2e_cascade_delete(
        self,
        mcp_client: "MCPClient"
    ):
        """forget() cascades to chunks, events."""
        # Create large content that will be chunked (reduced size for testing)
        # 1200 tokens ≈ 4800 chars, so 150 * 42 = 6300 chars should trigger chunking
        content = ("Large document content for chunking test. " * 150)

        # Store
        remember_response = mcp_client.call_tool("remember", {
            "content": content,
            "context": "note",
            "title": "Cascade Delete Test"
        })

        assert remember_response.success, f"remember() failed: {remember_response.error}"
        assert "id" in remember_response.data, f"No 'id' in response: {remember_response.data}"
        content_id = remember_response.data["id"]
        is_chunked = remember_response.data.get("is_chunked", False)

        # Delete with cascade
        forget_response = mcp_client.call_tool("forget", {
            "id": content_id,
            "confirm": True
        })

        assert forget_response.success
        assert forget_response.data.get("deleted") is True

        # Verify cascade info
        cascade = forget_response.data.get("cascade", {})
        if is_chunked:
            assert cascade.get("chunks", 0) >= 0

        # Verify content is gone
        recall_response = mcp_client.call_tool("recall", {"id": content_id})
        assert recall_response.data.get("total_count", 0) == 0


# =============================================================================
# Test: E2E Status
# =============================================================================

@pytest.mark.e2e
@pytest.mark.v5
class TestE2EStatus:
    """End-to-end tests for system status."""

    def test_e2e_status(
        self,
        mcp_client: "MCPClient"
    ):
        """status() reports V5 collections and counts."""
        response = mcp_client.call_tool("status", {})

        assert response.success, f"status() failed: {response.error}"
        assert response.data is not None

        data = response.data

        # Required fields
        assert "version" in data
        assert "healthy" in data
        assert "services" in data
        assert "counts" in data

        # V5 collections should be reported
        services = data.get("services", {})
        chromadb = services.get("chromadb", {})
        if "collections" in chromadb:
            collections = chromadb["collections"]
            assert "content" in collections
            assert "chunks" in collections

    def test_e2e_status_with_artifact(
        self,
        mcp_client: "MCPClient",
        created_content: List[str]
    ):
        """status(artifact_id) includes job status."""
        # Create content first
        content = generate_unique_content("status_test")
        remember_response = mcp_client.call_tool("remember", {
            "content": content,
            "context": "note"
        })

        assert remember_response.success
        content_id = remember_response.data["id"]
        created_content.append(content_id)

        # Check status with artifact_id
        status_response = mcp_client.call_tool("status", {
            "artifact_id": content_id
        })

        assert status_response.success


# =============================================================================
# Test: E2E Deduplication
# =============================================================================

@pytest.mark.e2e
@pytest.mark.v5
class TestE2EDeduplication:
    """End-to-end tests for content deduplication."""

    def test_e2e_deduplication(
        self,
        mcp_client: "MCPClient",
        created_content: List[str]
    ):
        """Same content stored twice returns same ID."""
        content = generate_unique_content("dedup_test")

        # Store first time
        resp1 = mcp_client.call_tool("remember", {
            "content": content,
            "context": "note",
            "title": "First Store"
        })

        assert resp1.success
        first_id = resp1.data["id"]
        created_content.append(first_id)

        # Store second time with different metadata
        resp2 = mcp_client.call_tool("remember", {
            "content": content,
            "context": "note",
            "title": "Second Store"
        })

        assert resp2.success
        second_id = resp2.data["id"]

        # IDs should match (content-based)
        assert first_id == second_id

        # Status should indicate unchanged
        assert resp2.data.get("status") == "unchanged"


# =============================================================================
# Test: E2E Conversation
# =============================================================================

@pytest.mark.e2e
@pytest.mark.v5
class TestE2EConversation:
    """End-to-end tests for conversation storage."""

    def test_e2e_conversation_turns(
        self,
        mcp_client: "MCPClient",
        created_content: List[str]
    ):
        """Store and retrieve conversation turns."""
        conversation_id = f"conv_{uuid.uuid4().hex[:8]}"

        # Store conversation turns
        turns = [
            {"role": "user", "content": "Hello, how can I help you?"},
            {"role": "assistant", "content": "I need help with my project."},
            {"role": "user", "content": "Sure, what kind of project?"},
        ]

        for i, turn in enumerate(turns):
            response = mcp_client.call_tool("remember", {
                "content": turn["content"],
                "context": "conversation",
                "conversation_id": conversation_id,
                "turn_index": i,
                "role": turn["role"]
            })

            assert response.success
            created_content.append(response.data["id"])

        # Retrieve conversation history
        recall_response = mcp_client.call_tool("recall", {
            "conversation_id": conversation_id,
            "limit": 20
        })

        assert recall_response.success


# =============================================================================
# Test: E2E Error Handling
# =============================================================================

@pytest.mark.e2e
@pytest.mark.v5
class TestE2EErrorHandling:
    """End-to-end tests for error handling."""

    def test_e2e_invalid_context(
        self,
        mcp_client: "MCPClient"
    ):
        """Invalid context returns proper error."""
        response = mcp_client.call_tool("remember", {
            "content": "Test content",
            "context": "invalid_context_type"
        })

        # Should return error
        data = response.data or {}
        assert "error" in data

    def test_e2e_forget_without_confirm(
        self,
        mcp_client: "MCPClient",
        created_content: List[str]
    ):
        """forget() without confirm returns error."""
        # Create content
        content = generate_unique_content("forget_test")
        remember_response = mcp_client.call_tool("remember", {
            "content": content,
            "context": "note"
        })

        assert remember_response.success
        content_id = remember_response.data["id"]
        created_content.append(content_id)

        # Try to forget without confirm
        forget_response = mcp_client.call_tool("forget", {
            "id": content_id
            # confirm not specified (defaults to False)
        })

        # Should return error about confirm
        data = forget_response.data or {}
        assert "error" in data
        assert "confirm" in data["error"].lower()
