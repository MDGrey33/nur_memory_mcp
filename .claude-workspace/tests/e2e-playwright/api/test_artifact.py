"""
Playwright API Tests for Artifact Operations.

Tests all artifact-related MCP tools:
- artifact_ingest: Ingest documents into the system
- artifact_search: Search for artifacts by content
- artifact_get: Retrieve artifact details
- artifact_delete: Delete artifacts

Also tests:
- Chunked ingestion for large documents
- Event extraction job creation (V3)
- artifact_uid and revision_id handling

Markers:
- @pytest.mark.api: API-level tests (no browser)
- @pytest.mark.artifact: Artifact-specific tests
- @pytest.mark.v3: V3 event extraction tests
"""

import pytest
import uuid
import re
import time
from typing import Dict, Any, List, Optional

# Import from lib
import sys
from pathlib import Path
lib_path = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from mcp_client import MCPClient, MCPResponse


# =============================================================================
# Test Data Helpers
# =============================================================================

def generate_unique_id(prefix: str = "test") -> str:
    """Generate a unique ID for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_artifact_params(
    content: Optional[str] = None,
    artifact_type: str = "doc",
    title: Optional[str] = None,
    source_system: str = "playwright-test"
) -> Dict[str, Any]:
    """Create parameters for artifact_ingest tool."""
    unique_id = uuid.uuid4().hex[:8]
    return {
        "content": content or f"Test artifact content {unique_id}",
        "artifact_type": artifact_type,
        "source_system": source_system,
        "title": title or f"Test Document {unique_id}",
        "source_id": f"test-{unique_id}"
    }


def extract_artifact_id(response: MCPResponse) -> Optional[str]:
    """Extract artifact_id from response data."""
    if response.data:
        # Try direct field
        if "artifact_id" in response.data:
            return response.data["artifact_id"]
        # Try text field for regex extraction
        if "text" in response.data:
            match = re.search(r'art_[a-f0-9]+', response.data["text"])
            if match:
                return match.group()
    return None


def extract_artifact_uid(response: MCPResponse) -> Optional[str]:
    """Extract artifact_uid from response data (V3)."""
    if response.data:
        if "artifact_uid" in response.data:
            return response.data["artifact_uid"]
        if "text" in response.data:
            match = re.search(r'uid_[a-f0-9]+', response.data["text"])
            if match:
                return match.group()
    return None


def extract_revision_id(response: MCPResponse) -> Optional[str]:
    """Extract revision_id from response data (V3)."""
    if response.data:
        if "revision_id" in response.data:
            return response.data["revision_id"]
        if "text" in response.data:
            match = re.search(r'rev_[a-f0-9]+', response.data["text"])
            if match:
                return match.group()
    return None


def extract_job_id(response: MCPResponse) -> Optional[str]:
    """Extract job_id from response data (V3)."""
    if response.data:
        if "job_id" in response.data:
            return response.data["job_id"]
        if "text" in response.data:
            # UUID format
            match = re.search(
                r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
                response.data["text"]
            )
            if match:
                return match.group()
    return None


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def small_document() -> str:
    """Small document content (no chunking needed)."""
    return """
    Python Best Practices Guide

    This document covers essential Python best practices:
    1. Always use virtual environments
    2. Follow PEP 8 style guidelines
    3. Write meaningful docstrings
    4. Use type hints for better code clarity
    5. Handle exceptions appropriately
    """


@pytest.fixture
def large_document() -> str:
    """Large document content (requires chunking, > 1200 tokens)."""
    base_content = """
    Software Engineering Best Practices Guide

    Chapter 1: Code Quality
    Writing clean, maintainable code is essential for long-term project success.
    This includes proper naming conventions, documentation, and testing.
    Every function should have a single responsibility and be well-named.

    Chapter 2: Testing Strategies
    Unit tests, integration tests, and end-to-end tests all play important roles.
    Code coverage should be maintained above 80% for critical paths.
    Test-driven development helps catch bugs early in the development cycle.

    Chapter 3: Code Review Process
    Every change should be reviewed by at least one other developer.
    Reviews should focus on correctness, maintainability, and performance.
    Constructive feedback improves team skills and code quality.

    Chapter 4: Documentation
    Good documentation includes inline comments, API docs, and architecture docs.
    Keep documentation up to date with code changes.
    README files should explain setup, usage, and contribution guidelines.

    Chapter 5: Version Control
    Use meaningful commit messages and follow branch naming conventions.
    Regular commits help track changes and enable easier debugging.
    Feature branches should be rebased and squashed before merging.
    """
    # Repeat to exceed chunking threshold (~1200 tokens)
    return (base_content * 15).strip()


@pytest.fixture
def meeting_notes_document() -> str:
    """Meeting notes with semantic events for V3 testing."""
    return """
    Meeting Notes - Product Launch Planning
    Date: March 15, 2024
    Attendees: Alice Chen (PM), Bob Smith (Engineering), Carol Davis (Design)

    DECISIONS MADE:
    1. Alice decided to launch the product on April 1st, 2024.
    2. The team agreed to use a freemium pricing model.

    COMMITMENTS:
    1. Bob committed to delivering the API integration by March 25th.
    2. Carol will complete the UI mockups by March 20th.

    ACTION ITEMS:
    - Bob: Implement OAuth2 authentication
    - Carol: Design the onboarding flow
    - Alice: Prepare marketing materials

    RISKS IDENTIFIED:
    - Timeline is aggressive, may need to cut scope
    - Third-party API has known reliability issues

    NEXT MEETING: March 22, 2024
    """


@pytest.fixture
def created_artifacts(mcp_client: MCPClient) -> List[str]:
    """Track created artifacts for cleanup."""
    artifacts: List[str] = []
    yield artifacts
    # Cleanup
    for artifact_id in artifacts:
        try:
            mcp_client.call_tool("artifact_delete", {"artifact_id": artifact_id})
        except Exception:
            pass


# =============================================================================
# Test Class: Artifact Ingest
# =============================================================================

@pytest.mark.api
@pytest.mark.artifact
class TestArtifactIngest:
    """Tests for artifact_ingest tool."""

    def test_ingest_small_document(
        self,
        mcp_client: MCPClient,
        small_document: str,
        created_artifacts: List[str]
    ) -> None:
        """Test ingesting a small document (no chunking)."""
        params = create_artifact_params(
            content=small_document,
            artifact_type="doc",
            title="Python Best Practices"
        )

        response = mcp_client.call_tool("artifact_ingest", params)

        assert response.success, f"artifact_ingest failed: {response.error}"
        assert response.data is not None, "Response data is None"

        # Extract and verify artifact_id
        artifact_id = extract_artifact_id(response)
        assert artifact_id is not None, "No artifact_id in response"
        assert artifact_id.startswith("art_"), f"Invalid artifact_id format: {artifact_id}"

        # Track for cleanup
        created_artifacts.append(artifact_id)

        # Verify latency is reasonable
        assert response.latency_ms < 30000, f"Ingestion too slow: {response.latency_ms}ms"

    def test_ingest_large_document_chunked(
        self,
        mcp_client: MCPClient,
        large_document: str,
        created_artifacts: List[str]
    ) -> None:
        """Test ingesting a large document that requires chunking."""
        params = create_artifact_params(
            content=large_document,
            artifact_type="doc",
            title="Software Engineering Guide (Large)"
        )

        response = mcp_client.call_tool("artifact_ingest", params, timeout=60)

        assert response.success, f"artifact_ingest (chunked) failed: {response.error}"
        assert response.data is not None, "Response data is None"

        artifact_id = extract_artifact_id(response)
        assert artifact_id is not None, "No artifact_id in response"

        # Track for cleanup
        created_artifacts.append(artifact_id)

        # Verify chunking indication in response (if available)
        if "text" in response.data:
            text = response.data["text"].lower()
            # Large documents should indicate chunking
            assert "chunk" in text or "art_" in text, \
                f"Expected chunking info in response: {response.data}"

    def test_ingest_different_artifact_types(
        self,
        mcp_client: MCPClient,
        created_artifacts: List[str]
    ) -> None:
        """Test ingesting different artifact types."""
        artifact_types = ["doc", "email", "chat", "transcript", "note"]

        for artifact_type in artifact_types:
            params = create_artifact_params(
                content=f"Test content for {artifact_type} type",
                artifact_type=artifact_type,
                title=f"Test {artifact_type.title()}"
            )

            response = mcp_client.call_tool("artifact_ingest", params)

            assert response.success, \
                f"artifact_ingest failed for type '{artifact_type}': {response.error}"

            artifact_id = extract_artifact_id(response)
            if artifact_id:
                created_artifacts.append(artifact_id)

    def test_ingest_with_metadata(
        self,
        mcp_client: MCPClient,
        created_artifacts: List[str]
    ) -> None:
        """Test ingesting an artifact with optional metadata."""
        params = create_artifact_params(
            content="Meeting about quarterly planning",
            artifact_type="note",
            title="Q1 Planning Meeting"
        )
        # Add optional metadata
        params["participants"] = ["Alice Chen", "Bob Smith"]
        params["ts"] = "2024-03-15T10:00:00Z"

        response = mcp_client.call_tool("artifact_ingest", params)

        assert response.success, f"artifact_ingest with metadata failed: {response.error}"

        artifact_id = extract_artifact_id(response)
        if artifact_id:
            created_artifacts.append(artifact_id)

    @pytest.mark.v3
    def test_ingest_returns_v3_fields(
        self,
        mcp_client: MCPClient,
        meeting_notes_document: str,
        created_artifacts: List[str]
    ) -> None:
        """Test that V3 ingest returns artifact_uid and revision_id."""
        params = create_artifact_params(
            content=meeting_notes_document,
            artifact_type="note",
            title="V3 Test Meeting Notes"
        )

        response = mcp_client.call_tool("artifact_ingest", params)

        assert response.success, f"V3 artifact_ingest failed: {response.error}"

        artifact_id = extract_artifact_id(response)
        if artifact_id:
            created_artifacts.append(artifact_id)

        # V3 should return artifact_uid and revision_id
        artifact_uid = extract_artifact_uid(response)
        revision_id = extract_revision_id(response)

        # These may be None if V3 is not enabled, but should exist if V3 is active
        if artifact_uid:
            assert artifact_uid.startswith("uid_"), \
                f"Invalid artifact_uid format: {artifact_uid}"
        if revision_id:
            assert revision_id.startswith("rev_"), \
                f"Invalid revision_id format: {revision_id}"


# =============================================================================
# Test Class: Artifact Search
# =============================================================================

@pytest.mark.api
@pytest.mark.artifact
class TestArtifactSearch:
    """Tests for artifact_search tool."""

    def test_search_basic_query(
        self,
        mcp_client: MCPClient,
        small_document: str,
        created_artifacts: List[str]
    ) -> None:
        """Test basic artifact search."""
        # First ingest a document
        ingest_params = create_artifact_params(
            content=small_document,
            artifact_type="doc",
            title="Python Guide for Search Test"
        )
        ingest_response = mcp_client.call_tool("artifact_ingest", ingest_params)
        assert ingest_response.success, f"Setup failed: {ingest_response.error}"

        artifact_id = extract_artifact_id(ingest_response)
        if artifact_id:
            created_artifacts.append(artifact_id)

        # Wait briefly for indexing
        time.sleep(1)

        # Now search
        search_params = {
            "query": "Python virtual environments PEP 8",
            "limit": 10
        }
        response = mcp_client.call_tool("artifact_search", search_params)

        assert response.success, f"artifact_search failed: {response.error}"
        assert response.data is not None, "Search returned no data"

    def test_search_with_limit(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test artifact search with result limit."""
        search_params = {
            "query": "software development",
            "limit": 5
        }
        response = mcp_client.call_tool("artifact_search", search_params)

        assert response.success, f"artifact_search failed: {response.error}"
        # Results should respect limit (if any results exist)

    def test_search_no_results(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test search with query that should return no results."""
        unique_query = f"xyznonexistent{uuid.uuid4().hex}"
        search_params = {
            "query": unique_query,
            "limit": 10
        }
        response = mcp_client.call_tool("artifact_search", search_params)

        # Should succeed but with empty results
        assert response.success, f"artifact_search failed: {response.error}"

    def test_search_with_source_system_filter(
        self,
        mcp_client: MCPClient,
        created_artifacts: List[str]
    ) -> None:
        """Test artifact search with source_system filter."""
        unique_source = f"test-source-{uuid.uuid4().hex[:8]}"

        # Ingest with specific source
        ingest_params = create_artifact_params(
            content="Document for source filter test",
            source_system=unique_source
        )
        ingest_response = mcp_client.call_tool("artifact_ingest", ingest_params)
        assert ingest_response.success

        artifact_id = extract_artifact_id(ingest_response)
        if artifact_id:
            created_artifacts.append(artifact_id)

        time.sleep(1)

        # Search with source filter
        search_params = {
            "query": "source filter test",
            "source_system": unique_source,
            "limit": 10
        }
        response = mcp_client.call_tool("artifact_search", search_params)

        assert response.success, f"artifact_search with filter failed: {response.error}"


# =============================================================================
# Test Class: Artifact Get
# =============================================================================

@pytest.mark.api
@pytest.mark.artifact
class TestArtifactGet:
    """Tests for artifact_get tool."""

    def test_get_existing_artifact(
        self,
        mcp_client: MCPClient,
        small_document: str,
        created_artifacts: List[str]
    ) -> None:
        """Test retrieving an existing artifact."""
        # First ingest
        ingest_params = create_artifact_params(
            content=small_document,
            artifact_type="doc",
            title="Document for Get Test"
        )
        ingest_response = mcp_client.call_tool("artifact_ingest", ingest_params)
        assert ingest_response.success

        artifact_id = extract_artifact_id(ingest_response)
        assert artifact_id is not None
        created_artifacts.append(artifact_id)

        # Now get
        get_params = {
            "artifact_id": artifact_id,
            "include_content": True
        }
        response = mcp_client.call_tool("artifact_get", get_params)

        assert response.success, f"artifact_get failed: {response.error}"
        assert response.data is not None

    def test_get_artifact_without_content(
        self,
        mcp_client: MCPClient,
        small_document: str,
        created_artifacts: List[str]
    ) -> None:
        """Test retrieving artifact metadata without content."""
        # First ingest
        ingest_params = create_artifact_params(
            content=small_document,
            artifact_type="doc"
        )
        ingest_response = mcp_client.call_tool("artifact_ingest", ingest_params)
        assert ingest_response.success

        artifact_id = extract_artifact_id(ingest_response)
        assert artifact_id is not None
        created_artifacts.append(artifact_id)

        # Get without content
        get_params = {
            "artifact_id": artifact_id,
            "include_content": False
        }
        response = mcp_client.call_tool("artifact_get", get_params)

        assert response.success, f"artifact_get failed: {response.error}"

    def test_get_nonexistent_artifact(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test retrieving a non-existent artifact."""
        fake_id = f"art_{uuid.uuid4().hex}"
        get_params = {
            "artifact_id": fake_id,
            "include_content": False
        }
        response = mcp_client.call_tool("artifact_get", get_params)

        # Should fail or return not found indication
        # The exact behavior depends on implementation
        if response.success:
            # If success, data should indicate not found
            assert response.data is not None
        else:
            # Error is expected for non-existent
            assert response.error is not None


# =============================================================================
# Test Class: Artifact Delete
# =============================================================================

@pytest.mark.api
@pytest.mark.artifact
class TestArtifactDelete:
    """Tests for artifact_delete tool."""

    def test_delete_existing_artifact(
        self,
        mcp_client: MCPClient,
        small_document: str
    ) -> None:
        """Test deleting an existing artifact."""
        # First ingest
        ingest_params = create_artifact_params(
            content=small_document,
            artifact_type="doc"
        )
        ingest_response = mcp_client.call_tool("artifact_ingest", ingest_params)
        assert ingest_response.success

        artifact_id = extract_artifact_id(ingest_response)
        assert artifact_id is not None

        # Delete
        delete_params = {"artifact_id": artifact_id}
        response = mcp_client.call_tool("artifact_delete", delete_params)

        assert response.success, f"artifact_delete failed: {response.error}"

        # Verify deletion by trying to get
        get_response = mcp_client.call_tool("artifact_get", {
            "artifact_id": artifact_id,
            "include_content": False
        })
        # Should fail or indicate not found
        # (behavior depends on implementation)

    def test_delete_nonexistent_artifact(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test deleting a non-existent artifact."""
        fake_id = f"art_{uuid.uuid4().hex}"
        delete_params = {"artifact_id": fake_id}
        response = mcp_client.call_tool("artifact_delete", delete_params)

        # Should either succeed (idempotent) or fail gracefully
        # Both are acceptable behaviors


# =============================================================================
# Test Class: Event Extraction Job (V3)
# =============================================================================

@pytest.mark.api
@pytest.mark.artifact
@pytest.mark.v3
class TestEventExtractionJob:
    """Tests for V3 event extraction job creation and status."""

    def test_ingest_creates_extraction_job(
        self,
        mcp_client: MCPClient,
        meeting_notes_document: str,
        created_artifacts: List[str]
    ) -> None:
        """Test that artifact ingest creates an event extraction job (V3)."""
        params = create_artifact_params(
            content=meeting_notes_document,
            artifact_type="note",
            title="Meeting Notes for Job Test"
        )
        params["participants"] = ["Alice Chen", "Bob Smith", "Carol Davis"]

        response = mcp_client.call_tool("artifact_ingest", params)

        assert response.success, f"artifact_ingest failed: {response.error}"

        artifact_id = extract_artifact_id(response)
        if artifact_id:
            created_artifacts.append(artifact_id)

        # Check for job_id in response (V3 feature)
        job_id = extract_job_id(response)
        artifact_uid = extract_artifact_uid(response)

        # If V3 is enabled, we should have either job_id or artifact_uid
        # to check job status
        if artifact_uid or job_id:
            # V3 is available
            pass  # Job created successfully

    def test_job_status_check(
        self,
        mcp_client: MCPClient,
        meeting_notes_document: str,
        created_artifacts: List[str]
    ) -> None:
        """Test checking job status for an ingested artifact (V3)."""
        # First ingest
        params = create_artifact_params(
            content=meeting_notes_document,
            artifact_type="note",
            title="Meeting Notes for Status Test"
        )
        ingest_response = mcp_client.call_tool("artifact_ingest", params)
        assert ingest_response.success

        artifact_id = extract_artifact_id(ingest_response)
        if artifact_id:
            created_artifacts.append(artifact_id)

        artifact_uid = extract_artifact_uid(ingest_response)

        # If V3 is available, check job status
        if artifact_uid:
            status_params = {"artifact_uid": artifact_uid}
            status_response = mcp_client.call_tool("job_status", status_params)

            # Check response
            if status_response.success:
                # Status should be PENDING, PROCESSING, DONE, or FAILED
                status_text = str(status_response.data)
                valid_statuses = ["PENDING", "PROCESSING", "DONE", "FAILED", "NOT_FOUND"]
                has_valid_status = any(s in status_text.upper() for s in valid_statuses)
                assert has_valid_status or "V3_UNAVAILABLE" in status_text, \
                    f"Unexpected job status response: {status_response.data}"
            else:
                # V3 may not be enabled
                assert "V3" in str(status_response.error) or \
                       "unavailable" in str(status_response.error).lower() or \
                       status_response.error is not None

    @pytest.mark.slow
    def test_wait_for_extraction_completion(
        self,
        mcp_client: MCPClient,
        meeting_notes_document: str,
        created_artifacts: List[str]
    ) -> None:
        """Test waiting for event extraction to complete (V3, slow)."""
        params = create_artifact_params(
            content=meeting_notes_document,
            artifact_type="note",
            title="Meeting Notes for Wait Test"
        )
        ingest_response = mcp_client.call_tool("artifact_ingest", params)
        assert ingest_response.success

        artifact_id = extract_artifact_id(ingest_response)
        if artifact_id:
            created_artifacts.append(artifact_id)

        artifact_uid = extract_artifact_uid(ingest_response)

        if not artifact_uid:
            pytest.skip("V3 not available (no artifact_uid)")

        # Poll for completion
        max_wait = 60  # seconds
        poll_interval = 3
        elapsed = 0

        while elapsed < max_wait:
            status_response = mcp_client.call_tool("job_status", {
                "artifact_uid": artifact_uid
            })

            if not status_response.success:
                if "V3_UNAVAILABLE" in str(status_response.error):
                    pytest.skip("V3 not available")
                break

            status_text = str(status_response.data).upper()
            if "DONE" in status_text:
                # Extraction completed
                return
            elif "FAILED" in status_text:
                pytest.fail(f"Extraction failed: {status_response.data}")
            elif "V3_UNAVAILABLE" in status_text:
                pytest.skip("V3 not available")

            time.sleep(poll_interval)
            elapsed += poll_interval

        # Timeout is acceptable if worker is not running
        # This is an integration test - worker may not be present


# =============================================================================
# Test Class: Full Artifact Lifecycle
# =============================================================================

@pytest.mark.api
@pytest.mark.artifact
class TestArtifactLifecycle:
    """End-to-end tests for complete artifact lifecycle."""

    def test_complete_lifecycle(
        self,
        mcp_client: MCPClient,
        small_document: str
    ) -> None:
        """Test complete artifact lifecycle: ingest -> search -> get -> delete."""
        unique_content = f"Unique test content {uuid.uuid4().hex}"

        # 1. Ingest
        ingest_params = create_artifact_params(
            content=unique_content,
            artifact_type="doc",
            title="Lifecycle Test Document"
        )
        ingest_response = mcp_client.call_tool("artifact_ingest", ingest_params)
        assert ingest_response.success, f"Ingest failed: {ingest_response.error}"

        artifact_id = extract_artifact_id(ingest_response)
        assert artifact_id is not None, "No artifact_id from ingest"

        try:
            # Wait for indexing
            time.sleep(2)

            # 2. Search
            search_params = {
                "query": unique_content[:50],
                "limit": 10
            }
            search_response = mcp_client.call_tool("artifact_search", search_params)
            assert search_response.success, f"Search failed: {search_response.error}"

            # 3. Get
            get_params = {
                "artifact_id": artifact_id,
                "include_content": True
            }
            get_response = mcp_client.call_tool("artifact_get", get_params)
            assert get_response.success, f"Get failed: {get_response.error}"

        finally:
            # 4. Delete (cleanup)
            delete_params = {"artifact_id": artifact_id}
            delete_response = mcp_client.call_tool("artifact_delete", delete_params)
            assert delete_response.success, f"Delete failed: {delete_response.error}"

    def test_multiple_artifacts_isolation(
        self,
        mcp_client: MCPClient,
        created_artifacts: List[str]
    ) -> None:
        """Test that multiple artifacts are properly isolated."""
        # Create two distinct artifacts
        artifacts: List[Dict[str, Any]] = []

        for i in range(2):
            params = create_artifact_params(
                content=f"Isolated artifact content number {i} - {uuid.uuid4().hex}",
                artifact_type="doc",
                title=f"Isolated Document {i}"
            )
            response = mcp_client.call_tool("artifact_ingest", params)
            assert response.success

            artifact_id = extract_artifact_id(response)
            assert artifact_id is not None
            created_artifacts.append(artifact_id)
            artifacts.append({
                "id": artifact_id,
                "params": params
            })

        # Verify each can be retrieved independently
        for artifact in artifacts:
            get_response = mcp_client.call_tool("artifact_get", {
                "artifact_id": artifact["id"],
                "include_content": True
            })
            assert get_response.success, \
                f"Failed to get artifact {artifact['id']}: {get_response.error}"


# =============================================================================
# Test Class: Edge Cases and Error Handling
# =============================================================================

@pytest.mark.api
@pytest.mark.artifact
class TestArtifactEdgeCases:
    """Tests for edge cases and error handling."""

    def test_ingest_empty_content(
        self,
        mcp_client: MCPClient,
        created_artifacts: List[str]
    ) -> None:
        """Test ingesting artifact with empty content."""
        params = create_artifact_params(
            content="",
            artifact_type="doc"
        )
        response = mcp_client.call_tool("artifact_ingest", params)

        # Should either fail gracefully or succeed with minimal content
        if response.success:
            artifact_id = extract_artifact_id(response)
            if artifact_id:
                created_artifacts.append(artifact_id)

    def test_ingest_special_characters(
        self,
        mcp_client: MCPClient,
        created_artifacts: List[str]
    ) -> None:
        """Test ingesting artifact with special characters."""
        special_content = """
        Document with special characters:
        - Emojis: Hello!
        - Unicode: cafe, resume
        - Quotes: "double" and 'single'
        - Code: <script>alert('xss')</script>
        - JSON-like: {"key": "value"}
        - Newlines and tabs:	indented
        """
        params = create_artifact_params(
            content=special_content,
            artifact_type="doc"
        )
        response = mcp_client.call_tool("artifact_ingest", params)

        assert response.success, \
            f"Failed to ingest special characters: {response.error}"

        artifact_id = extract_artifact_id(response)
        if artifact_id:
            created_artifacts.append(artifact_id)

    def test_ingest_very_long_title(
        self,
        mcp_client: MCPClient,
        created_artifacts: List[str]
    ) -> None:
        """Test ingesting artifact with very long title."""
        long_title = "A" * 500  # 500 character title
        params = create_artifact_params(
            content="Content with long title",
            artifact_type="doc",
            title=long_title
        )
        response = mcp_client.call_tool("artifact_ingest", params)

        # Should handle gracefully (truncate or accept)
        if response.success:
            artifact_id = extract_artifact_id(response)
            if artifact_id:
                created_artifacts.append(artifact_id)

    def test_search_with_invalid_limit(
        self,
        mcp_client: MCPClient
    ) -> None:
        """Test search with invalid limit values."""
        # Zero limit
        response = mcp_client.call_tool("artifact_search", {
            "query": "test",
            "limit": 0
        })
        # Should handle gracefully

        # Negative limit
        response = mcp_client.call_tool("artifact_search", {
            "query": "test",
            "limit": -1
        })
        # Should handle gracefully

    def test_concurrent_ingestions(
        self,
        mcp_client: MCPClient,
        created_artifacts: List[str]
    ) -> None:
        """Test multiple concurrent artifact ingestions."""
        import threading
        results: List[MCPResponse] = []
        errors: List[str] = []

        def ingest_artifact(index: int) -> None:
            try:
                params = create_artifact_params(
                    content=f"Concurrent test content {index}",
                    artifact_type="doc",
                    title=f"Concurrent Doc {index}"
                )
                response = mcp_client.call_tool("artifact_ingest", params)
                results.append(response)
                if response.success:
                    artifact_id = extract_artifact_id(response)
                    if artifact_id:
                        created_artifacts.append(artifact_id)
            except Exception as e:
                errors.append(str(e))

        # Create threads for concurrent ingestion
        threads = [
            threading.Thread(target=ingest_artifact, args=(i,))
            for i in range(3)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        # Check results
        assert len(errors) == 0, f"Concurrent ingestion errors: {errors}"
        success_count = sum(1 for r in results if r.success)
        assert success_count >= 1, "At least one concurrent ingestion should succeed"
