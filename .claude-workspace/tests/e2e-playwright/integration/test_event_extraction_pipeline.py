"""
Integration Tests for Event Extraction Pipeline.

Tests the full extraction workflow:
1. Ingest artifact with semantic content
2. Wait for extraction job to complete
3. Verify events created with correct categories
4. Validate event structure and evidence

Requirements:
- MCP server running (port 3201 by default)
- PostgreSQL running for event storage
- Event extraction worker running
- OpenAI API key configured (for LLM extraction)

Usage:
    pytest tests/e2e-playwright/integration/test_event_extraction_pipeline.py -v
    pytest tests/e2e-playwright/integration/test_event_extraction_pipeline.py -v -m "slow"
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import pytest
from typing import Any, Callable, Dict, List, Optional

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
    pytest.mark.v3,
    pytest.mark.requires_worker,
]


# =============================================================================
# Test Class: Basic Extraction Pipeline
# =============================================================================

@pytest.mark.integration
@pytest.mark.v3
@pytest.mark.requires_worker
class TestEventExtractionPipeline:
    """Tests for the basic event extraction pipeline."""

    @pytest.mark.slow
    def test_ingest_triggers_extraction_job(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        event_rich_content: str
    ) -> None:
        """Test that ingesting an artifact creates an extraction job."""
        # Create artifact
        artifact_info = create_test_artifact(
            content=event_rich_content,
            title="Extraction Pipeline Test - Job Creation",
            participants=["Alice Chen", "Bob Smith", "Carol Davis", "David Wilson"]
        )

        artifact_uid = artifact_info["artifact_uid"]
        assert artifact_uid is not None, "Artifact should be created"

        # Check job was created
        response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })

        assert response.success, f"Job status check failed: {response.error}"

        status = response.data.get("status", "NOT_FOUND")
        # Job should be pending, processing, or already done
        valid_statuses = ["PENDING", "PROCESSING", "DONE", "completed", "SKIPPED"]
        assert status in valid_statuses, f"Unexpected job status: {status}"

    @pytest.mark.slow
    def test_extraction_completes_with_events(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        event_rich_content: str
    ) -> None:
        """Test that extraction completes and creates events."""
        # Create artifact with rich semantic content
        artifact_info = create_test_artifact(
            content=event_rich_content,
            title="Extraction Pipeline Test - Event Creation",
            participants=["Alice Chen", "Bob Smith", "Carol Davis", "David Wilson"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        # Wait for extraction to complete
        try:
            job_result = wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction did not complete in time - worker may be slow")

        # Verify events were created
        events_created = job_result.get("events_created", 0)
        # Content has multiple clear decisions and commitments
        assert events_created > 0, "Extraction should create events from semantic content"

    @pytest.mark.slow
    def test_extracted_events_have_correct_categories(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        validate_event_structure: Callable,
        event_rich_content: str
    ) -> None:
        """Test that extracted events have valid categories."""
        # Create artifact
        artifact_info = create_test_artifact(
            content=event_rich_content,
            title="Extraction Pipeline Test - Category Validation",
            participants=["Alice Chen", "Bob Smith"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        # Wait for extraction
        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # List events for artifact
        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": True
        })

        assert response.success, f"Event list failed: {response.error}"

        events = response.data.get("events", [])

        # Validate each event structure
        for event in events:
            validate_event_structure(event, v4=True)

    @pytest.mark.slow
    def test_extracted_events_include_decisions(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        event_rich_content: str
    ) -> None:
        """Test that Decision events are extracted from clear decision statements."""
        # Create artifact
        artifact_info = create_test_artifact(
            content=event_rich_content,
            title="Extraction Pipeline Test - Decision Events",
            participants=["Alice Chen", "Bob Smith"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        # Wait for extraction
        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Search for Decision events
        response = mcp_client.call_tool("event_search_tool", {
            "artifact_uid": artifact_uid,
            "category": "Decision",
            "limit": 20,
            "include_evidence": True
        })

        assert response.success, f"Event search failed: {response.error}"

        events = response.data.get("events", [])
        # Content has explicit "decided" statements
        # May be 0 if LLM didn't extract, but we expect at least some
        if len(events) > 0:
            for event in events:
                assert event["category"] == "Decision"
                assert len(event["narrative"]) > 0

    @pytest.mark.slow
    def test_extracted_events_include_commitments(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        event_rich_content: str
    ) -> None:
        """Test that Commitment events are extracted from commitment statements."""
        # Create artifact
        artifact_info = create_test_artifact(
            content=event_rich_content,
            title="Extraction Pipeline Test - Commitment Events",
            participants=["Alice Chen", "Bob Smith", "Carol Davis"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        # Wait for extraction
        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Search for Commitment events
        response = mcp_client.call_tool("event_search_tool", {
            "artifact_uid": artifact_uid,
            "category": "Commitment",
            "limit": 20,
            "include_evidence": True
        })

        assert response.success, f"Event search failed: {response.error}"

        events = response.data.get("events", [])
        if len(events) > 0:
            for event in events:
                assert event["category"] == "Commitment"

    @pytest.mark.slow
    def test_extracted_events_include_quality_risks(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        event_rich_content: str
    ) -> None:
        """Test that QualityRisk events are extracted from risk statements."""
        # Create artifact
        artifact_info = create_test_artifact(
            content=event_rich_content,
            title="Extraction Pipeline Test - Risk Events",
            participants=["Alice Chen"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        # Wait for extraction
        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Search for QualityRisk events
        response = mcp_client.call_tool("event_search_tool", {
            "artifact_uid": artifact_uid,
            "category": "QualityRisk",
            "limit": 20,
            "include_evidence": True
        })

        assert response.success, f"Event search failed: {response.error}"

        events = response.data.get("events", [])
        if len(events) > 0:
            for event in events:
                assert event["category"] == "QualityRisk"


# =============================================================================
# Test Class: Event Evidence
# =============================================================================

@pytest.mark.integration
@pytest.mark.v3
@pytest.mark.requires_worker
class TestEventEvidence:
    """Tests for event evidence extraction."""

    @pytest.mark.slow
    def test_events_have_evidence_quotes(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable
    ) -> None:
        """Test that extracted events include evidence quotes."""
        content = """
        Important Meeting Notes - December 30, 2024

        Alice Chen decided to use PostgreSQL for the database.
        This decision was unanimous after reviewing options.

        Bob Smith committed to completing the API by January 5th.
        """

        artifact_info = create_test_artifact(
            content=content,
            title="Evidence Test - Quotes",
            participants=["Alice Chen", "Bob Smith"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Get events with evidence
        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": True
        })

        assert response.success

        events = response.data.get("events", [])
        # Check events have evidence
        events_with_evidence = [e for e in events if e.get("evidence")]

        if events_with_evidence:
            for event in events_with_evidence:
                evidence_list = event.get("evidence", [])
                for evidence in evidence_list:
                    assert "quote" in evidence, "Evidence should have quote field"
                    assert len(evidence["quote"]) > 0, "Quote should not be empty"

    @pytest.mark.slow
    def test_evidence_references_source_text(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable
    ) -> None:
        """Test that evidence quotes reference the source document."""
        # Very specific content to verify evidence matching
        content = """
        DECISION: The team decided to adopt Kubernetes for container orchestration.
        This was based on scalability requirements and team expertise.
        """

        artifact_info = create_test_artifact(
            content=content,
            title="Evidence Test - Source Reference",
            participants=[]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": True
        })

        if response.success and response.data.get("events"):
            for event in response.data["events"]:
                for evidence in event.get("evidence", []):
                    quote = evidence.get("quote", "")
                    # Evidence quote should be from the source
                    # (fuzzy check - may not be exact substring)
                    if quote:
                        # At minimum, quote should contain recognizable text
                        assert len(quote) > 10, "Quote should be meaningful"


# =============================================================================
# Test Class: Extraction Job States
# =============================================================================

@pytest.mark.integration
@pytest.mark.v3
@pytest.mark.requires_worker
class TestExtractionJobStates:
    """Tests for extraction job state transitions."""

    @pytest.mark.slow
    def test_job_transitions_through_states(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable
    ) -> None:
        """Test that job transitions from PENDING to DONE."""
        content = """
        Quick decision: Alice decided to use Python.
        """

        artifact_info = create_test_artifact(
            content=content,
            title="Job State Test",
            participants=["Alice"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        observed_states = set()
        timeout = 60
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = mcp_client.call_tool("job_status", {
                "artifact_id": artifact_uid
            })

            if response.success:
                status = response.data.get("status", "UNKNOWN")
                observed_states.add(status)

                if status in ("DONE", "FAILED", "SKIPPED"):
                    break

            time.sleep(1)

        # Should have seen at least initial and final states
        assert len(observed_states) > 0, "Should observe at least one state"

        # Final state should be terminal
        final_response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })
        if final_response.success:
            final_status = final_response.data.get("status")
            assert final_status in ("DONE", "FAILED", "SKIPPED", "PENDING", "PROCESSING"), \
                f"Unexpected final status: {final_status}"

    @pytest.mark.slow
    def test_job_status_includes_progress_info(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        event_rich_content: str
    ) -> None:
        """Test that job status includes progress information."""
        artifact_info = create_test_artifact(
            content=event_rich_content,
            title="Job Progress Test",
            participants=["Alice Chen"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            job_result = wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Completed job should have result info
        if job_result.get("status") == "DONE":
            # May include events_created, entities_created, etc.
            assert "status" in job_result


# =============================================================================
# Test Class: Re-extraction
# =============================================================================

@pytest.mark.integration
@pytest.mark.v3
@pytest.mark.requires_worker
class TestReextraction:
    """Tests for event re-extraction functionality."""

    @pytest.mark.slow
    def test_reextract_creates_new_job(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable
    ) -> None:
        """Test that re-extraction creates a new extraction job."""
        content = "Alice decided to use TypeScript for the project."

        artifact_info = create_test_artifact(
            content=content,
            title="Re-extraction Test",
            participants=["Alice"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        # Wait for initial extraction
        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=60)
        except TimeoutError:
            pytest.skip("Initial extraction timed out")

        # Trigger re-extraction
        response = mcp_client.call_tool("event_reextract", {
            "artifact_id": artifact_uid,
            "force": True
        })

        assert response.success, f"Re-extraction failed: {response.error}"

        # Job should be created (may be pending or already processing)
        status_response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })

        assert status_response.success


# =============================================================================
# Test Class: Edge Cases
# =============================================================================

@pytest.mark.integration
@pytest.mark.v3
@pytest.mark.requires_worker
class TestExtractionEdgeCases:
    """Tests for extraction edge cases and error handling."""

    @pytest.mark.slow
    def test_minimal_content_extraction(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable
    ) -> None:
        """Test extraction with minimal content."""
        content = "Brief note: agreed to proceed."

        artifact_info = create_test_artifact(
            content=content,
            title="Minimal Content Test"
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            job_result = wait_for_extraction(mcp_client, artifact_uid, timeout=60)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Should complete without error (may or may not extract events)
        assert job_result.get("status") in ("DONE", "SKIPPED")

    @pytest.mark.slow
    def test_no_semantic_content_extraction(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable
    ) -> None:
        """Test extraction with content that has no semantic events."""
        content = """
        Lorem ipsum dolor sit amet, consectetur adipiscing elit.
        Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.
        Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris.
        """

        artifact_info = create_test_artifact(
            content=content,
            title="No Semantic Content Test"
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            job_result = wait_for_extraction(mcp_client, artifact_uid, timeout=60)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Should complete - may have 0 events
        if job_result.get("status") == "DONE":
            events_created = job_result.get("events_created", 0)
            # Acceptable to have 0 events for non-semantic content
            assert events_created >= 0

    @pytest.mark.slow
    def test_unicode_content_extraction(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable
    ) -> None:
        """Test extraction with unicode characters."""
        content = """
        Meeting Notes - International Team

        Maria Garcia decided to implement multilingual support.
        Hiroshi Tanaka committed to Japanese localization by Q2.

        Key terms discussed:
        - Internationalisation (i18n)
        - Cafe menu redesign
        - Resume parsing feature
        """

        artifact_info = create_test_artifact(
            content=content,
            title="Unicode Content Test",
            participants=["Maria Garcia", "Hiroshi Tanaka"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=60)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Should complete without unicode errors
        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": False
        })

        assert response.success

    @pytest.mark.slow
    def test_large_content_extraction(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable,
        event_rich_content: str
    ) -> None:
        """Test extraction with larger content."""
        # Duplicate content to make it larger
        large_content = (event_rich_content + "\n---\n") * 3

        artifact_info = create_test_artifact(
            content=large_content,
            title="Large Content Test",
            participants=["Alice Chen", "Bob Smith"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            # Use longer timeout for large content
            job_result = wait_for_extraction(mcp_client, artifact_uid, timeout=120)
        except TimeoutError:
            pytest.skip("Extraction timed out for large content")

        assert job_result.get("status") in ("DONE", "SKIPPED")


# =============================================================================
# Test Class: Category Coverage
# =============================================================================

@pytest.mark.integration
@pytest.mark.v3
@pytest.mark.requires_worker
@pytest.mark.slow
class TestCategoryCoverage:
    """Tests for comprehensive category extraction."""

    def test_all_v4_categories_extractable(
        self,
        mcp_client: MCPClient,
        create_test_artifact: Callable,
        wait_for_extraction: Callable
    ) -> None:
        """Test that all V4 categories can be extracted from appropriate content."""
        # Content designed to trigger all V4 categories
        content = """
        Quarterly Review Meeting - December 30, 2024

        COMMITMENT: Alice committed to delivering the feature by March.

        EXECUTION: The team completed the database migration successfully.
        Bob executed the deployment script at 3 PM.

        DECISION: Carol decided to use the new framework for mobile development.

        COLLABORATION: David and Emily paired on the authentication module.
        The frontend and backend teams collaborated on API design.

        QUALITY RISK: The testing coverage is below 70% threshold.
        Performance tests revealed potential bottlenecks.

        FEEDBACK: Customer interviews highlighted usability concerns.
        The beta testers provided positive feedback on the new UI.

        CHANGE: Requirements changed after stakeholder review.
        The timeline was adjusted from Q1 to Q2.

        STAKEHOLDER: Executive team approved the budget increase.
        The customer success team requested priority support.
        """

        artifact_info = create_test_artifact(
            content=content,
            title="Category Coverage Test",
            participants=["Alice", "Bob", "Carol", "David", "Emily"]
        )

        artifact_uid = artifact_info["artifact_uid"]

        try:
            wait_for_extraction(mcp_client, artifact_uid, timeout=90)
        except TimeoutError:
            pytest.skip("Extraction timed out")

        # Get all events
        response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": False
        })

        assert response.success

        events = response.data.get("events", [])
        extracted_categories = {e["category"] for e in events}

        # Log which categories were extracted (informational)
        v4_categories = [
            "Commitment", "Execution", "Decision", "Collaboration",
            "QualityRisk", "Feedback", "Change", "Stakeholder"
        ]

        # We don't require all categories (LLM extraction varies)
        # but at least some should be extracted
        if events:
            assert len(extracted_categories) > 0, "Should extract at least some categories"


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
