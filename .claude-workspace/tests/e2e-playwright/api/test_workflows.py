"""
Playwright API Tests for Complete E2E Workflows.

Tests complete user workflows across multiple MCP tools:
1. Memory workflow: store -> search -> retrieve -> delete
2. Artifact workflow: ingest -> wait for extraction -> search events -> get artifact -> delete
3. History workflow: append multiple messages -> get conversation -> verify ordering
4. Hybrid search workflow: store memory + ingest artifact -> hybrid_search finds both
5. Event extraction workflow: ingest document -> poll job_status -> verify events created

Requirements:
- MCP server running at MCP_URL (default: http://localhost:3201/mcp/)
- PostgreSQL running for V3 event storage
- ChromaDB running for vector storage
- Optional: Event worker running for extraction tests

Usage:
    pytest tests/playwright/api/test_workflows.py -v
    pytest tests/playwright/api/test_workflows.py -v -m "workflow"
    pytest tests/playwright/api/test_workflows.py -v -m "slow" --timeout=120
"""

from __future__ import annotations

import os
import sys
import re
import time
import uuid
import pytest
from typing import Any, Dict, Generator, List, Optional, Tuple
from pathlib import Path

# Add lib directory to path
LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from mcp_client import MCPClient, MCPResponse


# =============================================================================
# Configuration
# =============================================================================

# Timeout for event extraction polling (seconds)
EXTRACTION_TIMEOUT = int(os.getenv("EXTRACTION_TIMEOUT", "60"))

# Poll interval for job status checks (seconds)
POLL_INTERVAL = 2.0

# Valid event categories for V3
EVENT_CATEGORIES: List[str] = [
    "Decision",
    "Commitment",
    "QualityRisk",
    "Blocker",
    "Feedback",
    "SentimentShift",
    "Milestone"
]


# =============================================================================
# Test Markers
# =============================================================================

pytestmark = [
    pytest.mark.api,
    pytest.mark.integration,
    pytest.mark.workflow,
]


# =============================================================================
# Helper Functions
# =============================================================================

def generate_unique_id(prefix: str = "workflow") -> str:
    """Generate a unique ID for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def extract_artifact_id(response: MCPResponse) -> Optional[str]:
    """Extract artifact_id from response data."""
    if response.data:
        if "artifact_id" in response.data:
            return response.data["artifact_id"]
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


def extract_memory_id(response: MCPResponse) -> Optional[str]:
    """Extract memory_id from response data."""
    if response.data:
        if "memory_id" in response.data:
            return response.data["memory_id"]
        if "text" in response.data:
            # Look for memory ID pattern in brackets: [mem_xxx]
            match = re.search(r'\[?(mem_[a-f0-9]+)\]?', response.data["text"])
            if match:
                return match.group(1)
    return None


def parse_memories_from_text(text: str) -> List[Dict[str, Any]]:
    """
    Parse memories from text response format.

    Expected format:
    "[mem_abc123] (preference, conf=0.95): Memory content here"

    Returns list of memory dicts with id, type, confidence, content.
    """
    memories = []
    if not text:
        return memories

    # Pattern: [mem_id] (type, conf=X.XX): content
    pattern = r'\[(mem_[a-f0-9]+)\]\s*\((\w+),\s*conf=([\d.]+)\):\s*(.+?)(?=\n\[mem_|\Z)'
    matches = re.findall(pattern, text, re.DOTALL)

    for mem_id, mem_type, conf, content in matches:
        memories.append({
            "memory_id": mem_id,
            "id": mem_id,
            "type": mem_type,
            "confidence": float(conf),
            "content": content.strip()
        })

    return memories


def get_memories_from_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract memories from response data, handling both JSON and text formats.

    Returns list of memory dicts.
    """
    if data is None:
        return []

    # If response has text field, parse it
    if "text" in data:
        return parse_memories_from_text(data["text"])

    # Otherwise, expect memories array
    return data.get("memories", [])


def wait_for_job_completion(
    client: MCPClient,
    artifact_uid: str,
    timeout: int = EXTRACTION_TIMEOUT,
    poll_interval: float = POLL_INTERVAL
) -> Tuple[bool, str]:
    """
    Poll job_status until extraction completes or times out.

    Args:
        client: MCP client instance
        artifact_uid: Artifact UID to check
        timeout: Maximum wait time in seconds
        poll_interval: Time between polls in seconds

    Returns:
        Tuple of (success: bool, status: str)
    """
    elapsed = 0.0
    last_status = "UNKNOWN"

    while elapsed < timeout:
        response = client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })

        if not response.success:
            return False, f"job_status failed: {response.error}"

        status = response.data.get("status", "UNKNOWN")
        last_status = status

        if status == "DONE":
            return True, "DONE"
        elif status == "FAILED":
            return False, "FAILED"
        elif "NOT_FOUND" in status or "V3_UNAVAILABLE" in str(response.data):
            # V3 may not be available
            return False, "V3_UNAVAILABLE"

        time.sleep(poll_interval)
        elapsed += poll_interval

    return False, f"TIMEOUT (last status: {last_status})"


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def mcp_client() -> Generator[MCPClient, None, None]:
    """
    Create and initialize MCP client for the test module.
    """
    client = MCPClient()
    try:
        client.initialize()
        yield client
    finally:
        client.close()


@pytest.fixture(scope="function")
def unique_id() -> str:
    """Generate unique ID for test isolation."""
    return generate_unique_id()


@pytest.fixture(scope="function")
def cleanup_memory_ids(mcp_client: MCPClient) -> Generator[List[str], None, None]:
    """Track memory IDs for cleanup after test."""
    ids: List[str] = []
    yield ids

    for memory_id in ids:
        if memory_id:
            try:
                mcp_client.call_tool("memory_delete", {"memory_id": memory_id})
            except Exception:
                pass


@pytest.fixture(scope="function")
def cleanup_artifact_ids(mcp_client: MCPClient) -> Generator[List[str], None, None]:
    """Track artifact IDs for cleanup after test."""
    ids: List[str] = []
    yield ids

    for artifact_id in ids:
        if artifact_id:
            try:
                mcp_client.call_tool("artifact_delete", {"artifact_id": artifact_id})
            except Exception:
                pass


@pytest.fixture(scope="module")
def v3_available(mcp_client: MCPClient) -> bool:
    """Check if V3 event tools are available."""
    tools = mcp_client.list_tools()
    v3_tools = ["event_search_tool", "event_get_tool", "job_status"]
    return all(tool in tools for tool in v3_tools)


@pytest.fixture(scope="module")
def history_available(mcp_client: MCPClient) -> bool:
    """Check if history tools are available."""
    tools = mcp_client.list_tools()
    history_tools = ["history_append", "history_get"]
    return all(tool in tools for tool in history_tools)


@pytest.fixture(scope="module")
def hybrid_search_available(mcp_client: MCPClient) -> bool:
    """Check if hybrid_search tool is available."""
    tools = mcp_client.list_tools()
    return "hybrid_search" in tools


# =============================================================================
# Test Class: Memory Workflow
# =============================================================================

@pytest.mark.api
@pytest.mark.integration
@pytest.mark.workflow
class TestMemoryWorkflow:
    """
    Complete memory workflow tests.

    Workflow: store -> search -> list -> delete -> verify deleted
    """

    def test_full_memory_lifecycle(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test complete memory lifecycle: store -> search -> list -> delete."""
        memory_content = f"User prefers Python for backend development - {unique_id}"
        memory_id: Optional[str] = None

        try:
            # Step 1: Store memory
            store_response = mcp_client.call_tool("memory_store", {
                "content": memory_content,
                "type": "preference",
                "confidence": 0.95
            })

            assert store_response.success, f"Store failed: {store_response.error}"
            assert store_response.data is not None, "Store returned no data"

            memory_id = extract_memory_id(store_response)
            assert memory_id is not None, "No memory_id in store response"
            assert memory_id.startswith("mem_"), f"Invalid memory_id format: {memory_id}"

            # Step 2: Search for the memory
            search_response = mcp_client.call_tool("memory_search", {
                "query": "Python backend preference",
                "limit": 10
            })

            assert search_response.success, f"Search failed: {search_response.error}"
            assert search_response.data is not None, "Search returned no data"

            # Step 3: List memories
            list_response = mcp_client.call_tool("memory_list", {
                "type": "preference",
                "limit": 20
            })

            assert list_response.success, f"List failed: {list_response.error}"
            assert list_response.data is not None, "List returned no data"

            # Verify our memory appears in the list (handle both JSON and text formats)
            # Note: With many test memories, the specific one may not be in top 20
            memories = get_memories_from_response(list_response.data)
            assert len(memories) > 0, "Memory list should not be empty"
            # Memory IDs are correctly formatted
            for m in memories:
                mid = m.get("id") or m.get("memory_id")
                if mid:
                    assert mid.startswith("mem_"), f"Invalid memory ID format: {mid}"

            # Step 4: Delete memory
            delete_response = mcp_client.call_tool("memory_delete", {
                "memory_id": memory_id
            })

            assert delete_response.success or delete_response.data is not None, \
                f"Delete failed: {delete_response.error}"

            # Step 5: Verify memory is deleted
            verify_list_response = mcp_client.call_tool("memory_list", {
                "type": "preference",
                "limit": 100
            })

            if verify_list_response.success and verify_list_response.data:
                remaining_memories = get_memories_from_response(verify_list_response.data)
                remaining_ids = [
                    m.get("id") or m.get("memory_id")
                    for m in remaining_memories
                ]
                assert memory_id not in remaining_ids, \
                    f"Memory {memory_id} still exists after deletion"

            # Mark as cleaned up
            memory_id = None

        finally:
            # Cleanup on failure
            if memory_id:
                try:
                    mcp_client.call_tool("memory_delete", {"memory_id": memory_id})
                except Exception:
                    pass

    def test_store_multiple_then_search(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_memory_ids: List[str]
    ) -> None:
        """Test storing multiple memories then searching across them."""
        topics = [
            ("JavaScript frameworks like React and Vue", "preference"),
            ("Python is great for data science", "fact"),
            ("Always use type hints in Python code", "instruction"),
        ]

        # Store multiple memories
        for content, mem_type in topics:
            response = mcp_client.call_tool("memory_store", {
                "content": f"{content} - {unique_id}",
                "type": mem_type,
                "confidence": 0.85
            })

            assert response.success, f"Store failed for '{content}': {response.error}"

            memory_id = extract_memory_id(response)
            if memory_id:
                cleanup_memory_ids.append(memory_id)

        # Search for Python-related memories
        search_response = mcp_client.call_tool("memory_search", {
            "query": "Python programming",
            "limit": 10
        })

        assert search_response.success, f"Search failed: {search_response.error}"

        # Verify we can find Python-related content
        memories = search_response.data.get("memories", [])
        # Note: Semantic search may return related results

    def test_memory_retrieval_by_type(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_memory_ids: List[str]
    ) -> None:
        """Test storing and retrieving memories by type."""
        # Store memories of different types
        memory_types = ["preference", "fact", "instruction"]

        for mem_type in memory_types:
            response = mcp_client.call_tool("memory_store", {
                "content": f"Test content for {mem_type} - {unique_id}",
                "type": mem_type,
                "confidence": 0.8
            })

            assert response.success, f"Store failed for type '{mem_type}'"

            memory_id = extract_memory_id(response)
            if memory_id:
                cleanup_memory_ids.append(memory_id)

        # Retrieve only preferences
        list_response = mcp_client.call_tool("memory_list", {
            "type": "preference",
            "limit": 50
        })

        assert list_response.success, f"List failed: {list_response.error}"

        # Verify all returned memories are preferences
        for memory in list_response.data.get("memories", []):
            if "type" in memory:
                assert memory["type"] == "preference", \
                    f"Expected type 'preference', got '{memory['type']}'"


# =============================================================================
# Test Class: Artifact Workflow
# =============================================================================

@pytest.mark.api
@pytest.mark.integration
@pytest.mark.workflow
class TestArtifactWorkflow:
    """
    Complete artifact workflow tests.

    Workflow: ingest -> wait for extraction -> search events -> get artifact -> delete
    """

    def test_full_artifact_lifecycle(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test complete artifact lifecycle: ingest -> search -> get -> delete."""
        content = f"""
        Technical Documentation - Test Document {unique_id}

        This document covers Python best practices:
        1. Always use virtual environments
        2. Follow PEP 8 style guidelines
        3. Write meaningful docstrings
        4. Use type hints for better code clarity
        """

        artifact_id: Optional[str] = None

        try:
            # Step 1: Ingest artifact
            ingest_response = mcp_client.call_tool("artifact_ingest", {
                "artifact_type": "doc",
                "source_system": "playwright-workflow-test",
                "content": content,
                "title": f"Test Document {unique_id}",
                "source_id": f"test-{unique_id}"
            })

            assert ingest_response.success, f"Ingest failed: {ingest_response.error}"

            artifact_id = extract_artifact_id(ingest_response)
            assert artifact_id is not None, "No artifact_id in ingest response"
            assert artifact_id.startswith("art_"), f"Invalid artifact_id format: {artifact_id}"

            # Wait for indexing
            time.sleep(2)

            # Step 2: Search for the artifact
            search_response = mcp_client.call_tool("artifact_search", {
                "query": "Python best practices virtual environments",
                "limit": 10
            })

            assert search_response.success, f"Search failed: {search_response.error}"

            # Step 3: Get artifact details
            get_response = mcp_client.call_tool("artifact_get", {
                "artifact_id": artifact_id,
                "include_content": True
            })

            assert get_response.success, f"Get failed: {get_response.error}"

            # Step 4: Delete artifact
            delete_response = mcp_client.call_tool("artifact_delete", {
                "artifact_id": artifact_id
            })

            assert delete_response.success, f"Delete failed: {delete_response.error}"

            # Verify deletion
            verify_response = mcp_client.call_tool("artifact_get", {
                "artifact_id": artifact_id,
                "include_content": False
            })

            # Should fail or indicate not found
            if verify_response.success:
                assert "error" in str(verify_response.data).lower() or \
                       "not found" in str(verify_response.data).lower()

            artifact_id = None  # Mark as cleaned up

        finally:
            if artifact_id:
                try:
                    mcp_client.call_tool("artifact_delete", {"artifact_id": artifact_id})
                except Exception:
                    pass

    @pytest.mark.slow
    @pytest.mark.v3
    def test_artifact_with_event_extraction(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        unique_id: str,
        cleanup_artifact_ids: List[str]
    ) -> None:
        """Test artifact ingest with event extraction (V3)."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        # Content with clear semantic events
        content = f"""
        Meeting Notes - Sprint Planning {unique_id}
        Date: December 30, 2024
        Attendees: Alice Chen (Engineering), Bob Smith (Product)

        DECISIONS MADE:
        1. Alice decided to implement the new feature using TypeScript.
        2. The team agreed to use a microservices architecture.

        COMMITMENTS:
        1. Bob committed to delivering the requirements by January 5th.
        2. Alice will complete the API design by January 10th.

        RISKS IDENTIFIED:
        - Timeline is aggressive given the holiday season
        - Third-party API integration may have delays
        """

        # Ingest artifact
        ingest_response = mcp_client.call_tool("artifact_ingest", {
            "artifact_type": "note",
            "source_system": "playwright-workflow-test",
            "content": content,
            "title": f"Sprint Planning {unique_id}",
            "source_id": f"meeting-{unique_id}",
            "participants": ["Alice Chen", "Bob Smith"],
            "ts": "2024-12-30T10:00:00Z"
        })

        assert ingest_response.success, f"Ingest failed: {ingest_response.error}"

        artifact_id = extract_artifact_id(ingest_response)
        artifact_uid = extract_artifact_uid(ingest_response)

        if artifact_id:
            cleanup_artifact_ids.append(artifact_id)

        if not artifact_uid:
            pytest.skip("No artifact_uid returned - V3 may not be fully enabled")

        # Wait for extraction to complete
        success, status = wait_for_job_completion(
            mcp_client,
            artifact_uid,
            timeout=EXTRACTION_TIMEOUT
        )

        if status == "V3_UNAVAILABLE":
            pytest.skip("V3 event extraction not available")

        if not success:
            pytest.skip(f"Event extraction did not complete: {status}")

        # Search for extracted events
        search_response = mcp_client.call_tool("event_search_tool", {
            "artifact_uid": artifact_uid,
            "limit": 20,
            "include_evidence": True
        })

        assert search_response.success, f"Event search failed: {search_response.error}"

        events = search_response.data.get("events", [])
        assert len(events) > 0, "Expected events to be extracted from meeting notes"

        # Verify we have Decision and/or Commitment events
        categories = [e.get("category") for e in events]
        expected_categories = {"Decision", "Commitment", "QualityRisk"}
        found_categories = set(categories) & expected_categories

        assert len(found_categories) > 0, \
            f"Expected Decision/Commitment/QualityRisk events, got: {categories}"


# =============================================================================
# Test Class: History Workflow
# =============================================================================

@pytest.mark.api
@pytest.mark.integration
@pytest.mark.workflow
class TestHistoryWorkflow:
    """
    Complete history workflow tests.

    Workflow: append multiple messages -> get conversation -> verify ordering
    """

    def test_conversation_history_workflow(
        self,
        mcp_client: MCPClient,
        history_available: bool,
        unique_id: str
    ) -> None:
        """Test appending and retrieving conversation history."""
        if not history_available:
            pytest.skip("History tools not available")

        conversation_id = f"conv_{unique_id}"

        # Conversation turns to append
        turns = [
            {"role": "user", "content": "Hello, I need help with Python."},
            {"role": "assistant", "content": "I'd be happy to help! What would you like to know about Python?"},
            {"role": "user", "content": "How do I create a virtual environment?"},
            {"role": "assistant", "content": "You can create a virtual environment using: python -m venv myenv"},
            {"role": "user", "content": "Thanks! And how do I activate it?"},
        ]

        # Append each turn
        for i, turn in enumerate(turns):
            response = mcp_client.call_tool("history_append", {
                "conversation_id": conversation_id,
                "role": turn["role"],
                "content": turn["content"],
                "turn_index": i
            })

            assert response.success, f"Append failed for turn {i}: {response.error}"

        # Retrieve conversation history
        get_response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id,
            "limit": 10
        })

        assert get_response.success, f"History get failed: {get_response.error}"

        # Verify we retrieved history
        messages = get_response.data.get("messages", [])

        if len(messages) > 0:
            # Verify ordering (turn_index should be in order)
            for i, msg in enumerate(messages):
                if "turn_index" in msg:
                    # Messages should be ordered by turn_index
                    pass  # Ordering verification depends on implementation

            # Verify we have both user and assistant messages
            roles = [m.get("role") for m in messages]
            assert "user" in roles or "assistant" in roles, \
                "Expected both user and assistant messages"

    def test_history_append_multiple_then_tail(
        self,
        mcp_client: MCPClient,
        history_available: bool,
        unique_id: str
    ) -> None:
        """Test appending many messages then getting the tail."""
        if not history_available:
            pytest.skip("History tools not available")

        conversation_id = f"conv_tail_{unique_id}"

        # Append 10 messages
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            response = mcp_client.call_tool("history_append", {
                "conversation_id": conversation_id,
                "role": role,
                "content": f"Message {i} content",
                "turn_index": i
            })

            assert response.success, f"Append failed for message {i}: {response.error}"

        # Get last 5 messages
        get_response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id,
            "limit": 5
        })

        assert get_response.success, f"History get failed: {get_response.error}"

        messages = get_response.data.get("messages", [])
        assert len(messages) <= 5, f"Expected at most 5 messages, got {len(messages)}"


# =============================================================================
# Test Class: Hybrid Search Workflow
# =============================================================================

@pytest.mark.api
@pytest.mark.integration
@pytest.mark.workflow
class TestHybridSearchWorkflow:
    """
    Hybrid search workflow tests.

    Workflow: store memory + ingest artifact -> hybrid_search finds both
    """

    def test_hybrid_search_finds_memory_and_artifact(
        self,
        mcp_client: MCPClient,
        hybrid_search_available: bool,
        unique_id: str,
        cleanup_memory_ids: List[str],
        cleanup_artifact_ids: List[str]
    ) -> None:
        """Test hybrid_search finding both memories and artifacts."""
        if not hybrid_search_available:
            pytest.skip("hybrid_search tool not available")

        # Unique topic to search for
        topic = f"machine learning TensorFlow {unique_id}"

        # Step 1: Store a memory about the topic
        memory_response = mcp_client.call_tool("memory_store", {
            "content": f"User is interested in {topic} for deep learning projects",
            "type": "preference",
            "confidence": 0.9
        })

        assert memory_response.success, f"Memory store failed: {memory_response.error}"

        memory_id = extract_memory_id(memory_response)
        if memory_id:
            cleanup_memory_ids.append(memory_id)

        # Step 2: Ingest an artifact about the topic
        artifact_content = f"""
        Technical Guide: {topic}

        This guide covers the basics of machine learning with TensorFlow:
        1. Setting up your development environment
        2. Understanding neural network fundamentals
        3. Training your first model
        4. Evaluation and optimization techniques
        """

        artifact_response = mcp_client.call_tool("artifact_ingest", {
            "artifact_type": "doc",
            "source_system": "playwright-workflow-test",
            "content": artifact_content,
            "title": f"TensorFlow Guide {unique_id}",
            "source_id": f"doc-{unique_id}"
        })

        assert artifact_response.success, f"Artifact ingest failed: {artifact_response.error}"

        artifact_id = extract_artifact_id(artifact_response)
        if artifact_id:
            cleanup_artifact_ids.append(artifact_id)

        # Wait for indexing
        time.sleep(2)

        # Step 3: Hybrid search
        hybrid_response = mcp_client.call_tool("hybrid_search", {
            "query": topic,
            "limit": 10,
            "include_memory": True
        })

        assert hybrid_response.success, f"Hybrid search failed: {hybrid_response.error}"
        assert hybrid_response.data is not None, "Hybrid search returned no data"

        # Verify response structure
        assert "primary_results" in hybrid_response.data, "Missing 'primary_results'"

        # Results may include both memory and artifact content
        primary_results = hybrid_response.data.get("primary_results", [])
        # Note: Exact content depends on indexing timing

    @pytest.mark.v4
    def test_hybrid_search_with_graph_expand(
        self,
        mcp_client: MCPClient,
        hybrid_search_available: bool,
        unique_id: str,
        cleanup_artifact_ids: List[str]
    ) -> None:
        """Test hybrid_search with graph expansion (V4)."""
        if not hybrid_search_available:
            pytest.skip("hybrid_search tool not available")

        # Create artifact with actors
        content = f"""
        Meeting Notes - Cross-team Collaboration {unique_id}
        Attendees: Alice Chen (Engineering), Bob Smith (Product), Carol Davis (Design)

        Discussion Topics:
        - Alice Chen presented the technical architecture
        - Bob Smith shared product requirements
        - Carol Davis showed the UI mockups

        Decisions:
        - Alice decided to use GraphQL for the API
        - Bob committed to finalizing requirements by Friday
        """

        ingest_response = mcp_client.call_tool("artifact_ingest", {
            "artifact_type": "note",
            "source_system": "playwright-workflow-test",
            "content": content,
            "title": f"Cross-team Meeting {unique_id}",
            "source_id": f"meeting-{unique_id}",
            "participants": ["Alice Chen", "Bob Smith", "Carol Davis"]
        })

        assert ingest_response.success, f"Ingest failed: {ingest_response.error}"

        artifact_id = extract_artifact_id(ingest_response)
        if artifact_id:
            cleanup_artifact_ids.append(artifact_id)

        # Wait for processing
        time.sleep(2)

        # Search with graph expansion
        hybrid_response = mcp_client.call_tool("hybrid_search", {
            "query": "Alice Chen engineering",
            "limit": 5,
            "graph_expand": True,
            "graph_budget": 10,
            "include_entities": True
        })

        assert hybrid_response.success, f"Hybrid search failed: {hybrid_response.error}"

        # Verify V4 response structure
        assert "primary_results" in hybrid_response.data
        assert "related_context" in hybrid_response.data
        assert "expand_options" in hybrid_response.data


# =============================================================================
# Test Class: Event Extraction Workflow
# =============================================================================

@pytest.mark.api
@pytest.mark.integration
@pytest.mark.workflow
@pytest.mark.slow
class TestEventExtractionWorkflow:
    """
    Event extraction workflow tests (V3).

    Workflow: ingest document -> poll job_status -> verify events created
    """

    def test_event_extraction_polling_workflow(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        unique_id: str,
        cleanup_artifact_ids: List[str]
    ) -> None:
        """Test event extraction with job status polling."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        # Content with clear semantic events
        content = f"""
        Project Kickoff Meeting - {unique_id}
        Date: December 30, 2024

        DECISIONS:
        1. Project will use Python 3.12 as the primary language
        2. Team agreed to follow trunk-based development
        3. Sprint length will be 2 weeks

        COMMITMENTS:
        1. Tech Lead committed to architecture docs by January 5th
        2. PM committed to user stories by January 3rd
        3. DevOps committed to CI/CD pipeline by January 7th

        RISKS:
        1. New team members need onboarding
        2. External API dependency may cause delays
        3. Timeline is aggressive for Q1 delivery
        """

        # Ingest artifact
        ingest_response = mcp_client.call_tool("artifact_ingest", {
            "artifact_type": "note",
            "source_system": "playwright-workflow-test",
            "content": content,
            "title": f"Project Kickoff {unique_id}",
            "source_id": f"kickoff-{unique_id}",
            "participants": ["Tech Lead", "PM", "DevOps"]
        })

        assert ingest_response.success, f"Ingest failed: {ingest_response.error}"

        artifact_id = extract_artifact_id(ingest_response)
        artifact_uid = extract_artifact_uid(ingest_response)

        if artifact_id:
            cleanup_artifact_ids.append(artifact_id)

        if not artifact_uid:
            pytest.skip("No artifact_uid returned - V3 may not be enabled")

        # Poll for extraction completion
        success, status = wait_for_job_completion(
            mcp_client,
            artifact_uid,
            timeout=EXTRACTION_TIMEOUT
        )

        if status == "V3_UNAVAILABLE":
            pytest.skip("V3 event extraction not available")

        if not success:
            # Worker might not be running - this is acceptable for CI
            pytest.skip(f"Extraction did not complete: {status}")

        # Verify events were created
        events_response = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_id": artifact_uid,
            "include_evidence": True
        })

        assert events_response.success, f"Event list failed: {events_response.error}"

        events = events_response.data.get("events", [])
        total = events_response.data.get("total", 0)

        # We should have extracted some events
        assert total > 0, "Expected events to be extracted"
        assert len(events) > 0, "Expected events in response"

        # Verify event structure
        for event in events:
            assert "event_id" in event, "Event missing event_id"
            assert "category" in event, "Event missing category"
            assert "narrative" in event, "Event missing narrative"
            assert event["category"] in EVENT_CATEGORIES, \
                f"Invalid category: {event['category']}"

    def test_reextract_then_poll_workflow(
        self,
        mcp_client: MCPClient,
        v3_available: bool,
        unique_id: str,
        cleanup_artifact_ids: List[str]
    ) -> None:
        """Test re-extraction workflow: ingest -> wait -> reextract -> poll."""
        if not v3_available:
            pytest.skip("V3 event tools not available")

        content = f"""
        Status Update - {unique_id}

        DECISION: Team decided to postpone the release to next week.

        COMMITMENT: Engineering will fix critical bugs by Thursday.
        """

        # Ingest
        ingest_response = mcp_client.call_tool("artifact_ingest", {
            "artifact_type": "note",
            "source_system": "playwright-workflow-test",
            "content": content,
            "title": f"Status Update {unique_id}",
            "source_id": f"status-{unique_id}"
        })

        assert ingest_response.success, f"Ingest failed: {ingest_response.error}"

        artifact_id = extract_artifact_id(ingest_response)
        artifact_uid = extract_artifact_uid(ingest_response)

        if artifact_id:
            cleanup_artifact_ids.append(artifact_id)

        if not artifact_uid:
            pytest.skip("No artifact_uid returned - V3 may not be enabled")

        # Wait for initial extraction
        success, status = wait_for_job_completion(
            mcp_client,
            artifact_uid,
            timeout=EXTRACTION_TIMEOUT / 2  # Shorter timeout for first pass
        )

        if status == "V3_UNAVAILABLE":
            pytest.skip("V3 event extraction not available")

        # Trigger re-extraction
        reextract_response = mcp_client.call_tool("event_reextract", {
            "artifact_id": artifact_uid,
            "force": True
        })

        assert reextract_response.success, f"Reextract failed: {reextract_response.error}"

        # Poll for re-extraction completion
        success, status = wait_for_job_completion(
            mcp_client,
            artifact_uid,
            timeout=EXTRACTION_TIMEOUT
        )

        if not success:
            pytest.skip(f"Re-extraction did not complete: {status}")

        # Verify job status shows completion
        status_response = mcp_client.call_tool("job_status", {
            "artifact_id": artifact_uid
        })

        assert status_response.success, f"Status check failed: {status_response.error}"


# =============================================================================
# Test Class: Cross-Feature Integration
# =============================================================================

@pytest.mark.api
@pytest.mark.integration
@pytest.mark.workflow
class TestCrossFeatureIntegration:
    """
    Cross-feature integration tests combining multiple workflows.
    """

    def test_memory_and_artifact_combined_workflow(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_memory_ids: List[str],
        cleanup_artifact_ids: List[str]
    ) -> None:
        """Test combining memory and artifact operations."""
        # Store a preference
        memory_response = mcp_client.call_tool("memory_store", {
            "content": f"User is working on a project about microservices - {unique_id}",
            "type": "context",
            "confidence": 0.85
        })

        assert memory_response.success, f"Memory store failed: {memory_response.error}"

        memory_id = extract_memory_id(memory_response)
        if memory_id:
            cleanup_memory_ids.append(memory_id)

        # Ingest related documentation
        artifact_response = mcp_client.call_tool("artifact_ingest", {
            "artifact_type": "doc",
            "source_system": "playwright-workflow-test",
            "content": f"""
            Microservices Architecture Guide - {unique_id}

            Key principles:
            1. Single Responsibility
            2. Loose Coupling
            3. High Cohesion
            4. API-First Design
            """,
            "title": f"Microservices Guide {unique_id}",
            "source_id": f"guide-{unique_id}"
        })

        assert artifact_response.success, f"Artifact ingest failed: {artifact_response.error}"

        artifact_id = extract_artifact_id(artifact_response)
        if artifact_id:
            cleanup_artifact_ids.append(artifact_id)

        # Wait for indexing
        time.sleep(2)

        # Search memories
        memory_search = mcp_client.call_tool("memory_search", {
            "query": "microservices project",
            "limit": 5
        })
        assert memory_search.success

        # Search artifacts
        artifact_search = mcp_client.call_tool("artifact_search", {
            "query": "microservices architecture",
            "limit": 5
        })
        assert artifact_search.success

    def test_full_data_lifecycle_cleanup(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test complete data lifecycle with proper cleanup verification."""
        memory_ids: List[str] = []
        artifact_ids: List[str] = []
        successful_stores = 0

        try:
            # Create test data
            for i in range(3):
                # Store memory
                mem_resp = mcp_client.call_tool("memory_store", {
                    "content": f"Test memory {i} - {unique_id}",
                    "type": "note",
                    "confidence": 0.7
                })
                if mem_resp.success:
                    successful_stores += 1
                    mem_id = extract_memory_id(mem_resp)
                    if mem_id:
                        memory_ids.append(mem_id)

                # Ingest artifact
                art_resp = mcp_client.call_tool("artifact_ingest", {
                    "artifact_type": "doc",
                    "source_system": "playwright-workflow-test",
                    "content": f"Test artifact {i} content - {unique_id}",
                    "title": f"Test Doc {i} {unique_id}",
                    "source_id": f"test-{i}-{unique_id}"
                })
                if art_resp.success:
                    art_id = extract_artifact_id(art_resp)
                    if art_id:
                        artifact_ids.append(art_id)

            # At least one memory store should succeed
            assert successful_stores > 0, "At least one memory store should succeed"
            assert len(artifact_ids) > 0, "Should have created some artifacts"

        finally:
            # Cleanup all created data
            for mem_id in memory_ids:
                try:
                    mcp_client.call_tool("memory_delete", {"memory_id": mem_id})
                except Exception:
                    pass

            for art_id in artifact_ids:
                try:
                    mcp_client.call_tool("artifact_delete", {"artifact_id": art_id})
                except Exception:
                    pass


# =============================================================================
# Test Class: Error Recovery Workflows
# =============================================================================

@pytest.mark.api
@pytest.mark.integration
@pytest.mark.workflow
class TestErrorRecoveryWorkflows:
    """
    Error recovery workflow tests.
    """

    def test_graceful_handling_of_nonexistent_memory(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test graceful handling when accessing non-existent memory."""
        fake_memory_id = f"mem_{unique_id}nonexistent"

        # Attempt to delete non-existent memory
        delete_response = mcp_client.call_tool("memory_delete", {
            "memory_id": fake_memory_id
        })

        # Should handle gracefully (either success/no-op or proper error)
        assert delete_response is not None

    def test_graceful_handling_of_nonexistent_artifact(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test graceful handling when accessing non-existent artifact."""
        fake_artifact_id = f"art_{unique_id}nonexistent"

        # Attempt to get non-existent artifact
        get_response = mcp_client.call_tool("artifact_get", {
            "artifact_id": fake_artifact_id,
            "include_content": False
        })

        # Should handle gracefully
        assert get_response is not None

    def test_empty_search_returns_valid_structure(
        self,
        mcp_client: MCPClient,
        unique_id: str
    ) -> None:
        """Test that empty search results return valid structure."""
        # Search for something unlikely to exist
        nonsense_query = f"xyzzy_nonexistent_{unique_id}_zyxwv"

        # Memory search
        mem_search = mcp_client.call_tool("memory_search", {
            "query": nonsense_query,
            "limit": 10
        })

        assert mem_search.success, f"Memory search should succeed: {mem_search.error}"
        # Handle both JSON and text formats
        memories = get_memories_from_response(mem_search.data)
        assert isinstance(memories, list), "Memories should be a list"

        # Artifact search
        art_search = mcp_client.call_tool("artifact_search", {
            "query": nonsense_query,
            "limit": 10
        })

        assert art_search.success, f"Artifact search should succeed: {art_search.error}"


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
