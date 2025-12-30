"""
Pytest Configuration for Performance Tests.

Provides:
- Timing fixtures and utilities
- Benchmark recording
- Performance thresholds
- Test data generation for load testing
"""

from __future__ import annotations

import os
import time
import json
import random
import string
import pytest
from pathlib import Path
from typing import Dict, List, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime

# Add lib directory to path
import sys
LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from mcp_client import MCPClient


# =============================================================================
# Environment Configuration
# =============================================================================

MCP_URL = os.getenv("MCP_URL", "http://localhost:3201/mcp/")
BENCHMARK_OUTPUT_DIR = os.getenv("BENCHMARK_OUTPUT_DIR", "reports/benchmarks")

# Performance thresholds (in seconds)
THRESHOLDS = {
    "ingestion_small": 1.0,      # <1KB document
    "ingestion_medium": 3.0,     # 1-10KB document
    "ingestion_large": 10.0,     # >10KB document
    "search_simple": 0.5,        # Simple search
    "search_complex": 2.0,       # Complex search with filters
    "memory_store": 0.5,         # Store single memory
    "memory_search": 0.5,        # Search memories
    "hybrid_search": 1.0,        # Hybrid search
    "extraction_complete": 120.0, # Event extraction completion
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class BenchmarkResult:
    """Result of a performance benchmark."""
    name: str
    duration: float
    threshold: float
    passed: bool
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "duration_seconds": self.duration,
            "threshold_seconds": self.threshold,
            "passed": self.passed,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


@dataclass
class BenchmarkSuite:
    """Collection of benchmark results."""
    name: str
    results: List[BenchmarkResult] = field(default_factory=list)
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: str = ""

    def add_result(self, result: BenchmarkResult):
        self.results.append(result)

    def finalize(self):
        self.end_time = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_tests": len(self.results),
            "passed": sum(1 for r in self.results if r.passed),
            "failed": sum(1 for r in self.results if not r.passed),
            "results": [r.to_dict() for r in self.results]
        }

    def save(self, output_dir: str = BENCHMARK_OUTPUT_DIR):
        """Save benchmark results to file."""
        os.makedirs(output_dir, exist_ok=True)
        filename = f"benchmark_{self.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = Path(output_dir) / filename
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return filepath


# =============================================================================
# MCP Client Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def mcp_client() -> MCPClient:
    """Session-scoped MCP client."""
    client = MCPClient(base_url=MCP_URL)
    if not client.initialize():
        pytest.skip("Could not connect to MCP server")
    yield client
    client.close()


# =============================================================================
# Timing Fixtures
# =============================================================================

@pytest.fixture
def timer():
    """Factory fixture for timing operations."""
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
            self.duration = None

        def start(self):
            self.start_time = time.perf_counter()
            return self

        def stop(self):
            self.end_time = time.perf_counter()
            self.duration = self.end_time - self.start_time
            return self.duration

        def __enter__(self):
            self.start()
            return self

        def __exit__(self, *args):
            self.stop()

    return Timer


@pytest.fixture
def benchmark(timer, request):
    """Factory fixture for running benchmarks."""
    results = []

    def _benchmark(
        name: str,
        func: Callable,
        threshold: float = None,
        iterations: int = 1,
        warmup: int = 0,
        **metadata
    ) -> BenchmarkResult:
        """
        Run a benchmark.

        Args:
            name: Benchmark name
            func: Function to benchmark (no arguments)
            threshold: Pass/fail threshold in seconds
            iterations: Number of iterations to average
            warmup: Number of warmup iterations (not timed)
            **metadata: Additional metadata to record
        """
        # Warmup
        for _ in range(warmup):
            func()

        # Timed runs
        durations = []
        for _ in range(iterations):
            t = timer()
            with t:
                func()
            durations.append(t.duration)

        avg_duration = sum(durations) / len(durations)
        threshold = threshold or THRESHOLDS.get(name, 10.0)

        result = BenchmarkResult(
            name=name,
            duration=avg_duration,
            threshold=threshold,
            passed=avg_duration <= threshold,
            metadata={
                "iterations": iterations,
                "min_duration": min(durations),
                "max_duration": max(durations),
                "all_durations": durations,
                **metadata
            }
        )
        results.append(result)
        return result

    yield _benchmark

    # Save results after test
    if results:
        suite = BenchmarkSuite(name=request.node.name, results=results)
        suite.finalize()
        suite.save()


# =============================================================================
# Test Data Generation
# =============================================================================

@pytest.fixture
def generate_content():
    """Factory for generating test content of various sizes."""
    def _generate(size_kb: float = 1.0, content_type: str = "text") -> str:
        """
        Generate content of specified size.

        Args:
            size_kb: Target size in kilobytes
            content_type: Type of content (text, meeting, technical)
        """
        target_chars = int(size_kb * 1024)

        if content_type == "meeting":
            # Generate realistic meeting notes
            sections = [
                "Meeting Notes - Performance Test\n\n",
                "Attendees: " + ", ".join([f"Person{i}" for i in range(5)]) + "\n\n",
                "Agenda:\n",
            ]

            topics = [
                "Discussed the quarterly roadmap and key milestones.",
                "Reviewed the budget allocation for Q2.",
                "Agreed on the technical architecture for the new platform.",
                "Sarah committed to delivering the API documentation by Friday.",
                "John will follow up with the client next week.",
                "The team decided to adopt microservices architecture.",
                "Risk identified: Timeline is aggressive for current scope.",
                "Action item: Schedule follow-up meeting with stakeholders.",
            ]

            while len("".join(sections)) < target_chars:
                sections.append(f"\n## Topic {len(sections)}\n")
                for _ in range(3):
                    sections.append(random.choice(topics) + "\n")

            return "".join(sections)[:target_chars]

        elif content_type == "technical":
            # Generate technical documentation
            sections = [
                "# Technical Documentation\n\n",
                "## Overview\n",
                "This document describes the system architecture.\n\n",
            ]

            paragraphs = [
                "The API uses RESTful conventions with JSON payloads.",
                "Authentication is handled via JWT tokens in the Authorization header.",
                "Rate limiting is configured at 100 requests per minute.",
                "The database uses PostgreSQL with connection pooling.",
                "Caching is implemented using Redis for session storage.",
            ]

            while len("".join(sections)) < target_chars:
                sections.append(f"\n### Section {len(sections)}\n")
                sections.append(random.choice(paragraphs) + "\n")

            return "".join(sections)[:target_chars]

        else:
            # Generate random text
            words = ["the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog",
                     "performance", "test", "benchmark", "memory", "search", "artifact"]

            text = []
            while len(" ".join(text)) < target_chars:
                sentence = " ".join(random.choices(words, k=random.randint(5, 15)))
                text.append(sentence.capitalize() + ".")

            return " ".join(text)[:target_chars]

    return _generate


@pytest.fixture
def small_document(generate_content) -> str:
    """Small document (<1KB)."""
    return generate_content(size_kb=0.5, content_type="meeting")


@pytest.fixture
def medium_document(generate_content) -> str:
    """Medium document (5KB)."""
    return generate_content(size_kb=5.0, content_type="meeting")


@pytest.fixture
def large_document(generate_content) -> str:
    """Large document (50KB)."""
    return generate_content(size_kb=50.0, content_type="meeting")


@pytest.fixture
def generate_memories():
    """Factory for generating test memories."""
    def _generate(count: int = 100) -> List[Dict]:
        types = ["preference", "fact", "observation", "instruction"]
        topics = [
            "programming language", "database", "framework", "testing",
            "deployment", "security", "performance", "architecture"
        ]

        memories = []
        for i in range(count):
            memories.append({
                "content": f"Memory {i}: User prefers {random.choice(topics)} for {random.choice(topics)}",
                "type": random.choice(types)
            })

        return memories

    return _generate


# =============================================================================
# Populated Database Fixture
# =============================================================================

@pytest.fixture(scope="module")
def populated_database(mcp_client, generate_content):
    """Populate database with test data for performance tests."""
    created_ids = {"memories": [], "artifacts": []}

    # Create 50 memories
    for i in range(50):
        result = mcp_client.call_tool("memory_store", {
            "content": f"Performance test memory {i} - topic {random.randint(1, 10)}",
            "type": random.choice(["preference", "fact", "observation"])
        })
        if result.success and result.data:
            mem_id = result.data.get("memory_id")
            if mem_id:
                created_ids["memories"].append(mem_id)

    # Create 10 artifacts
    for i in range(10):
        content = generate_content(size_kb=2.0, content_type="meeting")
        result = mcp_client.call_tool("artifact_ingest", {
            "content": content,
            "artifact_type": "note",
            "source_system": "perf-test",
            "title": f"Performance Test Document {i}",
            "source_id": f"perf-test-{i}"
        })
        if result.success and result.data:
            art_id = result.data.get("artifact_uid")
            if art_id:
                created_ids["artifacts"].append(art_id)

    yield created_ids

    # Cleanup
    for mem_id in created_ids["memories"]:
        try:
            mcp_client.call_tool("memory_delete", {"memory_id": mem_id})
        except:
            pass

    for art_id in created_ids["artifacts"]:
        try:
            mcp_client.call_tool("artifact_delete", {"artifact_uid": art_id})
        except:
            pass


# =============================================================================
# Marker Registration
# =============================================================================

def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "performance: Performance benchmark tests"
    )
    config.addinivalue_line(
        "markers",
        "benchmark: Benchmark tests with timing"
    )
    config.addinivalue_line(
        "markers",
        "slow: Slow running tests (>30s)"
    )
    config.addinivalue_line(
        "markers",
        "load: Load testing (many operations)"
    )
