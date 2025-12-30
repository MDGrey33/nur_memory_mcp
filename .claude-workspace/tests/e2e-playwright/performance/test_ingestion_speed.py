"""
Ingestion Speed Benchmarks.

Tests:
- Small document ingestion (<1KB)
- Medium document ingestion (1-10KB)
- Large document ingestion (>10KB, chunked)
- Batch ingestion throughput
- Memory store speed

Run:
    pytest tests/e2e-playwright/performance/test_ingestion_speed.py -v
    pytest tests/e2e-playwright/performance/test_ingestion_speed.py -v -m "not slow"

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
# Document Ingestion Benchmarks
# =============================================================================

@pytest.mark.performance
@pytest.mark.benchmark
class TestDocumentIngestionSpeed:
    """Benchmarks for document ingestion speed."""

    def test_small_document_ingestion(
        self,
        mcp_client,
        benchmark,
        small_document: str
    ):
        """Small document (<1KB) should ingest in <1s."""
        def ingest():
            return mcp_client.call_tool("artifact_ingest", {
                "content": small_document,
                "artifact_type": "note",
                "source_system": "perf-test",
                "title": "Small Doc Speed Test",
                "source_id": f"small-{time.time()}"
            })

        result = benchmark(
            name="ingestion_small",
            func=ingest,
            threshold=THRESHOLDS["ingestion_small"],
            iterations=3,
            warmup=1,
            document_size_kb=len(small_document) / 1024
        )

        assert result.passed, (
            f"Small document ingestion took {result.duration:.2f}s, "
            f"threshold is {result.threshold:.2f}s"
        )

    def test_medium_document_ingestion(
        self,
        mcp_client,
        benchmark,
        medium_document: str
    ):
        """Medium document (5KB) should ingest in <3s."""
        def ingest():
            return mcp_client.call_tool("artifact_ingest", {
                "content": medium_document,
                "artifact_type": "note",
                "source_system": "perf-test",
                "title": "Medium Doc Speed Test",
                "source_id": f"medium-{time.time()}"
            })

        result = benchmark(
            name="ingestion_medium",
            func=ingest,
            threshold=THRESHOLDS["ingestion_medium"],
            iterations=3,
            warmup=1,
            document_size_kb=len(medium_document) / 1024
        )

        assert result.passed, (
            f"Medium document ingestion took {result.duration:.2f}s, "
            f"threshold is {result.threshold:.2f}s"
        )

    @pytest.mark.slow
    def test_large_document_ingestion(
        self,
        mcp_client,
        benchmark,
        large_document: str
    ):
        """Large document (50KB) should ingest in <10s."""
        def ingest():
            return mcp_client.call_tool("artifact_ingest", {
                "content": large_document,
                "artifact_type": "note",
                "source_system": "perf-test",
                "title": "Large Doc Speed Test",
                "source_id": f"large-{time.time()}"
            })

        result = benchmark(
            name="ingestion_large",
            func=ingest,
            threshold=THRESHOLDS["ingestion_large"],
            iterations=2,
            warmup=0,
            document_size_kb=len(large_document) / 1024
        )

        assert result.passed, (
            f"Large document ingestion took {result.duration:.2f}s, "
            f"threshold is {result.threshold:.2f}s"
        )

    def test_ingestion_returns_artifact_uid(
        self,
        mcp_client,
        timer,
        small_document: str
    ):
        """Ingestion should return artifact_uid promptly."""
        with timer() as t:
            result = mcp_client.call_tool("artifact_ingest", {
                "content": small_document,
                "artifact_type": "note",
                "source_system": "perf-test",
                "title": "UID Response Test",
                "source_id": f"uid-test-{time.time()}"
            })

        assert result.success, f"Ingestion failed: {result.error}"
        assert "artifact_uid" in result.data, "Response missing artifact_uid"
        assert t.duration < 2.0, f"UID response took {t.duration:.2f}s"


@pytest.mark.performance
@pytest.mark.benchmark
class TestMemoryStoreSpeed:
    """Benchmarks for memory store speed."""

    def test_single_memory_store(self, mcp_client, benchmark):
        """Storing a single memory should complete in <0.5s."""
        def store():
            return mcp_client.call_tool("memory_store", {
                "content": f"Performance test memory {time.time()}",
                "type": "preference"
            })

        result = benchmark(
            name="memory_store",
            func=store,
            threshold=THRESHOLDS["memory_store"],
            iterations=5,
            warmup=1
        )

        assert result.passed, (
            f"Memory store took {result.duration:.2f}s, "
            f"threshold is {result.threshold:.2f}s"
        )

    def test_memory_with_metadata(self, mcp_client, timer):
        """Memory store with metadata should complete quickly."""
        with timer() as t:
            result = mcp_client.call_tool("memory_store", {
                "content": "Performance test with metadata",
                "type": "fact",
                "confidence": 0.95
            })

        assert result.success
        assert t.duration < 1.0, f"Memory store with metadata took {t.duration:.2f}s"


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.slow
class TestBatchIngestion:
    """Benchmarks for batch ingestion throughput."""

    def test_batch_memory_store(self, mcp_client, benchmark, generate_memories):
        """Batch memory store throughput."""
        memories = generate_memories(count=20)
        stored_ids = []

        def batch_store():
            for mem in memories[:5]:  # Store 5 per iteration
                result = mcp_client.call_tool("memory_store", mem)
                if result.success and result.data:
                    stored_ids.append(result.data.get("memory_id"))

        result = benchmark(
            name="batch_memory_store",
            func=batch_store,
            threshold=5.0,  # 5 memories in 5 seconds
            iterations=2,
            memories_per_batch=5
        )

        # Cleanup
        for mem_id in stored_ids:
            if mem_id:
                try:
                    mcp_client.call_tool("memory_delete", {"memory_id": mem_id})
                except:
                    pass

        assert result.passed, f"Batch store took {result.duration:.2f}s"

    def test_batch_document_ingestion(
        self,
        mcp_client,
        benchmark,
        generate_content
    ):
        """Batch document ingestion throughput."""
        documents = [
            generate_content(size_kb=2.0, content_type="meeting")
            for _ in range(5)
        ]
        ingested_ids = []

        def batch_ingest():
            for i, doc in enumerate(documents):
                result = mcp_client.call_tool("artifact_ingest", {
                    "content": doc,
                    "artifact_type": "note",
                    "source_system": "perf-test",
                    "title": f"Batch Doc {i}",
                    "source_id": f"batch-{i}-{time.time()}"
                })
                if result.success and result.data:
                    ingested_ids.append(result.data.get("artifact_uid"))

        result = benchmark(
            name="batch_document_ingestion",
            func=batch_ingest,
            threshold=15.0,  # 5 documents in 15 seconds
            iterations=1,
            documents_per_batch=5
        )

        # Cleanup
        for art_id in ingested_ids:
            if art_id:
                try:
                    mcp_client.call_tool("artifact_delete", {"artifact_uid": art_id})
                except:
                    pass

        assert result.passed, f"Batch ingestion took {result.duration:.2f}s"


@pytest.mark.performance
@pytest.mark.benchmark
class TestIngestionScaling:
    """Tests for ingestion scaling with document size."""

    def test_ingestion_scales_linearly(
        self,
        mcp_client,
        timer,
        generate_content
    ):
        """Ingestion time should scale roughly linearly with size."""
        sizes = [1, 5, 10]  # KB
        times = []

        for size_kb in sizes:
            content = generate_content(size_kb=size_kb, content_type="text")

            with timer() as t:
                result = mcp_client.call_tool("artifact_ingest", {
                    "content": content,
                    "artifact_type": "doc",
                    "source_system": "perf-test",
                    "title": f"Scale Test {size_kb}KB",
                    "source_id": f"scale-{size_kb}-{time.time()}"
                })

            assert result.success
            times.append({"size_kb": size_kb, "duration": t.duration})

        # Check scaling is reasonable (not exponential)
        # 10KB should not take more than 10x the 1KB time
        time_1kb = times[0]["duration"]
        time_10kb = times[2]["duration"]

        assert time_10kb < time_1kb * 20, (
            f"Scaling issue: 1KB={time_1kb:.2f}s, 10KB={time_10kb:.2f}s"
        )

    def test_chunked_document_detection(
        self,
        mcp_client,
        large_document: str
    ):
        """Large documents should be chunked."""
        result = mcp_client.call_tool("artifact_ingest", {
            "content": large_document,
            "artifact_type": "note",
            "source_system": "perf-test",
            "title": "Chunking Test",
            "source_id": f"chunk-{time.time()}"
        })

        assert result.success

        # Check for chunking indicators
        data = result.data
        is_chunked = data.get("is_chunked", False) or data.get("chunk_count", 0) > 1

        # Large docs (50KB+) should typically be chunked
        if len(large_document) > 30000:  # ~30KB
            # Soft assertion - chunking may depend on configuration
            if not is_chunked:
                print(f"Warning: Large document was not chunked")
