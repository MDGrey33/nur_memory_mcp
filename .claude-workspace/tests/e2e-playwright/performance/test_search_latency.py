"""
Search Latency Benchmarks.

Tests:
- Memory search latency
- Artifact search latency
- Hybrid search latency
- Search with filters
- Search scaling with database size

Run:
    pytest tests/e2e-playwright/performance/test_search_latency.py -v
    pytest tests/e2e-playwright/performance/test_search_latency.py -v -m "not slow"

Markers:
    @pytest.mark.performance - All performance tests
    @pytest.mark.benchmark - Benchmark tests
    @pytest.mark.slow - Slow running tests
"""

from __future__ import annotations

import time
import pytest
from typing import Dict, List

from .conftest import THRESHOLDS


# =============================================================================
# Memory Search Benchmarks
# =============================================================================

@pytest.mark.performance
@pytest.mark.benchmark
class TestMemorySearchLatency:
    """Benchmarks for memory search latency."""

    def test_simple_memory_search(self, mcp_client, benchmark):
        """Simple memory search should complete in <0.5s."""
        def search():
            return mcp_client.call_tool("memory_search", {
                "query": "programming language preference",
                "limit": 10
            })

        result = benchmark(
            name="memory_search",
            func=search,
            threshold=THRESHOLDS["memory_search"],
            iterations=5,
            warmup=1
        )

        assert result.passed, (
            f"Memory search took {result.duration:.2f}s, "
            f"threshold is {result.threshold:.2f}s"
        )

    def test_memory_search_with_type_filter(self, mcp_client, benchmark):
        """Memory search with type filter."""
        def search():
            return mcp_client.call_tool("memory_search", {
                "query": "user preference",
                "type": "preference",
                "limit": 10
            })

        result = benchmark(
            name="memory_search_filtered",
            func=search,
            threshold=0.6,  # Slightly higher for filtered
            iterations=5,
            warmup=1
        )

        assert result.passed, f"Filtered search took {result.duration:.2f}s"

    def test_memory_search_returns_results(self, mcp_client, timer):
        """Search should return results structure quickly."""
        with timer() as t:
            result = mcp_client.call_tool("memory_search", {
                "query": "test search query",
                "limit": 5
            })

        assert result.success, f"Search failed: {result.error}"
        assert t.duration < 1.0, f"Search took {t.duration:.2f}s"

        # Verify response structure
        data = result.data
        assert "memories" in data or "results" in data


@pytest.mark.performance
@pytest.mark.benchmark
class TestArtifactSearchLatency:
    """Benchmarks for artifact search latency."""

    def test_simple_artifact_search(self, mcp_client, benchmark):
        """Simple artifact search should complete quickly."""
        def search():
            return mcp_client.call_tool("artifact_search", {
                "query": "meeting notes project",
                "limit": 10
            })

        result = benchmark(
            name="artifact_search",
            func=search,
            threshold=0.8,
            iterations=5,
            warmup=1
        )

        assert result.passed, (
            f"Artifact search took {result.duration:.2f}s, "
            f"threshold is {result.threshold:.2f}s"
        )

    def test_artifact_search_with_filters(self, mcp_client, benchmark):
        """Artifact search with filters."""
        def search():
            return mcp_client.call_tool("artifact_search", {
                "query": "technical documentation",
                "artifact_type": "note",
                "limit": 10
            })

        result = benchmark(
            name="artifact_search_filtered",
            func=search,
            threshold=1.0,
            iterations=3,
            warmup=1
        )

        assert result.passed, f"Filtered artifact search took {result.duration:.2f}s"


@pytest.mark.performance
@pytest.mark.benchmark
class TestHybridSearchLatency:
    """Benchmarks for hybrid search latency."""

    def test_basic_hybrid_search(self, mcp_client, benchmark):
        """Basic hybrid search should complete in <1s."""
        def search():
            return mcp_client.call_tool("hybrid_search", {
                "query": "project planning decision",
                "limit": 10
            })

        result = benchmark(
            name="hybrid_search",
            func=search,
            threshold=THRESHOLDS["hybrid_search"],
            iterations=5,
            warmup=1
        )

        assert result.passed, (
            f"Hybrid search took {result.duration:.2f}s, "
            f"threshold is {result.threshold:.2f}s"
        )

    def test_hybrid_search_with_quality_filters(self, mcp_client, benchmark):
        """Hybrid search with quality filters."""
        def search():
            return mcp_client.call_tool("hybrid_search", {
                "query": "important decisions and risks",
                "limit": 10,
                "quality_filters": ["Decision", "QualityRisk"]
            })

        result = benchmark(
            name="hybrid_search_quality_filtered",
            func=search,
            threshold=1.5,
            iterations=3,
            warmup=1
        )

        assert result.passed, f"Quality-filtered search took {result.duration:.2f}s"

    def test_hybrid_search_with_graph_expansion(self, mcp_client, benchmark):
        """Hybrid search with graph expansion."""
        def search():
            return mcp_client.call_tool("hybrid_search", {
                "query": "team commitments",
                "limit": 10,
                "expand_options": {
                    "enabled": True,
                    "max_hops": 2
                }
            })

        result = benchmark(
            name="hybrid_search_expanded",
            func=search,
            threshold=2.0,  # Graph expansion takes longer
            iterations=3,
            warmup=1
        )

        assert result.passed, f"Expanded search took {result.duration:.2f}s"

    def test_hybrid_search_returns_structured_results(self, mcp_client, timer):
        """Hybrid search should return properly structured results."""
        with timer() as t:
            result = mcp_client.call_tool("hybrid_search", {
                "query": "test query",
                "limit": 5
            })

        assert result.success, f"Search failed: {result.error}"
        assert t.duration < 2.0, f"Search took {t.duration:.2f}s"

        # Verify response has expected sections
        data = result.data
        # Should have some results structure
        assert any(key in data for key in ["results", "memories", "artifacts", "events"])


@pytest.mark.performance
@pytest.mark.benchmark
class TestSearchLimits:
    """Tests for search behavior with different limits."""

    def test_search_limit_10(self, mcp_client, timer):
        """Search with limit 10."""
        with timer() as t:
            result = mcp_client.call_tool("hybrid_search", {
                "query": "test",
                "limit": 10
            })

        assert result.success
        assert t.duration < 1.0

    def test_search_limit_50(self, mcp_client, timer):
        """Search with limit 50."""
        with timer() as t:
            result = mcp_client.call_tool("hybrid_search", {
                "query": "test",
                "limit": 50
            })

        assert result.success
        assert t.duration < 2.0

    def test_search_limit_scaling(self, mcp_client, timer):
        """Search time should scale reasonably with limit."""
        times = {}

        for limit in [5, 20, 50]:
            with timer() as t:
                mcp_client.call_tool("hybrid_search", {
                    "query": "scaling test",
                    "limit": limit
                })
            times[limit] = t.duration

        # Limit 50 should not take 10x longer than limit 5
        assert times[50] < times[5] * 10, (
            f"Search scaling issue: limit=5: {times[5]:.2f}s, limit=50: {times[50]:.2f}s"
        )


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.slow
class TestSearchWithPopulatedDatabase:
    """Search benchmarks with populated database."""

    def test_memory_search_with_data(
        self,
        mcp_client,
        benchmark,
        populated_database
    ):
        """Memory search latency with populated database."""
        def search():
            return mcp_client.call_tool("memory_search", {
                "query": "performance test topic",
                "limit": 10
            })

        result = benchmark(
            name="memory_search_populated",
            func=search,
            threshold=1.0,
            iterations=5,
            warmup=2,
            database_memories=len(populated_database["memories"]),
            database_artifacts=len(populated_database["artifacts"])
        )

        assert result.passed, (
            f"Search with populated DB took {result.duration:.2f}s"
        )

    def test_hybrid_search_with_data(
        self,
        mcp_client,
        benchmark,
        populated_database
    ):
        """Hybrid search latency with populated database."""
        def search():
            return mcp_client.call_tool("hybrid_search", {
                "query": "meeting notes decisions",
                "limit": 20
            })

        result = benchmark(
            name="hybrid_search_populated",
            func=search,
            threshold=2.0,
            iterations=3,
            warmup=1,
            database_memories=len(populated_database["memories"]),
            database_artifacts=len(populated_database["artifacts"])
        )

        assert result.passed, (
            f"Hybrid search with populated DB took {result.duration:.2f}s"
        )


@pytest.mark.performance
@pytest.mark.benchmark
class TestEventSearch:
    """Benchmarks for event search."""

    def test_event_search_by_category(self, mcp_client, benchmark):
        """Event search by category."""
        def search():
            return mcp_client.call_tool("event_search_tool", {
                "categories": ["Decision", "Commitment"],
                "limit": 10
            })

        result = benchmark(
            name="event_search_category",
            func=search,
            threshold=1.0,
            iterations=3,
            warmup=1
        )

        assert result.passed, f"Event search took {result.duration:.2f}s"

    def test_event_search_by_query(self, mcp_client, benchmark):
        """Event search by text query."""
        def search():
            return mcp_client.call_tool("event_search_tool", {
                "query": "project deadline",
                "limit": 10
            })

        result = benchmark(
            name="event_search_query",
            func=search,
            threshold=1.0,
            iterations=3,
            warmup=1
        )

        assert result.passed, f"Event query search took {result.duration:.2f}s"

    def test_event_list_for_artifact(self, mcp_client, timer, populated_database):
        """Event list for artifact should be fast."""
        if not populated_database["artifacts"]:
            pytest.skip("No artifacts in populated database")

        artifact_uid = populated_database["artifacts"][0]

        with timer() as t:
            result = mcp_client.call_tool("event_list_for_artifact", {
                "artifact_uid": artifact_uid,
                "include_evidence": True
            })

        assert t.duration < 1.0, f"Event list took {t.duration:.2f}s"


@pytest.mark.performance
@pytest.mark.benchmark
class TestConcurrentSearch:
    """Tests for concurrent search behavior."""

    @pytest.mark.slow
    def test_sequential_searches(self, mcp_client, timer):
        """Multiple sequential searches should maintain performance."""
        queries = [
            "programming preference",
            "project planning",
            "team decision",
            "technical documentation",
            "meeting notes"
        ]

        times = []
        for query in queries:
            with timer() as t:
                mcp_client.call_tool("hybrid_search", {
                    "query": query,
                    "limit": 10
                })
            times.append(t.duration)

        avg_time = sum(times) / len(times)
        max_time = max(times)

        assert avg_time < 1.5, f"Average search time {avg_time:.2f}s too slow"
        assert max_time < 3.0, f"Max search time {max_time:.2f}s too slow"
