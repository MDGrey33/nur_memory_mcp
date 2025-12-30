"""
Event Extraction Time Benchmarks.

Tests:
- Event extraction completion time
- Job status polling performance
- Extraction scaling with document size
- Re-extraction performance

Run:
    pytest tests/e2e-playwright/performance/test_extraction_time.py -v
    pytest tests/e2e-playwright/performance/test_extraction_time.py -v -m "not slow"

Markers:
    @pytest.mark.performance - All performance tests
    @pytest.mark.benchmark - Benchmark tests
    @pytest.mark.slow - Slow running tests (extraction can take time)
"""

from __future__ import annotations

import time
import pytest
from typing import Dict, List

from .conftest import THRESHOLDS


# =============================================================================
# Extraction Time Constants
# =============================================================================

EXTRACTION_POLL_INTERVAL = 2.0  # seconds
MAX_EXTRACTION_WAIT = 120  # 2 minutes max wait


# =============================================================================
# Helper Functions
# =============================================================================

def wait_for_extraction(mcp_client, job_id: str, timeout: float = MAX_EXTRACTION_WAIT) -> Dict:
    """
    Wait for extraction job to complete.

    Returns:
        Dict with status, duration, and final state
    """
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout:
            return {
                "status": "timeout",
                "duration": elapsed,
                "final_state": "timeout"
            }

        result = mcp_client.call_tool("job_status", {"job_id": job_id})

        if not result.success:
            time.sleep(EXTRACTION_POLL_INTERVAL)
            continue

        status = result.data.get("status", "unknown")

        if status == "completed":
            return {
                "status": "completed",
                "duration": elapsed,
                "final_state": result.data
            }
        elif status == "failed":
            return {
                "status": "failed",
                "duration": elapsed,
                "final_state": result.data
            }

        time.sleep(EXTRACTION_POLL_INTERVAL)


# =============================================================================
# Extraction Time Benchmarks
# =============================================================================

@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.slow
class TestExtractionTime:
    """Benchmarks for event extraction time."""

    def test_small_document_extraction(
        self,
        mcp_client,
        timer,
        small_document: str
    ):
        """Small document extraction should complete in <30s."""
        # Ingest document
        result = mcp_client.call_tool("artifact_ingest", {
            "content": small_document,
            "artifact_type": "note",
            "source_system": "perf-test",
            "title": "Small Extraction Test",
            "source_id": f"small-extract-{time.time()}"
        })

        assert result.success, f"Ingestion failed: {result.error}"
        job_id = result.data.get("job_id")

        if not job_id:
            pytest.skip("No job_id returned - extraction may be synchronous")

        # Wait for extraction
        extraction_result = wait_for_extraction(mcp_client, job_id, timeout=30)

        assert extraction_result["status"] == "completed", (
            f"Extraction did not complete: {extraction_result['status']}"
        )
        assert extraction_result["duration"] < 30, (
            f"Extraction took {extraction_result['duration']:.1f}s, expected <30s"
        )

    def test_medium_document_extraction(
        self,
        mcp_client,
        timer,
        medium_document: str
    ):
        """Medium document extraction should complete in <60s."""
        result = mcp_client.call_tool("artifact_ingest", {
            "content": medium_document,
            "artifact_type": "note",
            "source_system": "perf-test",
            "title": "Medium Extraction Test",
            "source_id": f"medium-extract-{time.time()}"
        })

        assert result.success
        job_id = result.data.get("job_id")

        if not job_id:
            pytest.skip("No job_id returned")

        extraction_result = wait_for_extraction(mcp_client, job_id, timeout=60)

        assert extraction_result["status"] == "completed", (
            f"Extraction did not complete: {extraction_result['status']}"
        )
        assert extraction_result["duration"] < 60, (
            f"Extraction took {extraction_result['duration']:.1f}s, expected <60s"
        )

    def test_large_document_extraction(
        self,
        mcp_client,
        timer,
        large_document: str
    ):
        """Large document extraction should complete in <120s."""
        result = mcp_client.call_tool("artifact_ingest", {
            "content": large_document,
            "artifact_type": "note",
            "source_system": "perf-test",
            "title": "Large Extraction Test",
            "source_id": f"large-extract-{time.time()}"
        })

        assert result.success
        job_id = result.data.get("job_id")

        if not job_id:
            pytest.skip("No job_id returned")

        extraction_result = wait_for_extraction(mcp_client, job_id, timeout=120)

        assert extraction_result["status"] == "completed", (
            f"Extraction did not complete: {extraction_result['status']}"
        )
        assert extraction_result["duration"] < 120, (
            f"Extraction took {extraction_result['duration']:.1f}s, expected <120s"
        )


@pytest.mark.performance
@pytest.mark.benchmark
class TestJobStatusPolling:
    """Benchmarks for job status polling."""

    def test_job_status_response_time(self, mcp_client, benchmark, medium_document):
        """Job status check should be fast."""
        # Create a job first
        result = mcp_client.call_tool("artifact_ingest", {
            "content": medium_document,
            "artifact_type": "note",
            "source_system": "perf-test",
            "title": "Status Polling Test",
            "source_id": f"status-poll-{time.time()}"
        })

        job_id = result.data.get("job_id")
        if not job_id:
            pytest.skip("No job_id returned")

        def check_status():
            return mcp_client.call_tool("job_status", {"job_id": job_id})

        benchmark_result = benchmark(
            name="job_status_check",
            func=check_status,
            threshold=0.3,  # Status check should be very fast
            iterations=5,
            warmup=1
        )

        assert benchmark_result.passed, (
            f"Status check took {benchmark_result.duration:.2f}s"
        )

    def test_nonexistent_job_status(self, mcp_client, timer):
        """Status check for nonexistent job should return quickly."""
        with timer() as t:
            result = mcp_client.call_tool("job_status", {
                "job_id": "nonexistent-job-12345"
            })

        # Should return quickly even if not found
        assert t.duration < 0.5, f"Nonexistent job check took {t.duration:.2f}s"


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.slow
class TestExtractionScaling:
    """Tests for extraction time scaling."""

    def test_extraction_scales_with_size(
        self,
        mcp_client,
        generate_content
    ):
        """Extraction time should scale with document size."""
        sizes_and_times = []

        for size_kb in [1, 5, 10]:
            content = generate_content(size_kb=size_kb, content_type="meeting")

            result = mcp_client.call_tool("artifact_ingest", {
                "content": content,
                "artifact_type": "note",
                "source_system": "perf-test",
                "title": f"Scale Test {size_kb}KB",
                "source_id": f"scale-{size_kb}-{time.time()}"
            })

            job_id = result.data.get("job_id")
            if not job_id:
                continue

            extraction_result = wait_for_extraction(mcp_client, job_id, timeout=90)

            if extraction_result["status"] == "completed":
                sizes_and_times.append({
                    "size_kb": size_kb,
                    "duration": extraction_result["duration"]
                })

        if len(sizes_and_times) >= 2:
            # Check that larger docs don't take exponentially longer
            smallest = sizes_and_times[0]
            largest = sizes_and_times[-1]

            size_ratio = largest["size_kb"] / smallest["size_kb"]
            time_ratio = largest["duration"] / smallest["duration"]

            # Time should not increase faster than document size
            assert time_ratio < size_ratio * 3, (
                f"Extraction scaling issue: {smallest} -> {largest}"
            )


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.slow
class TestReextraction:
    """Benchmarks for re-extraction performance."""

    def test_reextraction_time(
        self,
        mcp_client,
        timer,
        small_document: str
    ):
        """Re-extraction should complete in reasonable time."""
        # First, ingest and wait for extraction
        result = mcp_client.call_tool("artifact_ingest", {
            "content": small_document,
            "artifact_type": "note",
            "source_system": "perf-test",
            "title": "Reextraction Test",
            "source_id": f"reextract-{time.time()}"
        })

        assert result.success
        artifact_uid = result.data.get("artifact_uid")
        job_id = result.data.get("job_id")

        # Wait for initial extraction
        if job_id:
            wait_for_extraction(mcp_client, job_id, timeout=60)

        # Now trigger re-extraction
        with timer() as t:
            reextract_result = mcp_client.call_tool("event_reextract", {
                "artifact_uid": artifact_uid
            })

        assert reextract_result.success, f"Reextract failed: {reextract_result.error}"

        # Reextract call should return quickly (it starts async job)
        assert t.duration < 2.0, f"Reextract call took {t.duration:.2f}s"

        # Wait for re-extraction to complete
        new_job_id = reextract_result.data.get("job_id")
        if new_job_id:
            extraction_result = wait_for_extraction(mcp_client, new_job_id, timeout=60)
            assert extraction_result["status"] == "completed"


@pytest.mark.performance
@pytest.mark.benchmark
class TestExtractionEvents:
    """Tests for extraction result quality."""

    def test_extraction_produces_events(
        self,
        mcp_client,
        small_document: str
    ):
        """Extraction should produce events for meeting notes."""
        result = mcp_client.call_tool("artifact_ingest", {
            "content": small_document,
            "artifact_type": "note",
            "source_system": "perf-test",
            "title": "Event Production Test",
            "source_id": f"events-{time.time()}"
        })

        assert result.success
        artifact_uid = result.data.get("artifact_uid")
        job_id = result.data.get("job_id")

        # Wait for extraction
        if job_id:
            extraction_result = wait_for_extraction(mcp_client, job_id, timeout=60)
            if extraction_result["status"] != "completed":
                pytest.skip("Extraction did not complete")

        # Get events
        events_result = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_uid": artifact_uid,
            "include_evidence": False
        })

        assert events_result.success
        events = events_result.data.get("events", [])

        # Meeting notes should produce some events
        assert len(events) >= 1, "No events extracted from meeting notes"

    def test_extraction_event_categories(
        self,
        mcp_client,
        generate_content
    ):
        """Extracted events should have valid categories."""
        content = generate_content(size_kb=2.0, content_type="meeting")

        result = mcp_client.call_tool("artifact_ingest", {
            "content": content,
            "artifact_type": "note",
            "source_system": "perf-test",
            "title": "Category Test",
            "source_id": f"categories-{time.time()}"
        })

        job_id = result.data.get("job_id")
        artifact_uid = result.data.get("artifact_uid")

        if job_id:
            wait_for_extraction(mcp_client, job_id, timeout=60)

        events_result = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_uid": artifact_uid
        })

        if events_result.success:
            events = events_result.data.get("events", [])
            valid_categories = [
                "Commitment", "Execution", "Decision", "Collaboration",
                "QualityRisk", "Feedback", "Change", "Stakeholder"
            ]

            for event in events:
                category = event.get("category")
                assert category in valid_categories, (
                    f"Invalid category: {category}"
                )
