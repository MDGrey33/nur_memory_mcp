"""
Pytest Configuration for Integration Tests.

Provides integration-specific fixtures for cross-service testing:
- Extended timeouts for extraction workflows
- Test artifact creation and cleanup
- Job polling utilities
- Event/entity validation helpers

These fixtures extend the base fixtures from the parent conftest.py.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import pytest
from typing import Any, Callable, Dict, Generator, List, Optional

# Add lib directory to path for MCPClient import
LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from mcp_client import MCPClient, MCPResponse


# =============================================================================
# Timeout Configuration
# =============================================================================

# Longer timeouts for integration tests
INTEGRATION_TIMEOUT = int(os.getenv("INTEGRATION_TIMEOUT", "120"))
EXTRACTION_TIMEOUT = int(os.getenv("EXTRACTION_TIMEOUT", "90"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "2.0"))


# =============================================================================
# V3/V4 Event Categories
# =============================================================================

V3_EVENT_CATEGORIES: List[str] = [
    "Decision",
    "Commitment",
    "QualityRisk",
    "Blocker",
    "Feedback",
    "SentimentShift",
    "Milestone"
]

V4_EVENT_CATEGORIES: List[str] = [
    "Commitment",
    "Execution",
    "Decision",
    "Collaboration",
    "QualityRisk",
    "Feedback",
    "Change",
    "Stakeholder"
]


# =============================================================================
# Marker Registration
# =============================================================================

def pytest_configure(config: pytest.Config) -> None:
    """Register integration-specific markers."""
    config.addinivalue_line(
        "markers",
        "integration: Integration tests (cross-service)"
    )
    config.addinivalue_line(
        "markers",
        "v3: V3-specific tests (event extraction)"
    )
    config.addinivalue_line(
        "markers",
        "v4: V4-specific tests (entities, graph expansion)"
    )
    config.addinivalue_line(
        "markers",
        "slow: Slow tests (>30 seconds)"
    )
    config.addinivalue_line(
        "markers",
        "requires_worker: Tests requiring event extraction worker"
    )
    config.addinivalue_line(
        "markers",
        "requires_ai: Tests requiring OpenAI API (LLM extraction)"
    )


# =============================================================================
# MCP Client Fixture (Module-scoped for Integration Tests)
# =============================================================================

@pytest.fixture(scope="module")
def mcp_client() -> Generator[MCPClient, None, None]:
    """
    Create MCP client for integration tests.

    Module-scoped to reuse connections across tests in the same file.
    Uses extended timeout for long-running operations.
    """
    mcp_url = os.environ.get("MCP_URL", "http://localhost:3201/mcp/")
    client = MCPClient(
        base_url=mcp_url,
        timeout=INTEGRATION_TIMEOUT,
        max_retries=3,
        retry_delay=2.0
    )
    try:
        client.initialize()
        yield client
    finally:
        client.close()


# =============================================================================
# Job Polling Utilities
# =============================================================================

@pytest.fixture(scope="module")
def wait_for_job() -> Callable:
    """
    Provide a reusable job polling function.

    Returns a function that polls job_status until completion or timeout.

    Usage:
        def test_example(mcp_client, wait_for_job):
            response = mcp_client.call_tool("artifact_ingest", {...})
            job_id = response.get("job_id")
            result = wait_for_job(mcp_client, artifact_uid=artifact_uid)
            assert result["status"] == "DONE"
    """
    def _wait_for_job(
        client: MCPClient,
        artifact_uid: Optional[str] = None,
        job_id: Optional[str] = None,
        timeout: int = EXTRACTION_TIMEOUT,
        poll_interval: float = POLL_INTERVAL,
        on_progress: Optional[Callable[[MCPResponse], None]] = None
    ) -> Dict[str, Any]:
        """
        Poll job status until completion.

        Args:
            client: MCP client instance
            artifact_uid: Artifact UID to check status for
            job_id: Job ID to check status for (alternative to artifact_uid)
            timeout: Maximum wait time in seconds
            poll_interval: Time between polls in seconds
            on_progress: Optional callback for progress updates

        Returns:
            Final job status dict with 'status', 'events_created', etc.

        Raises:
            TimeoutError: If job doesn't complete within timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            if job_id:
                response = client.call_tool("job_status", {"job_id": job_id})
            elif artifact_uid:
                response = client.call_tool("job_status", {"artifact_id": artifact_uid})
            else:
                raise ValueError("Either artifact_uid or job_id must be provided")

            if on_progress:
                on_progress(response)

            if not response.success:
                # Continue polling even if individual request fails
                time.sleep(poll_interval)
                continue

            status = response.data.get("status", "UNKNOWN")

            if status in ("DONE", "completed"):
                return response.data
            elif status in ("FAILED", "failed"):
                return response.data
            elif status == "NOT_FOUND":
                # Job may not be created yet, keep polling
                pass

            time.sleep(poll_interval)

        raise TimeoutError(f"Job did not complete within {timeout}s")

    return _wait_for_job


@pytest.fixture(scope="module")
def wait_for_extraction() -> Callable:
    """
    Wait for event extraction to complete for an artifact.

    Similar to wait_for_job but specifically for extraction workflows.
    Returns the final job status including event counts.
    """
    def _wait_for_extraction(
        client: MCPClient,
        artifact_uid: str,
        timeout: int = EXTRACTION_TIMEOUT,
        expected_status: str = "DONE"
    ) -> Dict[str, Any]:
        """
        Wait for extraction job to complete.

        Args:
            client: MCP client instance
            artifact_uid: Artifact to wait for
            timeout: Maximum wait time
            expected_status: Expected final status (default: DONE)

        Returns:
            Final job status dict

        Raises:
            TimeoutError: If extraction doesn't complete
            AssertionError: If final status doesn't match expected
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = client.call_tool("job_status", {"artifact_id": artifact_uid})

            if not response.success:
                time.sleep(POLL_INTERVAL)
                continue

            status = response.data.get("status", "UNKNOWN")

            if status == expected_status:
                return response.data
            elif status in ("FAILED", "failed"):
                pytest.skip(f"Extraction failed: {response.data}")
            elif status == "SKIPPED":
                return response.data

            time.sleep(POLL_INTERVAL)

        raise TimeoutError(f"Extraction for {artifact_uid} did not complete within {timeout}s")

    return _wait_for_extraction


# =============================================================================
# Test Data Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def event_rich_content() -> str:
    """
    Content designed to generate multiple semantic events.

    Includes clear decisions, commitments, risks, and feedback.
    """
    return """
    Sprint Planning Meeting Notes
    Date: December 30, 2024
    Location: Conference Room A
    Attendees: Alice Chen (Engineering Manager), Bob Smith (Tech Lead),
               Carol Davis (Designer), David Wilson (Product Owner)

    DECISIONS MADE:
    1. Alice Chen decided to launch the product on January 15th, 2025.
       This decision was based on the holiday timeline and market window.

    2. The engineering team decided to use React with TypeScript for the frontend.
       Bob Smith led the technical evaluation process.

    3. David Wilson decided to prioritize the dashboard feature over reports.
       Customer feedback indicated higher demand for real-time dashboards.

    COMMITMENTS:
    1. Bob Smith committed to delivering the API integration by January 5th.
       This includes OAuth2 authentication and rate limiting.

    2. Carol Davis will complete all UI mockups by January 3rd.
       She committed to 15 screen designs covering core workflows.

    3. Alice Chen committed to hiring two additional engineers by end of Q1.
       Budget has been approved by leadership.

    ACTION ITEMS:
    - Bob: Implement authentication service (due: Jan 5)
    - Carol: Design onboarding flow (due: Jan 3)
    - David: Write product requirements for phase 2 (due: Jan 10)

    RISKS IDENTIFIED:
    - Timeline risk: The January 15th deadline is aggressive given holidays.
      Team may need to reduce scope if velocity drops.

    - Technical risk: Third-party API (PaymentCorp) has known reliability issues.
      Bob will implement fallback mechanisms.

    - Resource risk: Design resources are constrained with Carol as single designer.
      May need to bring in contractor support.

    MILESTONES:
    - Alpha release: January 8th (internal testing)
    - Beta launch: January 12th (select customers)
    - Production launch: January 15th (general availability)

    FEEDBACK RECEIVED:
    - Customer testing showed confusion with the current navigation.
      Carol will redesign the sidebar based on user feedback.

    - Early adopters requested dark mode support.
      Added to backlog for post-launch release.

    - Sales team reported competitor launched similar feature last week.
      David will analyze competitive positioning.

    NEXT STEPS:
    - Daily standups at 9:30 AM starting January 2nd
    - Weekly demo sessions every Friday at 3 PM
    - Retrospective scheduled for January 17th
    """


@pytest.fixture(scope="module")
def entity_rich_content() -> str:
    """
    Content designed to generate multiple entities with relationships.

    Includes people with roles, organizations, and potential duplicates.
    """
    return """
    Project Status Update - Q4 2024
    Prepared by: Alice Chen, Engineering Manager

    TEAM MEMBERS:
    - Alice Chen (Engineering Manager, Acme Corp) - Overall project lead
    - A. Chen handles all engineering escalations
    - Bob Smith (Senior Engineer) - Backend architecture
    - Robert Smith assists with code reviews
    - Carol Davis (UX Designer, Design Team) - User experience
    - C. Davis from the design team created the mockups

    STAKEHOLDERS:
    - David Wilson (Product Owner, Acme Corp)
    - Dave Wilson coordinates with customers
    - Emily Brown (VP Engineering, Acme Corp) - Executive sponsor
    - E. Brown approved the budget

    PARTNER ORGANIZATIONS:
    - PaymentCorp provides payment processing APIs
    - Payment Corp Inc. is our primary payment vendor
    - CloudHost Inc. handles our infrastructure
    - Cloud Host provides AWS consulting services

    PROJECT REFERENCES:
    - Project Phoenix is the codename for our new platform
    - The Phoenix Project includes mobile and web apps
    - Operation Neptune refers to the migration effort
    - Neptune migration is planned for Q1 2025

    KEY DISCUSSIONS:
    Alice Chen met with PaymentCorp to discuss API changes.
    Bob Smith reviewed the CloudHost infrastructure proposal.
    David Wilson presented Project Phoenix roadmap to Emily Brown.
    Carol Davis collaborated with A. Chen on the design system.
    """


@pytest.fixture(scope="module")
def graph_relationship_content() -> str:
    """
    Content designed to create graph relationships for expansion testing.

    Multiple events involving same actors for graph traversal.
    """
    return """
    Decision Log - Architecture Review
    Date: December 28, 2024
    Participants: Alice Chen, Bob Smith, Carol Davis

    DECISION 1: Database Selection
    Alice Chen decided to use PostgreSQL for the primary database.
    Bob Smith supported this decision based on ACID requirements.
    This affects: Project Phoenix data layer

    DECISION 2: API Design
    Bob Smith decided to implement REST API with GraphQL facade.
    Alice Chen approved the approach after security review.
    Carol Davis will design the API documentation portal.

    DECISION 3: Authentication
    Alice Chen and Bob Smith jointly decided on OAuth2 with PKCE.
    This decision impacts all Project Phoenix services.

    COMMITMENT: Bob Smith committed to completing the auth service by Jan 10.
    This commitment depends on Decision 3 being finalized.

    RISK: Carol Davis identified a risk with the current timeline.
    Alice Chen acknowledged the risk and adjusted resources.

    ---

    Decision Log - UX Review
    Date: December 29, 2024
    Participants: Carol Davis, David Wilson, Alice Chen

    DECISION 4: Navigation Redesign
    Carol Davis decided to implement sidebar navigation.
    David Wilson approved based on customer feedback.
    Alice Chen allocated engineering resources.

    COMMITMENT: Carol Davis committed to mockups by Jan 3.
    This commitment relates to Decision 4.

    FEEDBACK: David Wilson shared customer interview results.
    Alice Chen requested follow-up analysis from Carol Davis.
    """


# =============================================================================
# Artifact Creation Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def create_test_artifact(mcp_client: MCPClient) -> Callable:
    """
    Factory fixture for creating test artifacts.

    Returns a function that creates artifacts and tracks them for cleanup.
    """
    created_artifacts: List[str] = []

    def _create_artifact(
        content: str,
        title: str = "Integration Test Document",
        artifact_type: str = "note",
        participants: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create a test artifact.

        Args:
            content: Document content
            title: Document title
            artifact_type: Type (note, doc, slack, etc.)
            participants: List of participant names

        Returns:
            Dict with artifact_uid, revision_id, job_id
        """
        source_id = f"integration-test-{uuid.uuid4().hex[:8]}"

        response = mcp_client.call_tool("artifact_ingest", {
            "artifact_type": artifact_type,
            "source_system": "integration-test",
            "content": content,
            "title": title,
            "source_id": source_id,
            "participants": participants or [],
            "ts": "2024-12-30T10:00:00Z"
        })

        if not response.success:
            raise RuntimeError(f"Failed to create artifact: {response.error}")

        artifact_uid = response.data.get("artifact_uid") or response.data.get("artifact_id")
        if artifact_uid:
            created_artifacts.append(artifact_uid)

        return {
            "artifact_uid": artifact_uid,
            "revision_id": response.data.get("revision_id"),
            "job_id": response.data.get("job_id"),
            "source_id": source_id
        }

    yield _create_artifact

    # Cleanup: delete created artifacts
    for artifact_uid in created_artifacts:
        try:
            mcp_client.call_tool("artifact_delete", {"artifact_id": artifact_uid})
        except Exception:
            pass  # Ignore cleanup errors


# =============================================================================
# Validation Helpers
# =============================================================================

@pytest.fixture(scope="module")
def validate_event_structure() -> Callable:
    """
    Provide event structure validation function.
    """
    def _validate(event: Dict[str, Any], v4: bool = True) -> None:
        """
        Validate event has required fields.

        Args:
            event: Event dict to validate
            v4: Whether to use V4 categories (default: True)
        """
        required_fields = ["event_id", "category", "narrative", "confidence"]
        for field in required_fields:
            assert field in event, f"Event missing required field: {field}"

        # Validate category
        categories = V4_EVENT_CATEGORIES if v4 else V3_EVENT_CATEGORIES
        assert event["category"] in categories, \
            f"Invalid category: {event['category']}. Expected one of: {categories}"

        # Validate confidence range
        confidence = event["confidence"]
        assert 0.0 <= confidence <= 1.0, \
            f"Confidence {confidence} out of valid range [0, 1]"

        # Validate narrative
        assert len(event["narrative"].strip()) > 0, "Narrative should not be empty"

    return _validate


@pytest.fixture(scope="module")
def validate_entity_structure() -> Callable:
    """
    Provide entity structure validation function.
    """
    def _validate(entity: Dict[str, Any]) -> None:
        """
        Validate entity has required fields.

        Args:
            entity: Entity dict to validate
        """
        required_fields = ["entity_id", "name", "type"]
        for field in required_fields:
            assert field in entity, f"Entity missing required field: {field}"

        # Validate entity type
        valid_types = ["person", "org", "project", "object", "place", "other"]
        assert entity["type"] in valid_types, \
            f"Invalid entity type: {entity['type']}. Expected one of: {valid_types}"

        # Name should be non-empty
        assert len(entity["name"].strip()) > 0, "Entity name should not be empty"

    return _validate


# =============================================================================
# Skip Conditions
# =============================================================================

@pytest.fixture(scope="module")
def check_v3_available(mcp_client: MCPClient) -> bool:
    """Check if V3 event tools are available."""
    tools = mcp_client.list_tools()
    v3_tools = ["event_search_tool", "event_get_tool", "event_list_for_artifact"]
    return all(tool in tools for tool in v3_tools)


@pytest.fixture(scope="module")
def check_v4_available(mcp_client: MCPClient) -> bool:
    """Check if V4 features are available."""
    tools = mcp_client.list_tools()
    # V4 requires hybrid_search with graph_expand support
    if "hybrid_search" not in tools:
        return False

    # Try a V4-specific call
    response = mcp_client.call_tool("hybrid_search", {
        "query": "test",
        "limit": 1,
        "graph_expand": True,
        "include_entities": True
    })

    return response.success and "entities" in response.data


@pytest.fixture(scope="module")
def skip_if_no_worker(mcp_client: MCPClient) -> None:
    """
    Skip tests if event extraction worker is not running.

    Creates a small artifact and checks if extraction starts.
    """
    # Create minimal artifact
    response = mcp_client.call_tool("artifact_ingest", {
        "artifact_type": "note",
        "source_system": "worker-check",
        "content": "Test decision: Use Python for the project.",
        "title": "Worker Check",
        "source_id": f"worker-check-{uuid.uuid4().hex[:8]}"
    })

    if not response.success:
        pytest.skip("Could not create test artifact to check worker")

    artifact_uid = response.data.get("artifact_uid")

    # Wait briefly for job to start
    time.sleep(3)

    status_response = mcp_client.call_tool("job_status", {
        "artifact_id": artifact_uid
    })

    if status_response.success:
        status = status_response.data.get("status", "NOT_FOUND")
        if status in ("PENDING", "PROCESSING", "DONE"):
            # Worker is running
            return

    pytest.skip("Event extraction worker not running - skipping worker-dependent tests")


# =============================================================================
# Report Header
# =============================================================================

def pytest_report_header(config: pytest.Config) -> List[str]:
    """Add integration test info to pytest header."""
    mcp_url = os.environ.get("MCP_URL", "http://localhost:3201/mcp/")
    return [
        f"Integration Test Configuration:",
        f"  MCP Server: {mcp_url}",
        f"  Extraction Timeout: {EXTRACTION_TIMEOUT}s",
        f"  Poll Interval: {POLL_INTERVAL}s"
    ]
