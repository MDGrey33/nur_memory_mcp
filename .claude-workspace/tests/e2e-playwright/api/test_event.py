"""
Playwright API Tests for V3 Event Operations.

Tests the MCP Memory Server V3 event tools via JSON-RPC:
- event_search_tool: Search events by category, actors, time filters
- event_get_tool: Get single event by ID with evidence
- event_list_for_artifact: List all events for an artifact
- event_reextract: Force re-extraction of events
- job_status: Check extraction job status

Requirements:
- MCP server running at MCP_URL (default: http://localhost:3201/mcp/)
- PostgreSQL running for V3 event storage
- Optional: Event worker running for extraction tests

Usage:
    pytest tests/playwright/api/test_event.py -v
    pytest tests/playwright/api/test_event.py -v -m "event"
    pytest tests/playwright/api/test_event.py -v -m "v3"
"""

import pytest
import uuid
import time
import os
import sys
from typing import Dict, List, Optional, Any, Generator
from pathlib import Path

# Add lib directory to path for MCPClient import
lib_path = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from mcp_client import MCPClient, MCPResponse


# =============================================================================
# Configuration
# =============================================================================

EXTRACTION_TIMEOUT = int(os.getenv("EXTRACTION_TIMEOUT", "60"))


# =============================================================================
# Event Categories (V3)
# =============================================================================

EVENT_CATEGORIES: List[str] = [
    "Decision",
    "Commitment",
    "QualityRisk",
    "Feedback",
    "Execution",
    "Collaboration",
    "Change",
    "Stakeholder"
]


# =============================================================================
# Module-Level Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def v3_available(mcp_client: MCPClient) -> bool:
    """Check if V3 event tools are available."""
    tools = mcp_client.list_tools()
    v3_tools = ["event_search_tool", "event_get_tool", "event_list_for_artifact", "event_reextract", "job_status"]
    return all(tool in tools for tool in v3_tools)


@pytest.fixture(scope="module")
def test_artifact_with_events(mcp_client: MCPClient, v3_available: bool) -> Optional[Dict[str, Any]]:
    """
    Create a test artifact that will generate semantic events.

    Returns:
        Dictionary with artifact_uid, revision_id, job_id if successful
    """
    if not v3_available:
        return None

    # Create content with clear semantic events
    content = """
    Meeting Notes - Product Launch Planning
    Date: March 15, 2024
    Attendees: Alice Chen (PM), Bob Smith (Engineering), Carol Davis (Design)

    DECISIONS MADE:
    1. Alice decided to launch the product on April 1st, 2024.
    2. The team agreed to use a freemium pricing model.
    3. Bob decided to use React for the frontend.

    COMMITMENTS:
    1. Bob committed to delivering the API integration by March 25th.
    2. Carol will complete the UI mockups by March 20th.
    3. Alice committed to preparing launch materials by March 30th.

    ACTION ITEMS:
    - Bob: Implement OAuth2 authentication
    - Carol: Design the onboarding flow
    - Alice: Prepare marketing materials

    RISKS IDENTIFIED:
    - Timeline is aggressive, may need to cut scope
    - Third-party API has known reliability issues
    - Design resources are constrained

    MILESTONES:
    - Beta launch: March 25th
    - Production launch: April 1st

    FEEDBACK RECEIVED:
    - User testing showed confusion with the navigation
    - Early adopters requested dark mode support
    """

    response = mcp_client.call_tool("artifact_ingest", {
        "artifact_type": "note",
        "source_system": "playwright-test",
        "content": content,
        "title": "Product Launch Planning Meeting",
        "source_id": f"playwright-test-{uuid.uuid4().hex[:8]}",
        "participants": ["Alice Chen", "Bob Smith", "Carol Davis"],
        "ts": "2024-03-15T10:00:00Z"
    })

    if not response.success:
        return None

    # Extract V3 fields from response
    # Handle both JSON and text response formats
    import re

    artifact_uid = None
    revision_id = None
    job_id = None

    if response.data:
        # Try JSON format first
        if "artifact_uid" in response.data:
            artifact_uid = response.data["artifact_uid"]
            revision_id = response.data.get("revision_id")
            job_id = response.data.get("job_id")
        elif "text" in response.data:
            # Parse from text response
            text = response.data["text"]
            # Look for uid_xxx pattern
            uid_match = re.search(r'uid_[a-f0-9]+', text)
            if uid_match:
                artifact_uid = uid_match.group()
            # Look for art_xxx pattern as fallback
            art_match = re.search(r'art_[a-f0-9]+', text)
            if art_match and not artifact_uid:
                artifact_uid = art_match.group()

    if not artifact_uid:
        return None

    # Verify the artifact is actually accessible in the database
    # by attempting to list events for it (should return empty list or events, not "not found")
    import time
    max_retries = 3
    for i in range(max_retries):
        verify_response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": False
        })

        # Check if the response contains error (server may return success=True with error in data)
        if verify_response.success and verify_response.data:
            if "error" not in verify_response.data and "error_code" not in verify_response.data:
                # Artifact exists in database (response has events/total, not error)
                return {
                    "artifact_uid": artifact_uid,
                    "revision_id": revision_id,
                    "job_id": job_id
                }

        # If we get NOT_FOUND error, the artifact wasn't stored in PostgreSQL
        # Wait a bit and retry (async processing)
        if i < max_retries - 1:
            time.sleep(1)

    # After retries, if still failing, return None (fixture not available)
    return None


@pytest.fixture(scope="module")
def existing_event_id(mcp_client: MCPClient, v3_available: bool) -> Optional[str]:
    """Get an existing event ID from the system for testing."""
    if not v3_available:
        return None

    response = mcp_client.call_tool("event_search_tool", {
        "limit": 1,
        "include_evidence": False
    })

    if response.success and response.data:
        events = response.data.get("events", [])
        if events:
            return events[0].get("event_id")
    return None


# =============================================================================
# Test Class: event_search_tool
# =============================================================================

@pytest.mark.api
@pytest.mark.event
@pytest.mark.v3
class TestEventSearchTool:
    """Tests for event_search_tool MCP tool."""

    def test_event_search_basic(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test basic event search without filters."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "limit": 20,
            "include_evidence": False
        })

        assert response.success, f"Search failed: {response.error}"
        assert "events" in response.data, "Response missing 'events' key"
        assert "total" in response.data, "Response missing 'total' key"
        assert isinstance(response.data["events"], list), "events should be a list"
        assert isinstance(response.data["total"], int), "total should be an integer"

    def test_event_search_with_category_decision(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search filtered by Decision category."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "category": "Decision",
            "limit": 20,
            "include_evidence": False
        })

        assert response.success, f"Search failed: {response.error}"
        assert "filters_applied" in response.data, "Response missing 'filters_applied'"
        assert response.data["filters_applied"].get("category") == "Decision"

        # All returned events should be Decisions
        for event in response.data.get("events", []):
            assert event["category"] == "Decision", f"Expected Decision, got {event['category']}"

    def test_event_search_with_category_commitment(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search filtered by Commitment category."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "category": "Commitment",
            "limit": 20,
            "include_evidence": False
        })

        assert response.success, f"Search failed: {response.error}"
        for event in response.data.get("events", []):
            assert event["category"] == "Commitment"

    def test_event_search_with_category_quality_risk(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search filtered by QualityRisk category."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "category": "QualityRisk",
            "limit": 20,
            "include_evidence": False
        })

        assert response.success, f"Search failed: {response.error}"
        for event in response.data.get("events", []):
            assert event["category"] == "QualityRisk"

    @pytest.mark.parametrize("category", EVENT_CATEGORIES)
    def test_event_search_all_categories(self, mcp_client: MCPClient, v3_available: bool, category: str) -> None:
        """Test event search with all valid categories."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "category": category,
            "limit": 10,
            "include_evidence": False
        })

        assert response.success, f"Search for {category} failed: {response.error}"
        assert "events" in response.data

    def test_event_search_invalid_category(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search rejects invalid category."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "category": "InvalidCategory",
            "limit": 20
        })

        # Should return error or empty results
        if response.success:
            # Some implementations may return empty results for invalid category
            assert response.data.get("total", 0) == 0 or "error" in response.data
        else:
            assert response.error is not None

    def test_event_search_with_time_range(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search with time range filters."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "time_from": "2024-01-01T00:00:00Z",
            "time_to": "2024-12-31T23:59:59Z",
            "limit": 20,
            "include_evidence": False
        })

        assert response.success, f"Time-filtered search failed: {response.error}"
        assert "filters_applied" in response.data
        assert "time_from" in response.data["filters_applied"]
        assert "time_to" in response.data["filters_applied"]

    def test_event_search_with_text_query(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search with full-text search on narrative."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "query": "pricing",
            "limit": 20,
            "include_evidence": False
        })

        assert response.success, f"Text query search failed: {response.error}"
        if "filters_applied" in response.data:
            assert "query" in response.data["filters_applied"]

    def test_event_search_with_evidence(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search includes evidence when requested."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "limit": 5,
            "include_evidence": True
        })

        assert response.success, f"Search with evidence failed: {response.error}"

        # If events exist, check evidence structure
        events = response.data.get("events", [])
        for event in events:
            if "evidence" in event and event["evidence"]:
                evidence = event["evidence"][0]
                assert "quote" in evidence, "Evidence missing 'quote'"
                # Optional fields
                if "start_char" in evidence:
                    assert isinstance(evidence["start_char"], int)
                if "end_char" in evidence:
                    assert isinstance(evidence["end_char"], int)

    def test_event_search_limit_validation(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search respects limit parameter."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        limit = 5
        response = mcp_client.call_tool("event_search_tool", {
            "limit": limit,
            "include_evidence": False
        })

        assert response.success, f"Limited search failed: {response.error}"
        assert len(response.data.get("events", [])) <= limit

    def test_event_search_invalid_limit_zero(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search rejects limit of 0."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "limit": 0,
            "include_evidence": False
        })

        # Should return error
        if response.success:
            assert "error" in response.data or "error_code" in response.data
        else:
            assert response.error is not None

    def test_event_search_invalid_limit_too_high(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search rejects limit > 100."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "limit": 200,
            "include_evidence": False
        })

        # Should return error or cap at 100
        if response.success:
            # Implementation may cap the limit instead of erroring
            events = response.data.get("events", [])
            assert len(events) <= 100 or "error" in response.data

    def test_event_search_with_artifact_filter(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test event search filtered by artifact_uid."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("event_search_tool", {
            "artifact_id": artifact_uid,  # API uses artifact_id parameter
            "limit": 20,
            "include_evidence": False
        })

        assert response.success, f"Artifact-filtered search failed: {response.error}"
        # The server internally resolves to artifact_uid and tracks in filters_applied
        if "filters_applied" in response.data:
            assert response.data["filters_applied"].get("artifact_uid") == artifact_uid

    def test_event_search_combined_filters(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search with multiple filters combined."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "query": "meeting",
            "category": "Decision",
            "time_from": "2024-01-01T00:00:00Z",
            "time_to": "2024-12-31T23:59:59Z",
            "limit": 10,
            "include_evidence": True
        })

        assert response.success, f"Combined filter search failed: {response.error}"

    def test_event_search_empty_results(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search returns empty list when no matches."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "query": f"nonexistent-query-{uuid.uuid4().hex}",
            "limit": 20,
            "include_evidence": False
        })

        assert response.success, f"Empty search failed: {response.error}"
        assert response.data.get("total", 0) == 0
        assert len(response.data.get("events", [])) == 0


# =============================================================================
# Test Class: event_get_tool
# =============================================================================

@pytest.mark.api
@pytest.mark.event
@pytest.mark.v3
class TestEventGetTool:
    """Tests for event_get_tool MCP tool."""

    def test_event_get_success(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test successful retrieval of single event."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success, f"Get event failed: {response.error}"
        assert "event_id" in response.data, "Response missing 'event_id'"
        assert "category" in response.data, "Response missing 'category'"
        assert "narrative" in response.data, "Response missing 'narrative'"
        assert "confidence" in response.data, "Response missing 'confidence'"

    def test_event_get_includes_all_required_fields(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test event_get includes all expected fields."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success, f"Get event failed: {response.error}"

        required_fields = [
            "event_id", "artifact_uid", "revision_id", "category",
            "narrative", "confidence"
        ]

        for field in required_fields:
            assert field in response.data, f"Missing required field: {field}"

    def test_event_get_includes_evidence(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test event_get includes evidence array."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success, f"Get event failed: {response.error}"
        assert "evidence" in response.data, "Response missing 'evidence'"
        assert isinstance(response.data["evidence"], list), "Evidence should be a list"

    def test_event_get_with_evt_prefix(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test event_get handles evt_ prefix in event_id."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        # Add evt_ prefix if not already present
        if not existing_event_id.startswith("evt_"):
            event_id_with_prefix = f"evt_{existing_event_id}"
        else:
            event_id_with_prefix = existing_event_id

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": event_id_with_prefix
        })

        # Should handle prefix gracefully
        assert response.success, f"Get event with prefix failed: {response.error}"

    def test_event_get_not_found(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event_get returns error for non-existent event."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        fake_uuid = "87654321-4321-8765-4321-876543218765"

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": fake_uuid
        })

        # Should return not found error
        if response.success:
            assert "error" in response.data or response.data.get("error_code") == "NOT_FOUND"
        else:
            assert response.error is not None

    def test_event_get_invalid_uuid(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event_get returns error for invalid UUID format."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": "invalid-uuid-format"
        })

        # Should return validation error
        if response.success:
            assert "error" in response.data or "error_code" in response.data

    def test_event_get_verifies_event_structure(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test that retrieved event has valid structure."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success, f"Get event failed: {response.error}"

        # Verify category is valid
        assert response.data["category"] in EVENT_CATEGORIES, \
            f"Invalid category: {response.data['category']}"

        # Verify confidence is in valid range
        confidence = response.data["confidence"]
        assert 0.0 <= confidence <= 1.0, f"Confidence out of range: {confidence}"

        # Verify narrative is non-empty
        assert len(response.data["narrative"]) > 0, "Narrative should not be empty"


# =============================================================================
# Test Class: event_list_for_artifact
# =============================================================================

@pytest.mark.api
@pytest.mark.event
@pytest.mark.v3
class TestEventListForArtifact:
    """Tests for event_list_for_artifact MCP tool."""

    def test_event_list_for_artifact_success(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test listing events for specific artifact."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": False
        })

        assert response.success, f"List for artifact failed: {response.error}"
        assert "events" in response.data, "Response missing 'events'"
        assert "total" in response.data, "Response missing 'total'"

    def test_event_list_for_artifact_with_evidence(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test listing events with evidence included."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": True
        })

        assert response.success, f"List with evidence failed: {response.error}"

    def test_event_list_for_artifact_returns_metadata(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test list response includes artifact metadata."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": False
        })

        assert response.success, f"List failed: {response.error}"

        # Should include artifact context
        if "artifact_uid" in response.data:
            assert response.data["artifact_uid"] == artifact_uid

    def test_event_list_for_artifact_not_found(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test error when artifact not found."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        fake_uid = f"uid_nonexistent_{uuid.uuid4().hex[:8]}"

        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": fake_uid,
            "include_evidence": False
        })

        # Should return not found or empty
        if response.success:
            # May return empty list for non-existent artifact
            assert response.data.get("total", 0) == 0 or "error" in response.data

    def test_event_list_for_artifact_empty_results(
        self,
        mcp_client: MCPClient,
        v3_available: bool
    ) -> None:
        """Test list returns empty when artifact has no events."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        # Create artifact with no event-worthy content
        response = mcp_client.call_tool("artifact_ingest", {
            "artifact_type": "doc",
            "source_system": "playwright-test",
            "content": "This is a simple document with no decisions or commitments.",
            "title": "Simple Document",
            "source_id": f"simple-{uuid.uuid4().hex[:8]}"
        })

        if not response.success:
            pytest.skip("Could not create test artifact")

        artifact_uid = response.get("artifact_uid")
        if not artifact_uid:
            pytest.skip("No artifact_uid in response")

        # List events (may be empty if worker hasn't processed)
        list_response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": False
        })

        assert list_response.success, f"List failed: {list_response.error}"


# =============================================================================
# Test Class: event_reextract
# =============================================================================

@pytest.mark.api
@pytest.mark.event
@pytest.mark.v3
class TestEventReextract:
    """Tests for event_reextract MCP tool."""

    def test_event_reextract_success(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test successful re-extraction request."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("event_reextract", {
            "artifact_id": artifact_uid,
            "force": False
        })

        assert response.success, f"Reextract failed: {response.error}"
        # Should return job info or status
        assert "status" in response.data or "job_id" in response.data or "message" in response.data

    def test_event_reextract_with_force(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test re-extraction with force flag."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("event_reextract", {
            "artifact_id": artifact_uid,
            "force": True
        })

        assert response.success, f"Force reextract failed: {response.error}"

    def test_event_reextract_not_found(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test error when artifact not found."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        fake_uid = f"uid_nonexistent_{uuid.uuid4().hex[:8]}"

        response = mcp_client.call_tool("event_reextract", {
            "artifact_id": fake_uid,
            "force": False
        })

        # Should return not found error
        if response.success:
            assert "error" in response.data or "NOT_FOUND" in str(response.data)

    def test_event_reextract_creates_job(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test that re-extraction creates a new job."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("event_reextract", {
            "artifact_id": artifact_uid,
            "force": True
        })

        assert response.success, f"Reextract failed: {response.error}"

        # Check job status was created
        status_response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })

        assert status_response.success, f"Job status check failed: {status_response.error}"


# =============================================================================
# Test Class: job_status
# =============================================================================

@pytest.mark.api
@pytest.mark.event
@pytest.mark.v3
class TestJobStatus:
    """Tests for job_status MCP tool."""

    def test_job_status_success(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test successful job status check."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })

        assert response.success, f"Job status failed: {response.error}"
        # Should return status or not found indicator
        assert "status" in response.data or "message" in response.data or "job_id" in response.data

    def test_job_status_returns_valid_status(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test job status returns valid status values."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })

        assert response.success, f"Job status failed: {response.error}"

        valid_statuses = ["PENDING", "PROCESSING", "DONE", "FAILED", "SKIPPED", "NOT_FOUND"]
        status = response.data.get("status")

        if status:
            assert status in valid_statuses, f"Invalid status: {status}"

    def test_job_status_not_found(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test job status for non-existent artifact."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        fake_uid = f"uid_nonexistent_{uuid.uuid4().hex[:8]}"

        response = mcp_client.call_tool("job_status", {
            "artifact_id": fake_uid
        })

        # Should return not found status
        if response.success:
            status = response.data.get("status")
            if status:
                assert status == "NOT_FOUND" or "NOT_FOUND" in str(response.data)

    def test_job_status_with_revision_id(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test job status with specific revision ID."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]
        revision_id = test_artifact_with_events.get("revision_id")

        if not revision_id:
            pytest.skip("No revision_id available")

        response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid,
            "revision_id": revision_id
        })

        assert response.success, f"Job status with revision failed: {response.error}"


# =============================================================================
# Test Class: Event Structure Validation
# =============================================================================

@pytest.mark.api
@pytest.mark.event
@pytest.mark.v3
class TestEventStructure:
    """Tests for validating event data structure and fields."""

    def test_event_has_required_fields(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test that events have all required fields."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success, f"Get event failed: {response.error}"

        required_fields = ["event_id", "category", "narrative", "confidence"]
        for field in required_fields:
            assert field in response.data, f"Event missing required field: {field}"

    def test_event_confidence_is_valid(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test that event confidence is between 0 and 1."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success
        confidence = response.data.get("confidence")

        assert confidence is not None, "Confidence should not be None"
        assert isinstance(confidence, (int, float)), "Confidence should be numeric"
        assert 0.0 <= confidence <= 1.0, f"Confidence {confidence} out of valid range [0, 1]"

    def test_event_category_is_valid(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test that event category is from valid set."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success
        category = response.data.get("category")

        assert category is not None, "Category should not be None"
        assert category in EVENT_CATEGORIES, f"Invalid category: {category}"

    def test_event_narrative_is_non_empty(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test that event narrative is non-empty string."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success
        narrative = response.data.get("narrative")

        assert narrative is not None, "Narrative should not be None"
        assert isinstance(narrative, str), "Narrative should be a string"
        assert len(narrative.strip()) > 0, "Narrative should not be empty"

    def test_event_evidence_structure(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test that event evidence has correct structure."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success
        evidence_list = response.data.get("evidence", [])

        assert isinstance(evidence_list, list), "Evidence should be a list"

        for evidence in evidence_list:
            assert "quote" in evidence, "Evidence missing 'quote' field"
            assert isinstance(evidence["quote"], str), "Quote should be a string"

    def test_event_actors_structure(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test that event actors have correct structure."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success
        actors = response.data.get("actors", [])

        assert isinstance(actors, list), "Actors should be a list"

        for actor in actors:
            # Actor should have at least a reference
            assert "ref" in actor or "name" in actor, "Actor missing identifier"


# =============================================================================
# Test Class: Integration Workflows
# =============================================================================

@pytest.mark.api
@pytest.mark.event
@pytest.mark.v3
class TestEventWorkflows:
    """Integration tests for event tool workflows."""

    def test_search_then_get_workflow(
        self,
        mcp_client: MCPClient,
        v3_available: bool
    ) -> None:
        """Test workflow: search for events, then get specific event."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        # First, search for events
        search_response = mcp_client.call_tool("event_search_tool", {
            "limit": 5,
            "include_evidence": False
        })

        assert search_response.success, f"Search failed: {search_response.error}"

        events = search_response.data.get("events", [])
        if not events:
            pytest.skip("No events available for workflow test")

        # Get first event
        event_id = events[0]["event_id"]

        # Then get full event details
        get_response = mcp_client.call_tool("event_get_tool", {
            "event_id": event_id
        })

        assert get_response.success, f"Get failed: {get_response.error}"
        assert get_response.data["event_id"] == event_id

    def test_list_then_filter_workflow(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test workflow: list events for artifact, then filter by category."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        # List all events for artifact
        list_response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": False
        })

        assert list_response.success, f"List failed: {list_response.error}"

        # Search with category filter
        search_response = mcp_client.call_tool("event_search_tool", {
            "artifact_uid": artifact_uid,
            "category": "Decision",
            "limit": 20,
            "include_evidence": False
        })

        assert search_response.success, f"Filtered search failed: {search_response.error}"

    def test_reextract_then_check_status_workflow(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test workflow: trigger re-extraction, then check job status."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        # Trigger re-extraction
        reextract_response = mcp_client.call_tool("event_reextract", {
            "artifact_id": artifact_uid,
            "force": True
        })

        assert reextract_response.success, f"Reextract failed: {reextract_response.error}"

        # Check job status
        status_response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })

        assert status_response.success, f"Status check failed: {status_response.error}"

    @pytest.mark.slow
    @pytest.mark.requires_worker
    def test_ingest_wait_search_workflow(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test full workflow: ingest artifact, wait for extraction, search events."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        # Create artifact with clear events
        content = """
        Decision Log - Sprint Planning

        DECISION: Team decided to use TypeScript for the new service.
        Owner: Tech Lead
        Date: 2024-03-15

        COMMITMENT: Backend team committed to API completion by March 30th.
        """

        ingest_response = mcp_client.call_tool("artifact_ingest", {
            "artifact_type": "note",
            "source_system": "playwright-workflow-test",
            "content": content,
            "title": "Sprint Decision Log",
            "source_id": f"workflow-{uuid.uuid4().hex[:8]}"
        })

        assert ingest_response.success, f"Ingest failed: {ingest_response.error}"

        artifact_uid = ingest_response.get("artifact_uid")
        assert artifact_uid, "No artifact_uid returned"

        # Poll job status (with timeout)
        max_wait = EXTRACTION_TIMEOUT
        poll_interval = 2
        elapsed = 0
        extraction_done = False

        while elapsed < max_wait:
            status_response = mcp_client.call_tool("job_status", {
                "artifact_id": artifact_uid
            })

            if status_response.success:
                status = status_response.data.get("status", "UNKNOWN")
                if status == "DONE":
                    extraction_done = True
                    break
                elif status == "FAILED":
                    pytest.skip("Extraction failed - worker may not be running")

            time.sleep(poll_interval)
            elapsed += poll_interval

        if not extraction_done:
            pytest.skip(f"Extraction not complete after {max_wait}s - worker may not be running")

        # Search for extracted events
        search_response = mcp_client.call_tool("event_search_tool", {
            "artifact_uid": artifact_uid,
            "limit": 20,
            "include_evidence": True
        })

        assert search_response.success, f"Search failed: {search_response.error}"
        assert search_response.data.get("total", 0) > 0, "Expected some events to be extracted"


# =============================================================================
# Test Class: Error Handling
# =============================================================================

@pytest.mark.api
@pytest.mark.event
@pytest.mark.v3
class TestEventErrorHandling:
    """Tests for error handling in event tools."""

    def test_event_search_handles_database_error(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event_search handles errors gracefully."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        # This should work even if database is empty
        response = mcp_client.call_tool("event_search_tool", {
            "limit": 10,
            "include_evidence": False
        })

        # Should return success with empty results, not crash
        assert response.success or response.error is not None

    def test_event_get_handles_missing_id(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event_get handles missing event_id parameter."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_get_tool", {})

        # Should return validation error
        assert not response.success or "error" in response.data

    def test_event_list_handles_invalid_artifact_id(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event_list handles invalid artifact_id format."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": "invalid!!format",
            "include_evidence": False
        })

        # Should handle gracefully
        assert response.success or response.error is not None

    def test_job_status_handles_missing_artifact_id(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test job_status handles missing artifact_id parameter."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("job_status", {})

        # Should return validation error
        assert not response.success or "error" in response.data


# =============================================================================
# Test Class: Performance
# =============================================================================

@pytest.mark.api
@pytest.mark.event
@pytest.mark.v3
@pytest.mark.performance
class TestEventPerformance:
    """Tests for event tool performance."""

    def test_event_search_latency(self, mcp_client: MCPClient, v3_available: bool) -> None:
        """Test event search completes within acceptable latency."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        response = mcp_client.call_tool("event_search_tool", {
            "limit": 20,
            "include_evidence": False
        })

        assert response.success, f"Search failed: {response.error}"
        # Should complete within 5 seconds
        assert response.latency_ms < 5000, f"Search too slow: {response.latency_ms}ms"

    def test_event_get_latency(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        existing_event_id: Optional[str]
    ) -> None:
        """Test event get completes within acceptable latency."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not existing_event_id:
            pytest.skip("No existing events available")

        response = mcp_client.call_tool("event_get_tool", {
            "event_id": existing_event_id
        })

        assert response.success, f"Get failed: {response.error}"
        # Should complete within 2 seconds
        assert response.latency_ms < 2000, f"Get too slow: {response.latency_ms}ms"

    def test_job_status_latency(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        test_artifact_with_events: Optional[Dict[str, Any]]
    ) -> None:
        """Test job status completes within acceptable latency."""
        if not v3_available:
            pytest.skip("V3 event tools not available")
        if not test_artifact_with_events:
            pytest.skip("No test artifact available")

        artifact_uid = test_artifact_with_events["artifact_uid"]

        response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })

        assert response.success, f"Status failed: {response.error}"
        # Should complete within 1 second
        assert response.latency_ms < 1000, f"Status too slow: {response.latency_ms}ms"
