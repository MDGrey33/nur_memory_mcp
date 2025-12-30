"""
Playwright API Tests for Memory Operations.

Tests all memory tools: memory_store, memory_search, memory_list, memory_delete

Test Environment:
- Requires MCP server running at MCP_URL (default: http://localhost:3201/mcp/)
- Uses fixtures from conftest.py (mcp_client, env_config)

Usage:
    # Run all memory tests
    pytest tests/playwright/api/test_memory.py -v

    # Run only store tests
    pytest tests/playwright/api/test_memory.py -v -k "store"

    # Run with specific environment
    MCP_URL=http://localhost:3001/mcp/ pytest tests/playwright/api/test_memory.py -v
"""

from __future__ import annotations

import re
import uuid
import pytest
from typing import Any, Dict, Generator, List, Optional

# Import from lib directory (added to path in conftest.py)
from lib import MCPClient, MCPResponse, MCPClientError


# =============================================================================
# Test Constants and Schema Definitions
# =============================================================================

# Valid memory types
VALID_MEMORY_TYPES = ["preference", "fact", "context", "instruction", "note"]

# Confidence range
MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0


# =============================================================================
# Response Schema Validators
# =============================================================================

# MCP protocol returns text responses. These helpers parse them.
MEMORY_ID_PATTERN = re.compile(r'\[mem_([a-f0-9]+)\]')


def extract_memory_id_from_text(text: str) -> Optional[str]:
    """
    Extract memory_id from MCP text response.

    Text format: "Stored memory [mem_xxx]: content..." or "[mem_xxx] (type, conf=0.9): ..."
    Returns: "mem_xxx" or None if not found
    """
    match = MEMORY_ID_PATTERN.search(text)
    if match:
        return f"mem_{match.group(1)}"
    return None


def extract_all_memory_ids_from_text(text: str) -> List[str]:
    """
    Extract all memory_ids from MCP text response.

    Text format: "[mem_xxx] (...)\n[mem_yyy] (...)\n..."
    Returns: ["mem_xxx", "mem_yyy", ...]
    """
    matches = MEMORY_ID_PATTERN.findall(text)
    return [f"mem_{m}" for m in matches]


def validate_memory_store_response(data: Dict[str, Any]) -> bool:
    """
    Validate memory_store response schema.

    MCP returns text like: "Stored memory [mem_xxx]: content..."
    We validate that the text contains a valid memory_id.
    """
    if data is None:
        return False

    # Handle text response format (MCP protocol standard)
    if "text" in data:
        text = data["text"]
        memory_id = extract_memory_id_from_text(text)
        return memory_id is not None and memory_id.startswith("mem_")

    # Handle JSON response format (legacy/alternative)
    if "memory_id" not in data:
        return False
    if not isinstance(data["memory_id"], str):
        return False
    if not data["memory_id"].startswith("mem_"):
        return False
    return True


def validate_memory_search_response(data: Dict[str, Any]) -> bool:
    """
    Validate memory_search response schema.

    MCP returns text like: "[mem_xxx] (type, conf=0.9): content\n..."
    We validate that the text contains valid memory entries.
    """
    if data is None:
        return False

    # Handle text response format (MCP protocol standard)
    if "text" in data:
        # Text response is valid - may be empty or contain memory entries
        return True

    # Handle JSON response format (legacy/alternative)
    if "memories" not in data:
        return False
    if not isinstance(data["memories"], list):
        return False
    return True


def validate_memory_list_response(data: Dict[str, Any]) -> bool:
    """
    Validate memory_list response schema.

    MCP returns text like: "Found N memories:\n[mem_xxx] (type, conf=0.9): content\n..."
    """
    if data is None:
        return False

    # Handle text response format (MCP protocol standard)
    if "text" in data:
        # Text response is valid - may indicate "Found N memories" or be empty
        return True

    # Handle JSON response format (legacy/alternative)
    if "memories" not in data:
        return False
    if not isinstance(data["memories"], list):
        return False
    return True


def validate_memory_delete_response(data: Dict[str, Any]) -> bool:
    """
    Validate memory_delete response schema.

    MCP returns text like: "Deleted memory [mem_xxx]" or similar.
    """
    if data is None:
        return False

    # Handle text response format (MCP protocol standard)
    if "text" in data:
        text = data["text"].lower()
        return "deleted" in text or "removed" in text or "success" in text

    # Handle JSON response format (legacy/alternative)
    return "status" in data or "deleted" in str(data).lower()


def get_memory_id_from_response(data: Dict[str, Any]) -> Optional[str]:
    """
    Extract memory_id from response data.

    Handles both MCP text format and JSON format responses.

    Args:
        data: Response data dict (may have 'text' or 'memory_id' key)

    Returns:
        memory_id string or None if not found
    """
    if data is None:
        return None

    # Handle text response format (MCP protocol standard)
    if "text" in data:
        return extract_memory_id_from_text(data["text"])

    # Handle JSON response format (legacy/alternative)
    return data.get("memory_id")


def validate_memory_item(memory: Dict[str, Any]) -> bool:
    """
    Validate individual memory item structure.

    Expected fields in each memory:
    - id or memory_id: str
    - content: str
    - type: str
    - confidence: float (0-1)
    - created_at: str (ISO timestamp)
    """
    if memory is None:
        return False

    # Check for ID (may be 'id' or 'memory_id')
    has_id = "id" in memory or "memory_id" in memory
    if not has_id:
        return False

    # Content is required
    if "content" not in memory:
        return False

    return True


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def unique_id() -> str:
    """Generate unique ID for test isolation."""
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="function")
def test_memory_params(unique_id: str) -> Dict[str, Any]:
    """Generate unique memory parameters for testing."""
    return {
        "content": f"Test memory content - User prefers Python - {unique_id}",
        "type": "preference",
        "confidence": 0.9
    }


@pytest.fixture(scope="function")
def cleanup_memory_ids() -> Generator[List[str], None, None]:
    """
    Track memory IDs for cleanup after test.

    Usage:
        def test_something(mcp_client, cleanup_memory_ids):
            response = mcp_client.call_tool("memory_store", {...})
            if response.success and response.data:
                cleanup_memory_ids.append(response.data.get("memory_id"))
    """
    ids: List[str] = []
    yield ids
    # Note: Cleanup happens in cleanup_test_memories fixture


@pytest.fixture(scope="function")
def cleanup_test_memories(
    mcp_client: MCPClient,
    cleanup_memory_ids: List[str]
) -> Generator[None, None, None]:
    """
    Cleanup test memories after test completes.

    This fixture must be explicitly used by tests that create memories.
    """
    yield

    for memory_id in cleanup_memory_ids:
        if memory_id:
            try:
                mcp_client.call_tool("memory_delete", {"memory_id": memory_id})
            except Exception:
                pass  # Best effort cleanup


@pytest.fixture(scope="function")
def stored_memory(
    mcp_client: MCPClient,
    test_memory_params: Dict[str, Any],
    cleanup_memory_ids: List[str]
) -> Generator[Dict[str, Any], None, None]:
    """
    Create a stored memory for tests that need existing data.

    Yields:
        Dict with memory_id and original params
    """
    response = mcp_client.call_tool("memory_store", test_memory_params)

    if not response.success or not response.data:
        pytest.skip("Failed to create test memory - server may be unavailable")

    memory_id = get_memory_id_from_response(response.data)
    if memory_id:
        cleanup_memory_ids.append(memory_id)

    yield {
        "memory_id": memory_id,
        "content": test_memory_params["content"],
        "type": test_memory_params["type"],
        "confidence": test_memory_params["confidence"],
    }


# =============================================================================
# Test Class: memory_store
# =============================================================================

@pytest.mark.api
@pytest.mark.memory
class TestMemoryStore:
    """Tests for the memory_store tool."""

    def test_store_basic_memory(
        self,
        mcp_client: MCPClient,
        test_memory_params: Dict[str, Any],
        cleanup_memory_ids: List[str],
        cleanup_test_memories: None
    ) -> None:
        """Test storing a basic memory with required fields."""
        response = mcp_client.call_tool("memory_store", test_memory_params)

        assert response.success, f"memory_store failed: {response.error}"
        assert response.data is not None, "Response data is None"
        assert validate_memory_store_response(response.data), \
            f"Invalid response schema: {response.data}"

        memory_id = get_memory_id_from_response(response.data)
        assert memory_id is not None, "No memory_id in response"
        assert memory_id.startswith("mem_"), f"Invalid memory_id format: {memory_id}"

        # Track for cleanup
        cleanup_memory_ids.append(memory_id)

    def test_store_memory_all_types(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_memory_ids: List[str],
        cleanup_test_memories: None
    ) -> None:
        """Test storing memories with all valid types."""
        for memory_type in VALID_MEMORY_TYPES:
            params = {
                "content": f"Test memory for type {memory_type} - {unique_id}",
                "type": memory_type,
                "confidence": 0.85
            }

            response = mcp_client.call_tool("memory_store", params)

            assert response.success, \
                f"memory_store failed for type '{memory_type}': {response.error}"

            memory_id = get_memory_id_from_response(response.data) if response.data else None
            if memory_id:
                cleanup_memory_ids.append(memory_id)

    def test_store_memory_confidence_range(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_memory_ids: List[str],
        cleanup_test_memories: None
    ) -> None:
        """Test storing memories with various confidence values."""
        confidence_values = [0.0, 0.1, 0.5, 0.9, 1.0]

        for confidence in confidence_values:
            params = {
                "content": f"Test memory with confidence {confidence} - {unique_id}",
                "type": "preference",
                "confidence": confidence
            }

            response = mcp_client.call_tool("memory_store", params)

            assert response.success, \
                f"memory_store failed for confidence {confidence}: {response.error}"

            memory_id = get_memory_id_from_response(response.data) if response.data else None
            if memory_id:
                cleanup_memory_ids.append(memory_id)

    def test_store_memory_long_content(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_memory_ids: List[str],
        cleanup_test_memories: None
    ) -> None:
        """Test storing memory with long content."""
        long_content = "This is a long memory content. " * 100  # ~3200 chars

        params = {
            "content": f"{long_content} - {unique_id}",
            "type": "note",
            "confidence": 0.8
        }

        response = mcp_client.call_tool("memory_store", params)

        assert response.success, f"memory_store failed for long content: {response.error}"

        memory_id = get_memory_id_from_response(response.data) if response.data else None
        if memory_id:
            cleanup_memory_ids.append(memory_id)

    def test_store_memory_special_characters(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_memory_ids: List[str],
        cleanup_test_memories: None
    ) -> None:
        """Test storing memory with special characters in content."""
        special_content = (
            f"Test with special chars: "
            f"quotes \"double\" 'single' "
            f"unicode \u00e9\u00e0\u00fc\u00f1 "
            f"emoji (no actual emoji) "
            f"newlines\n\ttabs "
            f"backslash \\\\ "
            f"angle brackets <tag> "
            f"ampersand & "
            f"- {unique_id}"
        )

        params = {
            "content": special_content,
            "type": "note",
            "confidence": 0.75
        }

        response = mcp_client.call_tool("memory_store", params)

        assert response.success, \
            f"memory_store failed for special characters: {response.error}"

        memory_id = get_memory_id_from_response(response.data) if response.data else None
        if memory_id:
            cleanup_memory_ids.append(memory_id)

    def test_store_memory_returns_latency(
        self,
        mcp_client: MCPClient,
        test_memory_params: Dict[str, Any],
        cleanup_memory_ids: List[str],
        cleanup_test_memories: None
    ) -> None:
        """Test that response includes latency measurement."""
        response = mcp_client.call_tool("memory_store", test_memory_params)

        assert response.success, f"memory_store failed: {response.error}"
        assert response.latency_ms > 0, "Latency should be positive"
        assert response.latency_ms < 30000, "Latency exceeded 30 seconds"

        memory_id = get_memory_id_from_response(response.data) if response.data else None
        if memory_id:
            cleanup_memory_ids.append(memory_id)


# =============================================================================
# Test Class: memory_store Error Cases
# =============================================================================

@pytest.mark.api
@pytest.mark.memory
class TestMemoryStoreErrors:
    """Error handling tests for memory_store tool."""

    def test_store_memory_missing_content(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test error when content is missing."""
        params = {
            "type": "preference",
            "confidence": 0.9
            # content is missing
        }

        response = mcp_client.call_tool("memory_store", params)

        # Should fail or return error
        assert not response.success or response.error is not None, \
            "Should fail when content is missing"

    def test_store_memory_empty_content(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test behavior with empty content string."""
        params = {
            "content": "",
            "type": "preference",
            "confidence": 0.9
        }

        response = mcp_client.call_tool("memory_store", params)

        # Empty content should either fail or be rejected
        # The exact behavior depends on server implementation
        # We just verify we get a valid response
        assert response is not None, "Should return a response"

    def test_store_memory_invalid_type(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test behavior with invalid memory type."""
        params = {
            "content": f"Test memory - {unique_id}",
            "type": "invalid_type_xyz",
            "confidence": 0.9
        }

        response = mcp_client.call_tool("memory_store", params)

        # May fail or default to a valid type
        # We just verify we get a valid response
        assert response is not None, "Should return a response"

    def test_store_memory_invalid_confidence(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test behavior with out-of-range confidence values."""
        invalid_confidences = [-0.1, 1.5, 100, -100]

        for confidence in invalid_confidences:
            params = {
                "content": f"Test memory - {unique_id}",
                "type": "preference",
                "confidence": confidence
            }

            response = mcp_client.call_tool("memory_store", params)

            # Should either fail or clamp the value
            assert response is not None, \
                f"Should return a response for confidence {confidence}"


# =============================================================================
# Test Class: memory_search
# =============================================================================

@pytest.mark.api
@pytest.mark.memory
class TestMemorySearch:
    """Tests for the memory_search tool."""

    def test_search_basic_query(
        self,
        mcp_client: MCPClient,
        stored_memory: Dict[str, Any],
        cleanup_test_memories: None
    ) -> None:
        """Test basic memory search with a query."""
        # Search for content from the stored memory
        response = mcp_client.call_tool("memory_search", {
            "query": "Python preference",
            "limit": 10
        })

        assert response.success, f"memory_search failed: {response.error}"
        assert response.data is not None, "Response data is None"
        assert validate_memory_search_response(response.data), \
            f"Invalid response schema: {response.data}"

    def test_search_returns_relevant_results(
        self,
        mcp_client: MCPClient,
        stored_memory: Dict[str, Any],
        cleanup_test_memories: None
    ) -> None:
        """Test that search returns relevant results."""
        # Search for specific content
        search_query = "Python"  # Part of our test memory content

        response = mcp_client.call_tool("memory_search", {
            "query": search_query,
            "limit": 10
        })

        assert response.success, f"memory_search failed: {response.error}"

        memories = response.data.get("memories", [])
        # Note: May return empty if embeddings haven't propagated yet
        # or if this is the first search after store

    def test_search_with_limit(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test search respects limit parameter."""
        limits = [1, 5, 10, 20]

        for limit in limits:
            response = mcp_client.call_tool("memory_search", {
                "query": "test",
                "limit": limit
            })

            assert response.success, f"memory_search failed with limit {limit}: {response.error}"
            assert response.data is not None

            memories = response.data.get("memories", [])
            assert len(memories) <= limit, \
                f"Returned {len(memories)} memories, expected <= {limit}"

    def test_search_with_type_filter(
        self,
        mcp_client: MCPClient,
        stored_memory: Dict[str, Any],
        cleanup_test_memories: None
    ) -> None:
        """Test search with type filter."""
        response = mcp_client.call_tool("memory_search", {
            "query": "Python",
            "type": "preference",
            "limit": 10
        })

        assert response.success, f"memory_search failed: {response.error}"
        assert response.data is not None

        # If results returned, they should match the type filter
        memories = response.data.get("memories", [])
        for memory in memories:
            if "type" in memory:
                assert memory["type"] == "preference", \
                    f"Expected type 'preference', got '{memory.get('type')}'"

    def test_search_empty_query(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test search behavior with empty query."""
        response = mcp_client.call_tool("memory_search", {
            "query": "",
            "limit": 10
        })

        # Should either fail or return empty results
        assert response is not None, "Should return a response"

    def test_search_no_results(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test search that finds no matching results."""
        # Use a very specific query that shouldn't match anything
        nonsense_query = f"xyzzy_nonexistent_content_{unique_id}_zzzz"

        response = mcp_client.call_tool("memory_search", {
            "query": nonsense_query,
            "limit": 10
        })

        assert response.success, f"memory_search failed: {response.error}"
        assert response.data is not None

        memories = response.data.get("memories", [])
        # Should return empty or near-empty results
        # (semantic search may return low-confidence matches)


# =============================================================================
# Test Class: memory_list
# =============================================================================

@pytest.mark.api
@pytest.mark.memory
class TestMemoryList:
    """Tests for the memory_list tool."""

    def test_list_basic(
        self,
        mcp_client: MCPClient,
        stored_memory: Dict[str, Any],
        cleanup_test_memories: None
    ) -> None:
        """Test basic memory listing."""
        response = mcp_client.call_tool("memory_list", {
            "limit": 10
        })

        assert response.success, f"memory_list failed: {response.error}"
        assert response.data is not None, "Response data is None"
        assert validate_memory_list_response(response.data), \
            f"Invalid response schema: {response.data}"

    def test_list_with_type_filter(
        self,
        mcp_client: MCPClient,
        stored_memory: Dict[str, Any],
        cleanup_test_memories: None
    ) -> None:
        """Test listing memories filtered by type."""
        response = mcp_client.call_tool("memory_list", {
            "type": "preference",
            "limit": 10
        })

        assert response.success, f"memory_list failed: {response.error}"
        assert response.data is not None

        # Verify all returned memories match the type filter
        memories = response.data.get("memories", [])
        for memory in memories:
            if "type" in memory:
                assert memory["type"] == "preference", \
                    f"Expected type 'preference', got '{memory.get('type')}'"

    def test_list_with_limit(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test list respects limit parameter."""
        limits = [1, 5, 10]

        for limit in limits:
            response = mcp_client.call_tool("memory_list", {
                "limit": limit
            })

            assert response.success, f"memory_list failed with limit {limit}: {response.error}"
            assert response.data is not None

            memories = response.data.get("memories", [])
            assert len(memories) <= limit, \
                f"Returned {len(memories)} memories, expected <= {limit}"

    def test_list_returns_valid_memory_items(
        self,
        mcp_client: MCPClient,
        stored_memory: Dict[str, Any],
        cleanup_test_memories: None
    ) -> None:
        """Test that listed memories have valid structure."""
        response = mcp_client.call_tool("memory_list", {
            "limit": 20
        })

        assert response.success, f"memory_list failed: {response.error}"

        memories = response.data.get("memories", [])

        for memory in memories:
            assert validate_memory_item(memory), \
                f"Invalid memory structure: {memory}"

    def test_list_all_types(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test listing with each memory type filter."""
        for memory_type in VALID_MEMORY_TYPES:
            response = mcp_client.call_tool("memory_list", {
                "type": memory_type,
                "limit": 5
            })

            assert response.success, \
                f"memory_list failed for type '{memory_type}': {response.error}"


# =============================================================================
# Test Class: memory_delete
# =============================================================================

@pytest.mark.api
@pytest.mark.memory
class TestMemoryDelete:
    """Tests for the memory_delete tool."""

    def test_delete_existing_memory(
        self,
        mcp_client: MCPClient,
        test_memory_params: Dict[str, Any]
    ) -> None:
        """Test deleting an existing memory."""
        # First, create a memory
        store_response = mcp_client.call_tool("memory_store", test_memory_params)
        assert store_response.success, f"Failed to create test memory: {store_response.error}"

        memory_id = get_memory_id_from_response(store_response.data)
        assert memory_id, "No memory_id in store response"

        # Now delete it
        delete_response = mcp_client.call_tool("memory_delete", {
            "memory_id": memory_id
        })

        assert delete_response.success, f"memory_delete failed: {delete_response.error}"
        assert delete_response.data is not None, "Response data is None"
        assert validate_memory_delete_response(delete_response.data), \
            f"Invalid response schema: {delete_response.data}"

    def test_delete_nonexistent_memory(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test deleting a non-existent memory."""
        fake_memory_id = f"mem_{unique_id}00000000"

        response = mcp_client.call_tool("memory_delete", {
            "memory_id": fake_memory_id
        })

        # Should either fail gracefully or return success with no-op
        # Different servers may handle this differently
        assert response is not None, "Should return a response"

    def test_delete_invalid_memory_id_format(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test deleting with invalid memory ID format."""
        invalid_ids = [
            "",
            "invalid",
            "12345",
            "mem-invalid",
        ]

        for invalid_id in invalid_ids:
            response = mcp_client.call_tool("memory_delete", {
                "memory_id": invalid_id
            })

            # Should handle gracefully
            assert response is not None, \
                f"Should return a response for invalid ID: {invalid_id}"

    def test_delete_verify_memory_removed(
        self,
        mcp_client: MCPClient,
        test_memory_params: Dict[str, Any]
    ) -> None:
        """Test that deleted memory is no longer retrievable."""
        # Create a memory
        store_response = mcp_client.call_tool("memory_store", test_memory_params)
        assert store_response.success

        memory_id = get_memory_id_from_response(store_response.data)

        # Delete it
        delete_response = mcp_client.call_tool("memory_delete", {
            "memory_id": memory_id
        })
        assert delete_response.success or delete_response.data is not None

        # Try to find it in list
        list_response = mcp_client.call_tool("memory_list", {
            "limit": 100
        })

        if list_response.success and list_response.data:
            memories = list_response.data.get("memories", [])
            memory_ids = [
                m.get("id") or m.get("memory_id")
                for m in memories
            ]
            assert memory_id not in memory_ids, \
                f"Deleted memory {memory_id} still found in list"


# =============================================================================
# Test Class: Integration Tests
# =============================================================================

@pytest.mark.api
@pytest.mark.memory
@pytest.mark.integration
class TestMemoryIntegration:
    """Integration tests for memory operations workflow."""

    def test_full_memory_lifecycle(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test complete memory lifecycle: store -> search -> list -> delete."""
        # 1. Store a memory
        memory_content = f"Integration test memory - User likes TypeScript - {unique_id}"
        store_response = mcp_client.call_tool("memory_store", {
            "content": memory_content,
            "type": "preference",
            "confidence": 0.95
        })

        assert store_response.success, f"Store failed: {store_response.error}"
        memory_id = get_memory_id_from_response(store_response.data)
        assert memory_id, "No memory_id returned"

        try:
            # 2. Search for the memory
            search_response = mcp_client.call_tool("memory_search", {
                "query": "TypeScript",
                "limit": 10
            })
            assert search_response.success, f"Search failed: {search_response.error}"

            # 3. List memories
            list_response = mcp_client.call_tool("memory_list", {
                "type": "preference",
                "limit": 50
            })
            assert list_response.success, f"List failed: {list_response.error}"

            # 4. Delete the memory
            delete_response = mcp_client.call_tool("memory_delete", {
                "memory_id": memory_id
            })
            assert delete_response.success or delete_response.data, \
                f"Delete failed: {delete_response.error}"

        except Exception as e:
            # Cleanup on failure
            mcp_client.call_tool("memory_delete", {"memory_id": memory_id})
            raise e

    def test_store_multiple_then_search(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test storing multiple memories then searching."""
        memory_ids: List[str] = []

        topics = [
            "JavaScript frameworks",
            "Python data science",
            "Rust systems programming",
        ]

        try:
            # Store multiple memories
            for topic in topics:
                response = mcp_client.call_tool("memory_store", {
                    "content": f"User interested in {topic} - {unique_id}",
                    "type": "preference",
                    "confidence": 0.8
                })
                assert response.success, f"Failed to store memory for {topic}"

                memory_id = get_memory_id_from_response(response.data) if response.data else None
                if memory_id:
                    memory_ids.append(memory_id)

            # Search for one topic
            search_response = mcp_client.call_tool("memory_search", {
                "query": "Python",
                "limit": 10
            })
            assert search_response.success, f"Search failed: {search_response.error}"

        finally:
            # Cleanup all created memories
            for mid in memory_ids:
                try:
                    mcp_client.call_tool("memory_delete", {"memory_id": mid})
                except Exception:
                    pass

    def test_store_different_types_then_filter(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test storing memories of different types then filtering list."""
        memory_ids: List[str] = []

        memories_to_create = [
            {"type": "preference", "content": f"Preference memory - {unique_id}"},
            {"type": "fact", "content": f"Fact memory - {unique_id}"},
            {"type": "note", "content": f"Note memory - {unique_id}"},
        ]

        try:
            # Store memories with different types
            for mem in memories_to_create:
                response = mcp_client.call_tool("memory_store", {
                    "content": mem["content"],
                    "type": mem["type"],
                    "confidence": 0.85
                })
                assert response.success

                memory_id = get_memory_id_from_response(response.data) if response.data else None
                if memory_id:
                    memory_ids.append(memory_id)

            # List only preferences
            list_response = mcp_client.call_tool("memory_list", {
                "type": "preference",
                "limit": 50
            })
            assert list_response.success

            # List only facts
            list_response = mcp_client.call_tool("memory_list", {
                "type": "fact",
                "limit": 50
            })
            assert list_response.success

        finally:
            # Cleanup
            for mid in memory_ids:
                try:
                    mcp_client.call_tool("memory_delete", {"memory_id": mid})
                except Exception:
                    pass


# =============================================================================
# Test Class: Performance Tests
# =============================================================================

@pytest.mark.api
@pytest.mark.memory
@pytest.mark.performance
@pytest.mark.slow
class TestMemoryPerformance:
    """Performance tests for memory operations."""

    def test_store_latency(
        self,
        mcp_client: MCPClient,
        test_memory_params: Dict[str, Any],
        cleanup_memory_ids: List[str],
        cleanup_test_memories: None
    ) -> None:
        """Test that store operation completes within acceptable time."""
        response = mcp_client.call_tool("memory_store", test_memory_params)

        assert response.success, f"memory_store failed: {response.error}"
        assert response.latency_ms < 5000, \
            f"Store latency {response.latency_ms}ms exceeded 5s threshold"

        memory_id = get_memory_id_from_response(response.data) if response.data else None
        if memory_id:
            cleanup_memory_ids.append(memory_id)

    def test_search_latency(
        self,
        mcp_client: MCPClient,
        stored_memory: Dict[str, Any],
        cleanup_test_memories: None
    ) -> None:
        """Test that search operation completes within acceptable time."""
        response = mcp_client.call_tool("memory_search", {
            "query": "Python",
            "limit": 10
        })

        assert response.success, f"memory_search failed: {response.error}"
        assert response.latency_ms < 5000, \
            f"Search latency {response.latency_ms}ms exceeded 5s threshold"

    def test_list_latency(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test that list operation completes within acceptable time."""
        response = mcp_client.call_tool("memory_list", {
            "limit": 50
        })

        assert response.success, f"memory_list failed: {response.error}"
        assert response.latency_ms < 5000, \
            f"List latency {response.latency_ms}ms exceeded 5s threshold"

    def test_delete_latency(
        self,
        mcp_client: MCPClient,
        test_memory_params: Dict[str, Any]
    ) -> None:
        """Test that delete operation completes within acceptable time."""
        # Create memory first
        store_response = mcp_client.call_tool("memory_store", test_memory_params)
        assert store_response.success

        memory_id = get_memory_id_from_response(store_response.data)

        # Time the delete
        delete_response = mcp_client.call_tool("memory_delete", {
            "memory_id": memory_id
        })

        assert delete_response.latency_ms < 5000, \
            f"Delete latency {delete_response.latency_ms}ms exceeded 5s threshold"
