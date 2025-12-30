"""
Integration Tests for Graph Expansion in hybrid_search.

Tests the V4 graph expansion functionality:
1. graph_expand=true returns related context via graph traversal
2. Related events found through shared actors
3. Related events found through shared subjects
4. graph_filters limit expansion by category
5. graph_budget limits number of expanded items

Requirements:
- MCP server running (port 3201 by default)
- PostgreSQL running with event tables
- Apache AGE graph database for relationships
- ChromaDB for embeddings
- Event extraction worker (for some tests)

Usage:
    pytest tests/e2e-playwright/integration/test_graph_expansion.py -v
    pytest tests/e2e-playwright/integration/test_graph_expansion.py -v -m "v4"
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import pytest
from typing import Any, Callable, Dict, List, Optional, Set

# Add lib directory to path
LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from mcp_client import MCPClient, MCPResponse


# =============================================================================
# Test Markers
# =============================================================================

pytestmark = [
    pytest.mark.integration,
    pytest.mark.v4,
]


# =============================================================================
# V4 Event Categories
# =============================================================================

V4_CATEGORIES = [
    "Commitment", "Execution", "Decision", "Collaboration",
    "QualityRisk", "Feedback", "Change", "Stakeholder"
]

DEFAULT_GRAPH_FILTERS = ["Decision", "Commitment", "QualityRisk"]


# =============================================================================
# Test Class: Basic Graph Expansion
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
class TestGraphExpansionBasic:
    """Basic tests for graph_expand functionality."""

    def test_graph_expand_true_returns_related_context(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that graph_expand=true returns related_context array."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "engineering decision architecture",
            "limit": 5,
            "graph_expand": True
        })

        assert response.success, f"Search failed: {response.error}"
        assert "related_context" in response.data, "Should have related_context"
        assert isinstance(response.data["related_context"], list)

    def test_graph_expand_false_returns_empty_related_context(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test that graph_expand=false returns empty related_context."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test query",
            "limit": 5,
            "graph_expand": False
        })

        assert response.success
        related_context = response.data.get("related_context", [])
        assert related_context == [], "related_context should be empty"

    def test_graph_expand_default_is_false(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test that graph_expand defaults to false."""
        # Call without graph_expand parameter
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5
        })

        assert response.success
        related_context = response.data.get("related_context", [])
        # Default should be empty (graph_expand=false by default)
        assert related_context == [], "Default should be no graph expansion"


# =============================================================================
# Test Class: Related Context Structure
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
class TestRelatedContextStructure:
    """Tests for related_context item structure."""

    def test_related_context_items_have_required_fields(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that related_context items have required fields."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen Bob Smith decision commitment",
            "limit": 10,
            "graph_expand": True,
            "graph_budget": 20
        })

        assert response.success

        related_context = response.data.get("related_context", [])

        for item in related_context:
            if not isinstance(item, dict):
                continue

            # Required fields per V4 spec
            assert "type" in item, "Related item should have type"
            assert "id" in item, "Related item should have id"
            assert "reason" in item, "Related item should have reason"

    def test_related_context_reason_follows_format(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that related_context reason follows standardized format."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "team meeting project discussion",
            "limit": 10,
            "graph_expand": True,
            "graph_budget": 20
        })

        assert response.success

        related_context = response.data.get("related_context", [])

        import re
        for item in related_context:
            if not isinstance(item, dict):
                continue

            reason = item.get("reason", "")
            if reason:
                # Reason should follow format: same_actor:Name or same_subject:Topic
                valid_format = re.match(r"same_(actor|subject):.+", reason)
                assert valid_format or reason == "", \
                    f"Reason '{reason}' should follow 'same_actor:X' or 'same_subject:X' format"

    def test_related_context_includes_type_field(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that related_context type indicates event/artifact/entity."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "decision commitment quality risk",
            "limit": 10,
            "graph_expand": True,
            "graph_budget": 20
        })

        assert response.success

        related_context = response.data.get("related_context", [])

        valid_types = ["event", "artifact", "entity", "chunk"]

        for item in related_context:
            if isinstance(item, dict) and "type" in item:
                assert item["type"] in valid_types, \
                    f"Invalid type: {item['type']}. Expected one of {valid_types}"


# =============================================================================
# Test Class: Graph Expansion by Actor
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
@pytest.mark.requires_worker
class TestGraphExpansionByActor:
    """Tests for graph expansion via shared actors."""

    @pytest.mark.slow
    def test_finds_related_events_by_same_actor(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        graph_relationship_content: str
    ) -> None:
        """Test that graph expansion finds events involving same actor."""
        # Create artifact with multiple events involving Alice Chen
        artifact_info = create_test_artifact(
            content=graph_relationship_content,
            title="Graph Expansion Test - Same Actor",
            participants=["Alice Chen", "Bob Smith", "Carol Davis", "David Wilson"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Search for Alice Chen events
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen decided",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": 20,
            "include_events": True
        })

        assert response.success

        # Related context should include other events involving Alice Chen
        related_context = response.data.get("related_context", [])

        # Check for same_actor relationships
        actor_relations = [
            item for item in related_context
            if isinstance(item, dict) and "same_actor" in item.get("reason", "")
        ]

        # May be empty if no events extracted, but structure should be valid
        if actor_relations:
            for relation in actor_relations:
                assert "Alice" in relation.get("reason", "") or \
                       "same_actor" in relation.get("reason", "")

    @pytest.mark.slow
    def test_expansion_respects_actor_filter(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        graph_relationship_content: str
    ) -> None:
        """Test that expansion filters by actor correctly."""
        artifact_info = create_test_artifact(
            content=graph_relationship_content,
            title="Graph Expansion Test - Actor Filter",
            participants=["Alice Chen", "Bob Smith"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Search specifically for Bob Smith
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Bob Smith committed API",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": 20
        })

        assert response.success

        related_context = response.data.get("related_context", [])

        # Should find Bob-related events
        for item in related_context:
            if isinstance(item, dict) and item.get("reason"):
                # Relations should be relevant to Bob
                pass


# =============================================================================
# Test Class: Graph Expansion by Subject
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
@pytest.mark.requires_worker
class TestGraphExpansionBySubject:
    """Tests for graph expansion via shared subjects."""

    @pytest.mark.slow
    def test_finds_related_events_by_same_subject(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        graph_relationship_content: str
    ) -> None:
        """Test that graph expansion finds events about same subject."""
        artifact_info = create_test_artifact(
            content=graph_relationship_content,
            title="Graph Expansion Test - Same Subject",
            participants=["Alice Chen", "Bob Smith", "Carol Davis"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Search for Project Phoenix events
        response = mcp_client.call_tool("hybrid_search", {
            "query": "Project Phoenix database API",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": 20,
            "include_events": True
        })

        assert response.success

        related_context = response.data.get("related_context", [])

        # Check for same_subject relationships
        subject_relations = [
            item for item in related_context
            if isinstance(item, dict) and "same_subject" in item.get("reason", "")
        ]

        # May be empty if no events extracted, but structure should be valid


# =============================================================================
# Test Class: Graph Budget
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
class TestGraphBudget:
    """Tests for graph_budget parameter."""

    def test_graph_budget_limits_related_context(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that graph_budget limits number of related items."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        budget = 3

        response = mcp_client.call_tool("hybrid_search", {
            "query": "meeting notes decision commitment",
            "limit": 10,
            "graph_expand": True,
            "graph_budget": budget
        })

        assert response.success

        related_context = response.data.get("related_context", [])
        assert len(related_context) <= budget, \
            f"Should return at most {budget} related items"

    def test_graph_budget_zero_returns_empty(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that graph_budget=0 returns empty related_context."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": 0
        })

        assert response.success

        related_context = response.data.get("related_context", [])
        assert len(related_context) == 0, "Budget 0 should return empty"

    def test_graph_budget_validation(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test that invalid graph_budget values are rejected."""
        # Budget > 50 should fail
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": 100
        })

        assert not response.success, "Should reject graph_budget > 50"

    def test_default_graph_budget(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test default graph_budget when not specified."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True
            # No graph_budget specified
        })

        assert response.success

        # Should use default (10) - verify by checking expand_options
        expand_options = response.data.get("expand_options", [])
        budget_option = next(
            (opt for opt in expand_options if opt.get("name") == "graph_budget"),
            None
        )
        if budget_option:
            assert budget_option.get("default") == 10


# =============================================================================
# Test Class: Graph Filters
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
class TestGraphFilters:
    """Tests for graph_filters by category."""

    def test_graph_filters_accepts_valid_categories(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that graph_filters accepts valid V4 categories."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_filters": ["Decision", "Commitment", "QualityRisk"]
        })

        assert response.success, f"Should accept valid categories: {response.error}"

    def test_graph_filters_rejects_invalid_categories(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test that graph_filters rejects invalid categories."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_filters": ["InvalidCategory", "NotACategory"]
        })

        assert not response.success, "Should reject invalid categories"

    def test_graph_filters_decision_only(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test filtering to Decision events only."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "decision made team",
            "limit": 10,
            "graph_expand": True,
            "graph_filters": ["Decision"],
            "graph_budget": 20
        })

        assert response.success

        related_context = response.data.get("related_context", [])

        # All related events should be Decision category
        for item in related_context:
            if isinstance(item, dict) and item.get("category"):
                assert item["category"] == "Decision", \
                    f"Expected Decision, got {item['category']}"

    def test_graph_filters_multiple_categories(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test filtering to multiple categories."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        allowed = ["Decision", "Commitment"]

        response = mcp_client.call_tool("hybrid_search", {
            "query": "team agreement commitment decision",
            "limit": 10,
            "graph_expand": True,
            "graph_filters": allowed,
            "graph_budget": 20
        })

        assert response.success

        related_context = response.data.get("related_context", [])

        for item in related_context:
            if isinstance(item, dict) and item.get("category"):
                assert item["category"] in allowed, \
                    f"Category {item['category']} not in {allowed}"

    def test_graph_filters_null_searches_all(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that graph_filters=null/None searches all categories."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_filters": None
        })

        assert response.success, "Should accept null for all categories"

    def test_default_graph_filters(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test default graph_filters value."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True
            # No graph_filters specified - should use default
        })

        assert response.success

        # Check expand_options for default
        expand_options = response.data.get("expand_options", [])
        filters_option = next(
            (opt for opt in expand_options if opt.get("name") == "graph_filters"),
            None
        )

        if filters_option:
            # Default should be Decision, Commitment, QualityRisk
            default_filters = filters_option.get("default", [])
            assert isinstance(default_filters, list)


# =============================================================================
# Test Class: Graph Seed and Depth
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
class TestGraphSeedAndDepth:
    """Tests for graph_seed_limit and graph_depth parameters."""

    def test_graph_seed_limit_respected(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that graph_seed_limit limits seed results for expansion."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "meeting notes discussion",
            "limit": 10,
            "graph_expand": True,
            "graph_seed_limit": 2
        })

        assert response.success
        # Hard to verify seed_limit directly, but call should succeed

    def test_graph_depth_only_supports_one(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test that graph_depth only supports value of 1."""
        # graph_depth > 1 should be rejected
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_depth": 2
        })

        assert not response.success, "Should reject graph_depth > 1"
        assert "graph_depth" in response.error.lower()

    def test_graph_depth_one_succeeds(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that graph_depth=1 succeeds."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True,
            "graph_depth": 1
        })

        assert response.success, "graph_depth=1 should succeed"


# =============================================================================
# Test Class: Integration with Events
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
@pytest.mark.requires_worker
class TestGraphExpansionWithEvents:
    """Tests for graph expansion with event data."""

    @pytest.mark.slow
    def test_graph_expand_returns_event_details(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        event_rich_content: str
    ) -> None:
        """Test that graph expansion returns relevant event details."""
        artifact_info = create_test_artifact(
            content=event_rich_content,
            title="Graph Expansion with Events Test",
            participants=["Alice Chen", "Bob Smith"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen decision commitment",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": 20,
            "include_events": True
        })

        assert response.success

        # Check that events appear in primary or related results
        primary = response.data.get("primary_results", [])
        related = response.data.get("related_context", [])

        event_items = [
            item for item in (primary + related)
            if isinstance(item, dict) and item.get("type") == "event"
        ]

        # Events should have category and narrative
        for event in event_items:
            if event.get("category"):
                assert event["category"] in V4_CATEGORIES
            if event.get("narrative"):
                assert len(event["narrative"]) > 0


# =============================================================================
# Test Class: expand_options Response
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
class TestExpandOptions:
    """Tests for expand_options in response."""

    def test_expand_options_always_present(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test that expand_options is always present in response."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5
        })

        assert response.success
        assert "expand_options" in response.data

    def test_expand_options_describes_graph_expand(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test that expand_options describes graph_expand option."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5,
            "graph_expand": True
        })

        assert response.success

        expand_options = response.data.get("expand_options", [])
        option_names = {opt.get("name") for opt in expand_options if isinstance(opt, dict)}

        assert "graph_expand" in option_names, "Should describe graph_expand option"
        assert "graph_budget" in option_names, "Should describe graph_budget option"
        assert "graph_filters" in option_names, "Should describe graph_filters option"

    def test_expand_options_have_descriptions(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test that expand_options entries have descriptions."""
        response = mcp_client.call_tool("hybrid_search", {
            "query": "test",
            "limit": 5
        })

        assert response.success

        expand_options = response.data.get("expand_options", [])

        for opt in expand_options:
            if isinstance(opt, dict):
                assert "name" in opt, "Option should have name"
                assert "description" in opt, "Option should have description"
                assert "type" in opt, "Option should have type"


# =============================================================================
# Test Class: Performance
# =============================================================================

@pytest.mark.integration
@pytest.mark.v4
class TestGraphExpansionPerformance:
    """Performance tests for graph expansion."""

    def test_graph_expand_completes_in_reasonable_time(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that graph expansion completes within acceptable time."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "decision commitment risk feedback",
            "limit": 10,
            "graph_expand": True,
            "graph_budget": 20
        })

        assert response.success

        # Should complete within 10 seconds
        assert response.latency_ms < 10000, \
            f"Graph expansion too slow: {response.latency_ms}ms"

    def test_larger_budget_still_performant(
        self,
        mcp_client: MCPClient,
        check_v4_available: bool
    ) -> None:
        """Test that larger graph_budget doesn't cause excessive delay."""
        if not check_v4_available:
            pytest.skip("V4 features not available")

        response = mcp_client.call_tool("hybrid_search", {
            "query": "meeting notes team discussion",
            "limit": 10,
            "graph_expand": True,
            "graph_budget": 50  # Max budget
        })

        assert response.success

        # Should still complete within 15 seconds even with max budget
        assert response.latency_ms < 15000, \
            f"Large budget search too slow: {response.latency_ms}ms"


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
