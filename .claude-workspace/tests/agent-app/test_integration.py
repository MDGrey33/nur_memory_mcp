"""
Integration tests for agent-app.

Tests end-to-end flows with actual Docker containers.
These tests require Docker and docker-compose to be running.
"""

import pytest
import asyncio
import subprocess
from datetime import datetime

# Imports from src (path setup in conftest.py)
import memory_gateway
import context_builder
import memory_policy

ChromaMcpGateway = memory_gateway.ChromaMcpGateway
ContextBuilder = context_builder.ContextBuilder
MemoryPolicy = memory_policy.MemoryPolicy


# Skip all integration tests if Docker is not available
def is_docker_available():
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


pytestmark = pytest.mark.skipif(
    not is_docker_available(),
    reason="Docker is not available or not running"
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestEndToEndFlow:
    """Test complete end-to-end workflows."""

    async def test_store_and_retrieve_history(self):
        """Test storing and retrieving conversation history."""
        gateway = ChromaMcpGateway("localhost:8000")

        async with gateway:
            # Ensure collections exist
            await gateway.ensure_collections(["history", "memory"])

            # Store multiple history turns
            conversation_id = f"test_conv_{datetime.utcnow().timestamp()}"

            await gateway.append_history(
                conversation_id=conversation_id,
                role="user",
                text="Hello, I want to test the memory system",
                turn_index=0,
                ts="2025-12-25T12:00:00Z",
                message_id="msg_001"
            )

            await gateway.append_history(
                conversation_id=conversation_id,
                role="assistant",
                text="Sure, I can help you test the memory system.",
                turn_index=1,
                ts="2025-12-25T12:00:01Z",
                message_id="msg_002"
            )

            await gateway.append_history(
                conversation_id=conversation_id,
                role="user",
                text="Great, let's see if it works.",
                turn_index=2,
                ts="2025-12-25T12:00:02Z",
                message_id="msg_003"
            )

            # Retrieve history
            results = await gateway.tail_history(conversation_id, 10)

            # Verify results
            assert len(results) == 3
            assert results[0]["metadata"]["turn_index"] == 0
            assert results[1]["metadata"]["turn_index"] == 1
            assert results[2]["metadata"]["turn_index"] == 2
            assert "Hello, I want to test" in results[0]["document"]

    async def test_store_and_recall_memories(self):
        """Test storing and recalling memories."""
        gateway = ChromaMcpGateway("localhost:8000")

        async with gateway:
            # Ensure collections exist
            await gateway.ensure_collections(["history", "memory"])

            # Store memories
            conversation_id = f"test_conv_{datetime.utcnow().timestamp()}"

            await gateway.write_memory(
                text="User prefers Docker for container deployment",
                memory_type="preference",
                confidence=0.9,
                ts="2025-12-25T12:00:00Z",
                conversation_id=conversation_id,
                entities="Docker",
                source="chat",
                tags="deployment,containers"
            )

            await gateway.write_memory(
                text="Project uses Python 3.11 and async/await patterns",
                memory_type="fact",
                confidence=0.95,
                ts="2025-12-25T12:00:01Z",
                conversation_id=conversation_id,
                entities="Python",
                source="chat",
                tags="programming,python"
            )

            # Small delay to allow indexing
            await asyncio.sleep(1)

            # Recall memories with semantic search
            results = await gateway.recall_memory(
                query_text="What container technology does the user prefer?",
                k=5,
                min_confidence=0.7
            )

            # Verify results
            assert len(results) > 0
            # Should find Docker preference
            docker_found = any("Docker" in r["document"] for r in results)
            assert docker_found

    async def test_context_building_integration(self):
        """Test complete context building with real gateway."""
        gateway = ChromaMcpGateway("localhost:8000")

        async with gateway:
            # Ensure collections exist
            await gateway.ensure_collections(["history", "memory"])

            conversation_id = f"test_conv_{datetime.utcnow().timestamp()}"

            # Store history
            await gateway.append_history(
                conversation_id=conversation_id,
                role="user",
                text="I need help with memory systems",
                turn_index=0,
                ts="2025-12-25T12:00:00Z"
            )

            await gateway.append_history(
                conversation_id=conversation_id,
                role="assistant",
                text="I can help with memory systems",
                turn_index=1,
                ts="2025-12-25T12:00:01Z"
            )

            # Store memory
            await gateway.write_memory(
                text="User is working on ChromaDB integration",
                memory_type="project",
                confidence=0.85,
                ts="2025-12-25T12:00:00Z",
                conversation_id=conversation_id
            )

            # Small delay for indexing
            await asyncio.sleep(1)

            # Build context
            builder = ContextBuilder(
                gateway=gateway,
                history_tail_n=10,
                memory_top_k=5,
                min_confidence=0.7
            )

            context = await builder.build_context(
                conversation_id=conversation_id,
                latest_user_text="Tell me more about memory systems"
            )

            # Verify context
            assert len(context.history) == 2
            assert context.latest_message == "Tell me more about memory systems"
            assert context.metadata["history_count"] == 2

    async def test_memory_policy_integration(self):
        """Test memory policy with real storage."""
        gateway = ChromaMcpGateway("localhost:8000")
        policy = MemoryPolicy(min_confidence=0.7, max_per_window=2)

        async with gateway:
            await gateway.ensure_collections(["history", "memory"])

            conversation_id = f"test_conv_{datetime.utcnow().timestamp()}"
            window_key = policy.generate_window_key(conversation_id)

            # First memory - should pass
            if policy.should_store("fact", 0.85):
                if policy.enforce_rate_limit(window_key):
                    await gateway.write_memory(
                        text="First memory",
                        memory_type="fact",
                        confidence=0.85,
                        ts="2025-12-25T12:00:00Z"
                    )

            # Second memory - should pass
            if policy.should_store("preference", 0.9):
                if policy.enforce_rate_limit(window_key):
                    await gateway.write_memory(
                        text="Second memory",
                        memory_type="preference",
                        confidence=0.9,
                        ts="2025-12-25T12:00:01Z"
                    )

            # Third memory - should be rate limited
            should_store_third = False
            if policy.should_store("decision", 0.8):
                if policy.enforce_rate_limit(window_key):
                    should_store_third = True

            # Verify rate limiting worked
            assert not should_store_third

    async def test_persistence_across_operations(self):
        """Test that data persists across multiple operations."""
        gateway = ChromaMcpGateway("localhost:8000")

        async with gateway:
            await gateway.ensure_collections(["history", "memory"])

            conversation_id = f"test_conv_{datetime.utcnow().timestamp()}"

            # Store data
            await gateway.append_history(
                conversation_id=conversation_id,
                role="user",
                text="Persistence test message",
                turn_index=0,
                ts="2025-12-25T12:00:00Z"
            )

            await gateway.write_memory(
                text="Persistence test memory",
                memory_type="fact",
                confidence=0.9,
                ts="2025-12-25T12:00:00Z"
            )

        # Close gateway and reopen
        gateway2 = ChromaMcpGateway("localhost:8000")

        async with gateway2:
            # Retrieve data
            history = await gateway2.tail_history(conversation_id, 10)
            assert len(history) >= 1
            assert "Persistence test message" in history[0]["document"]

            await asyncio.sleep(1)  # Allow indexing

            memories = await gateway2.recall_memory(
                query_text="Persistence test",
                k=5,
                min_confidence=0.7
            )
            # Should find the memory (may have other memories too)
            persistence_found = any("Persistence test memory" in m["document"] for m in memories)
            assert persistence_found


@pytest.mark.integration
@pytest.mark.asyncio
class TestErrorHandling:
    """Test error handling in integration scenarios."""

    async def test_invalid_conversation_retrieval(self):
        """Test retrieving history for non-existent conversation."""
        gateway = ChromaMcpGateway("localhost:8000")

        async with gateway:
            await gateway.ensure_collections(["history", "memory"])

            # Should return empty results, not error
            results = await gateway.tail_history("nonexistent_conv_12345", 10)
            assert len(results) == 0

    async def test_query_with_no_memories(self):
        """Test querying when no memories exist."""
        gateway = ChromaMcpGateway("localhost:8000")

        async with gateway:
            await gateway.ensure_collections(["history", "memory"])

            # Should return empty results, not error
            results = await gateway.recall_memory(
                query_text="This query should match nothing specific xyz123",
                k=5,
                min_confidence=0.99
            )
            # May return empty or very low relevance results
            assert isinstance(results, list)


@pytest.mark.integration
@pytest.mark.asyncio
class TestConcurrency:
    """Test concurrent operations."""

    async def test_concurrent_history_writes(self):
        """Test writing history from multiple tasks concurrently."""
        gateway = ChromaMcpGateway("localhost:8000")

        async with gateway:
            await gateway.ensure_collections(["history", "memory"])

            conversation_id = f"test_conv_{datetime.utcnow().timestamp()}"

            # Create multiple concurrent writes
            tasks = []
            for i in range(5):
                task = gateway.append_history(
                    conversation_id=conversation_id,
                    role="user",
                    text=f"Concurrent message {i}",
                    turn_index=i,
                    ts=f"2025-12-25T12:00:{i:02d}Z"
                )
                tasks.append(task)

            # Wait for all writes
            results = await asyncio.gather(*tasks)

            # Verify all writes succeeded
            assert len(results) == 5

            # Retrieve and verify
            history = await gateway.tail_history(conversation_id, 10)
            assert len(history) == 5

    async def test_concurrent_memory_writes(self):
        """Test writing memories from multiple tasks concurrently."""
        gateway = ChromaMcpGateway("localhost:8000")

        async with gateway:
            await gateway.ensure_collections(["history", "memory"])

            # Create multiple concurrent memory writes
            tasks = []
            for i in range(3):
                task = gateway.write_memory(
                    text=f"Concurrent memory {i}",
                    memory_type="fact",
                    confidence=0.8,
                    ts=f"2025-12-25T12:00:{i:02d}Z"
                )
                tasks.append(task)

            # Wait for all writes
            results = await asyncio.gather(*tasks)

            # Verify all writes succeeded
            assert len(results) == 3
