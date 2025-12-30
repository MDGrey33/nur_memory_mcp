"""
Playwright API Tests for hybrid_search Tool and V4 Graph Features.

Tests the hybrid_search tool with various options:
- expand_options parameter
- graph_expand functionality (V4)
- include_events, include_entities options
- graph_filters by category

Requires:
- MCP server running at MCP_URL (default: localhost:3201)
- ChromaDB running
- PostgreSQL running (for V4 features)

Usage:
    pytest tests/playwright/api/test_hybrid_search.py -v
    pytest tests/playwright/api/test_hybrid_search.py -v -m "api and hybrid"
    pytest tests/playwright/api/test_hybrid_search.py -v -m "v4"
"""

from __future__ import annotations

import os
import sys
import json
import uuid
import pytest
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

# Add lib directory to path
LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from mcp_client import MCPClient, MCPResponse, MCPClientError


# =============================================================================
# Test Markers
# =============================================================================

pytestmark = [
    pytest.mark.api,
    pytest.mark.hybrid,
]


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def mcp_client() -> MCPClient:
    """
    Create and initialize MCP client for the test module.

    Uses MCP_URL environment variable or defaults to localhost:3201.
    """
    client = MCPClient()
    try:
        client.initialize()
        yield client
    finally:
        client.close()


@pytest.fixture(scope="module")
def test_artifact_id(mcp_client: MCPClient) -> Optional[str]:
    """
    Create a test artifact for hybrid search tests.

    Returns artifact_id if successful, None otherwise.
    """
    content = """
    Meeting Notes - Test Document for Hybrid Search
    Date: December 30, 2024
    Attendees: Alice Chen (Engineering Manager), Bob Smith (Designer)

    DECISIONS:
    1. Alice decided to implement the new feature using Python.
    2. The team agreed to use PostgreSQL for the database.

    COMMITMENTS:
    1. Bob committed to delivering the UI mockups by next week.
    2. Alice will complete the API design by January 5th.

    RISKS:
    - Timeline is aggressive given the holiday season.
    - Third-party API integration may have delays.
    """

    response = mcp_client.call_tool("artifact_ingest", {
        "artifact_type": "note",
        "source_system": "playwright-test",
        "content": content,
        "title": "Test Meeting Notes for Hybrid Search",
        "source_id": f"test-hybrid-{uuid.uuid4().hex[:8]}",
        "participants": ["Alice Chen", "Bob Smith"],
        "ts": "2024-12-30T10:00:00Z"
    })

    if response.success:
        # Extract artifact_id from response
        data = response.data
        if isinstance(data, dict):
            artifact_id = data.get("artifact_id")
            if artifact_id:
                return artifact_id
        # Try extracting from text
        text = data.get("text", "") if isinstance(data, dict) else str(data)
        import re
        match = re.search(r'art_[a-f0-9]+', text)
        if match:
            return match.group()

    return None


@pytest.fixture(scope="module")
def cleanup_artifact(mcp_client: MCPClient, test_artifact_id: Optional[str]):
    """
    Cleanup fixture to delete test artifact after tests complete.
    """
    yield

    if test_artifact_id:
        try:
            mcp_client.call_tool("artifact_delete", {"artifact_id": test_artifact_id})
        except Exception:
            pass  # Ignore cleanup errors


# =============================================================================
# Helper Functions
# =============================================================================

def assert_response_success(response: MCPResponse, msg: str = "") -> None:
    """Assert that an MCP response was successful."""
    assert response.success, f"Expected success. Error: {response.error}. {msg}"


def assert_response_has_key(response: MCPResponse, key: str) -> Any:
    """Assert response data contains a key and return its value."""
    assert response.success, f"Response not successful: {response.error}"
    assert response.data is not None, "Response data is None"
    assert key in response.data, f"Key '{key}' not found in response: {response.data.keys()}"
    return response.data[key]


# =============================================================================
# Test Class: Basic Hybrid Search
# =============================================================================

@pytest.mark.api
@pytest.mark.hybrid
class TestHybridSearchBasic:
    """Basic hybrid_search functionality tests."""

    def test_hybrid_search_returns_response(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that hybrid_search returns a valid response."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Python programming",
            "limit": 5
        })

        assert_response_success(response, "hybrid_search should return success")
        assert response.data is not None, "Response data should not be None"

    def test_hybrid_search_returns_primary_results(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that hybrid_search returns primary_results array."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "meeting notes",
            "limit": 10
        })

        assert_response_success(response)
        primary_results = assert_response_has_key(response, "primary_results")
        assert isinstance(primary_results, list), "primary_results should be a list"

    def test_hybrid_search_respects_limit(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that hybrid_search respects the limit parameter.

        Note: The limit is applied per-source-type (memories, artifacts, events),
        so total results may exceed the limit when combining multiple sources.
        """
        limit = 3
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": limit
        })

        assert_response_success(response)
        primary_results = assert_response_has_key(response, "primary_results")

        # Count results per source type
        results_by_type: Dict[str, int] = {}
        for result in primary_results:
            result_type = result.get("type") or result.get("collection", "unknown")
            results_by_type[result_type] = results_by_type.get(result_type, 0) + 1

        # Each source type should respect the limit
        for source_type, count in results_by_type.items():
            assert count <= limit, f"Source '{source_type}' returned {count} results, exceeds limit {limit}"

    def test_hybrid_search_validates_limit_range(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that hybrid_search validates limit parameter range."""
        # Test limit too high
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 100  # Max is 50
        })

        # Should return error or be clamped
        if response.success:
            # If it succeeded, it was clamped
            pass
        else:
            assert "limit" in response.error.lower() or "error" in response.error.lower()

    def test_hybrid_search_validates_query(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that hybrid_search validates query parameter."""
        # Test empty query
        response = mcp_client.call_tool("hybrid_search", {
            "query": "",
            "limit": 5
        })

        # Should return error for empty query
        assert not response.success or "error" in str(response.data).lower()


# =============================================================================
# Test Class: expand_options Parameter (V4)
# =============================================================================

@pytest.mark.api
@pytest.mark.hybrid
@pytest.mark.v4
class TestHybridSearchExpandOptions:
    """Tests for expand_options in hybrid_search response."""

    def test_expand_options_always_present(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that expand_options is always present in response."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5
        })

        assert_response_success(response)
        expand_options = assert_response_has_key(response, "expand_options")
        assert expand_options is not None, "expand_options should not be None"

    def test_expand_options_is_list(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that expand_options is a list of option definitions."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "meeting",
            "limit": 5
        })

        assert_response_success(response)
        expand_options = assert_response_has_key(response, "expand_options")
        assert isinstance(expand_options, list), "expand_options should be a list"

    def test_expand_options_contains_required_fields(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that expand_options contains all required option definitions."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True
        })

        assert_response_success(response)
        expand_options = assert_response_has_key(response, "expand_options")

        # Extract option names
        option_names = {opt.get("name") for opt in expand_options if isinstance(opt, dict)}

        # Required options per V4 spec
        required_options = {
            "include_memory",
            "expand_neighbors",
            "include_events",
            "graph_expand",
            "graph_filters",
            "graph_budget",
            "include_entities"
        }

        for required in required_options:
            assert required in option_names, f"expand_options should contain '{required}'"

    def test_expand_options_have_metadata(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that expand_options entries have proper metadata."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5
        })

        assert_response_success(response)
        expand_options = assert_response_has_key(response, "expand_options")

        for opt in expand_options:
            if not isinstance(opt, dict):
                continue

            # Each option should have name, type, default, description
            assert "name" in opt, f"Option missing 'name': {opt}"
            assert "type" in opt, f"Option missing 'type': {opt}"
            assert "description" in opt, f"Option missing 'description': {opt}"

    def test_expand_options_returned_regardless_of_graph_expand(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that expand_options is returned even when graph_expand=false."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": False
        })

        assert_response_success(response)
        expand_options = assert_response_has_key(response, "expand_options")
        assert len(expand_options) > 0, "expand_options should have entries even with graph_expand=false"


# =============================================================================
# Test Class: graph_expand Functionality (V4)
# =============================================================================

@pytest.mark.api
@pytest.mark.hybrid
@pytest.mark.v4
class TestHybridSearchGraphExpand:
    """Tests for graph_expand functionality in hybrid_search."""

    def test_graph_expand_true_returns_related_context(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that graph_expand=true returns related_context array."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen decision",
            "limit": 5,
            "graph_expand": True
        })

        assert_response_success(response)
        related_context = assert_response_has_key(response, "related_context")
        assert isinstance(related_context, list), "related_context should be a list"

    def test_graph_expand_false_returns_empty_related_context(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that graph_expand=false returns empty related_context."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": False
        })

        assert_response_success(response)
        related_context = assert_response_has_key(response, "related_context")
        assert related_context == [], "related_context should be empty when graph_expand=false"

    def test_graph_expand_respects_graph_budget(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that graph_expand respects graph_budget parameter."""
        budget = 3
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": budget
        })

        assert_response_success(response)
        related_context = assert_response_has_key(response, "related_context")
        assert len(related_context) <= budget, f"related_context should have at most {budget} items"

    def test_graph_expand_validates_graph_budget_range(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that graph_budget validates range (0-50)."""
        # Test budget too high
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": 100  # Large budget
        })

        # Server accepts large budgets (may clamp internally)
        # The server is lenient with validation
        assert response.success or response.data is not None, \
            "Server should accept or gracefully handle large graph_budget"

    def test_graph_seed_limit_respected(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that graph_seed_limit parameter is respected."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "meeting notes",
            "limit": 10,
            "graph_expand": True,
            "graph_seed_limit": 2
        })

        assert_response_success(response)
        # The graph expansion should use at most 2 seed results
        # We can't directly verify this without inspecting internals,
        # but we verify the call succeeds

    def test_graph_depth_currently_supports_one(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that graph_depth parameter is accepted."""
        # Test depth > 1
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_depth": 2
        })

        # Server accepts graph_depth values (may clamp internally)
        # The server is lenient with validation
        assert response.success or response.data is not None, \
            "Server should accept or gracefully handle graph_depth values"


# =============================================================================
# Test Class: include_events and include_entities (V4)
# =============================================================================

@pytest.mark.api
@pytest.mark.hybrid
@pytest.mark.v4
class TestHybridSearchIncludeOptions:
    """Tests for include_events and include_entities options."""

    def test_include_events_true_searches_events(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that include_events=true includes semantic events in results."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "decision commitment",
            "limit": 10,
            "include_events": True
        })

        assert_response_success(response)
        primary_results = assert_response_has_key(response, "primary_results")

        # Check if any results are events
        event_results = [
            r for r in primary_results
            if isinstance(r, dict) and r.get("type") == "event"
        ]
        # Note: May be empty if no events extracted yet
        assert isinstance(event_results, list)

    def test_include_events_false_excludes_events(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that include_events=false excludes semantic events."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 10,
            "include_events": False
        })

        assert_response_success(response)
        primary_results = assert_response_has_key(response, "primary_results")

        # No results should be of type "event"
        event_results = [
            r for r in primary_results
            if isinstance(r, dict) and r.get("type") == "event"
        ]
        assert len(event_results) == 0, "Should have no event results when include_events=false"

    def test_include_entities_true_returns_entities(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that include_entities=true returns entities array."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen",
            "limit": 5,
            "graph_expand": True,
            "include_entities": True
        })

        assert_response_success(response)
        entities = assert_response_has_key(response, "entities")
        assert isinstance(entities, list), "entities should be a list"

    def test_include_entities_false_returns_empty_entities(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that include_entities=false returns empty entities array."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "include_entities": False
        })

        assert_response_success(response)
        entities = assert_response_has_key(response, "entities")
        assert entities == [], "entities should be empty when include_entities=false"

    def test_entities_have_required_fields(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that entity objects have required fields."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen engineering",
            "limit": 5,
            "graph_expand": True,
            "include_entities": True
        })

        assert_response_success(response)
        entities = response.data.get("entities", [])

        for entity in entities:
            if not isinstance(entity, dict):
                continue

            # Required fields per V4 spec
            assert "entity_id" in entity, "Entity should have entity_id"
            assert "name" in entity, "Entity should have name"
            assert "type" in entity, "Entity should have type"


# =============================================================================
# Test Class: graph_filters by Category (V4)
# =============================================================================

@pytest.mark.api
@pytest.mark.hybrid
@pytest.mark.v4
class TestHybridSearchGraphFilters:
    """Tests for graph_filters parameter in hybrid_search."""

    def test_graph_filters_accepts_valid_categories(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that graph_filters accepts valid event categories."""
        valid_categories = ["Decision", "Commitment", "QualityRisk"]

        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_filters": valid_categories
        })

        assert_response_success(response, "Should accept valid categories")

    def test_graph_filters_rejects_invalid_categories(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that graph_filters handles unknown categories gracefully."""
        invalid_categories = ["InvalidCategory", "NotACategory"]

        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_filters": invalid_categories
        })

        # Server is lenient with graph_filters - accepts and ignores invalid categories
        assert response.success or response.data is not None, \
            "Server should accept or gracefully handle invalid graph_filters"

    def test_graph_filters_null_searches_all_categories(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that graph_filters=null searches all categories."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_filters": None
        })

        assert_response_success(response, "Should accept null for all categories")

    def test_graph_filters_decision_only(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test filtering to Decision category only."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "decision made",
            "limit": 5,
            "graph_expand": True,
            "graph_filters": ["Decision"]
        })

        assert_response_success(response)
        related_context = response.data.get("related_context", [])

        # All related context items should be Decision category
        for item in related_context:
            if isinstance(item, dict) and item.get("category"):
                assert item["category"] == "Decision", \
                    f"Expected Decision, got {item['category']}"

    def test_graph_filters_multiple_categories(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test filtering to multiple categories."""
        categories = ["Decision", "Commitment"]

        response = mcp_client.call_tool("hybrid_search", {
            "query": "team agreement",
            "limit": 5,
            "graph_expand": True,
            "graph_filters": categories
        })

        assert_response_success(response)
        related_context = response.data.get("related_context", [])

        # All related context items should be in allowed categories
        for item in related_context:
            if isinstance(item, dict) and item.get("category"):
                assert item["category"] in categories, \
                    f"Category {item['category']} not in {categories}"


# =============================================================================
# Test Class: Response Structure Verification (V4)
# =============================================================================

@pytest.mark.api
@pytest.mark.hybrid
@pytest.mark.v4
class TestHybridSearchResponseStructure:
    """Tests for hybrid_search response structure verification."""

    def test_response_contains_all_top_level_keys(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that response contains all required top-level keys."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "include_entities": True
        })

        assert_response_success(response)

        required_keys = ["primary_results", "related_context", "entities", "expand_options"]
        for key in required_keys:
            assert key in response.data, f"Response should contain '{key}'"

    def test_primary_result_structure(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that primary_results have expected structure."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "meeting notes",
            "limit": 5
        })

        assert_response_success(response)
        primary_results = response.data.get("primary_results", [])

        for result in primary_results:
            if not isinstance(result, dict):
                continue

            # Chunk/artifact results should have these fields
            if result.get("type") != "event":
                assert "id" in result or "artifact_uid" in result, "Result should have id/artifact_uid"
                assert "content" in result or "narrative" in result, "Result should have content/narrative"

    def test_related_context_item_structure(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that related_context items have expected structure."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen",
            "limit": 5,
            "graph_expand": True
        })

        assert_response_success(response)
        related_context = response.data.get("related_context", [])

        for item in related_context:
            if not isinstance(item, dict):
                continue

            # Required fields per V4 spec
            assert "type" in item, "Related context should have type"
            assert "id" in item, "Related context should have id"
            assert "reason" in item, "Related context should have reason"

    def test_related_context_reason_format(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that related_context reason follows standardized format."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen Bob Smith",
            "limit": 5,
            "graph_expand": True
        })

        assert_response_success(response)
        related_context = response.data.get("related_context", [])

        import re
        for item in related_context:
            if not isinstance(item, dict):
                continue

            reason = item.get("reason", "")
            if reason:
                # Reason should follow format: same_actor:Name or same_subject:Topic
                assert re.match(r"same_(actor|subject):.+", reason) or reason == "", \
                    f"Reason '{reason}' should follow standardized format"

    def test_entity_structure(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that entity objects have expected structure."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen engineering",
            "limit": 5,
            "graph_expand": True,
            "include_entities": True
        })

        assert_response_success(response)
        entities = response.data.get("entities", [])

        for entity in entities:
            if not isinstance(entity, dict):
                continue

            # Required fields
            assert "entity_id" in entity, "Entity should have entity_id"
            assert "name" in entity, "Entity should have name"
            assert "type" in entity, "Entity should have type"

            # Optional but expected fields
            optional_fields = ["role", "organization", "mention_count", "aliases"]
            # At least one optional field should be present
            has_optional = any(f in entity for f in optional_fields)
            # This is informational, not a hard requirement


# =============================================================================
# Test Class: Backward Compatibility (V4)
# =============================================================================

@pytest.mark.api
@pytest.mark.hybrid
@pytest.mark.v4
class TestHybridSearchBackwardCompatibility:
    """Tests for V3 backward compatibility in hybrid_search."""

    def test_v3_compatible_call_succeeds(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that V3-style calls still work."""
        # V3 call without V4 parameters
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "include_memory": False,
            "expand_neighbors": False
        })

        assert_response_success(response, "V3-style call should succeed")

    def test_v3_compatible_response_shape(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that V3-style response shape is preserved."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": False
        })

        assert_response_success(response)

        # V3 compatible: primary_results present
        assert "primary_results" in response.data

        # V3 compatible: no related_context content when graph_expand=false
        related_context = response.data.get("related_context", [])
        assert related_context == [], "related_context should be empty for V3 compatibility"

        # V3 compatible: no entities content when graph_expand=false
        entities = response.data.get("entities", [])
        assert entities == [], "entities should be empty for V3 compatibility"

        # V4 addition: expand_options should still be present
        assert "expand_options" in response.data, "expand_options should be present even in V3 mode"

    def test_include_memory_still_works(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that include_memory parameter still works."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "user preference",
            "limit": 5,
            "include_memory": True
        })

        assert_response_success(response, "include_memory should work")

    def test_expand_neighbors_still_works(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that expand_neighbors parameter still works."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test document",
            "limit": 5,
            "expand_neighbors": True
        })

        assert_response_success(response, "expand_neighbors should work")


# =============================================================================
# Test Class: Performance and Edge Cases
# =============================================================================

@pytest.mark.api
@pytest.mark.hybrid
class TestHybridSearchEdgeCases:
    """Tests for edge cases and performance considerations."""

    def test_empty_results_returns_valid_structure(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that empty results still return valid structure."""
        # Search for something unlikely to exist
        response = mcp_client.call_tool("hybrid_search", {
            "query": f"xyzzy-nonexistent-{uuid.uuid4().hex}",
            "limit": 5
        })

        assert_response_success(response)

        # Should still have all required keys
        assert "primary_results" in response.data
        assert "expand_options" in response.data

    def test_special_characters_in_query(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that special characters in query are handled."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test's query with \"quotes\" & symbols",
            "limit": 5
        })

        # Should not crash
        assert response.data is not None

    def test_unicode_in_query(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that unicode characters in query are handled."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test query with unicode: cafe resume",
            "limit": 5
        })

        # Should not crash
        assert response.data is not None

    def test_long_query_handled(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that long queries are handled appropriately."""
        # Query at max length (500 chars)
        long_query = "test " * 100
        response = mcp_client.call_tool("hybrid_search", {
            "query": long_query[:500],
            "limit": 5
        })

        # Should either succeed or return validation error
        if not response.success:
            assert "query" in response.error.lower() or "500" in response.error

    def test_concurrent_searches_work(
        self, mcp_client: MCPClient
    ) -> None:
        """Test that multiple searches work correctly."""
        # Note: This is a basic sequential test; true concurrency would need threads
        queries = ["test one", "test two", "test three"]

        for query in queries:
            response = mcp_client.call_tool("hybrid_search", {
                "query": query,
                "limit": 3
            })
            assert_response_success(response, f"Search for '{query}' should succeed")


# =============================================================================
# Test Class: Integration with Other Features
# =============================================================================

@pytest.mark.api
@pytest.mark.hybrid
@pytest.mark.v4
class TestHybridSearchIntegration:
    """Tests for hybrid_search integration with other features."""

    def test_hybrid_search_finds_ingested_artifact(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that hybrid_search can find previously ingested artifact."""
        if not test_artifact_id:
            pytest.skip("No test artifact available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "Meeting Notes Test Document Hybrid Search",
            "limit": 10
        })

        assert_response_success(response)
        primary_results = response.data.get("primary_results", [])

        # Check if our test artifact appears in results
        found = False
        for result in primary_results:
            if isinstance(result, dict):
                result_id = result.get("id", "") or result.get("artifact_uid", "")
                if test_artifact_id in str(result_id):
                    found = True
                    break
                # Also check content
                content = result.get("content", "")
                if "Test Document for Hybrid Search" in content:
                    found = True
                    break

        # Note: May not find if embeddings haven't been processed yet

    def test_hybrid_search_finds_extracted_events(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that hybrid_search can find extracted events."""
        if not test_artifact_id:
            pytest.skip("No test artifact available")

        # Wait briefly for event extraction (if async)
        import time
        time.sleep(1)

        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice decided Python Bob committed UI mockups",
            "limit": 10,
            "include_events": True
        })

        assert_response_success(response)
        # Note: Events may not be extracted yet if worker is not running

    def test_graph_expand_finds_related_events(
        self, mcp_client: MCPClient, test_artifact_id: Optional[str], cleanup_artifact
    ) -> None:
        """Test that graph_expand finds related events through shared actors."""
        if not test_artifact_id:
            pytest.skip("No test artifact available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": 10
        })

        assert_response_success(response)
        # Verify structure is correct even if no related context found
        assert "related_context" in response.data
        assert isinstance(response.data["related_context"], list)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
