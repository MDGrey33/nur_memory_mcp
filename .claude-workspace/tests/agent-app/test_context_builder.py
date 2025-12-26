"""
Unit tests for context_builder.py

Tests context assembly, token budget management, and error handling.
Uses mocked gateway to avoid external dependencies.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Imports from src (path setup in conftest.py)
import context_builder
import models
import exceptions

ContextBuilder = context_builder.ContextBuilder
HistoryTurn = models.HistoryTurn
MemoryItem = models.MemoryItem
ContextPackage = models.ContextPackage
ContextBuildError = exceptions.ContextBuildError


class TestContextBuilderInitialization:
    """Test ContextBuilder initialization."""

    def test_initialization_with_defaults(self, mock_gateway):
        """Test initialization with default parameters."""
        builder = ContextBuilder(mock_gateway)

        assert builder.gateway == mock_gateway
        assert builder.history_tail_n == 16
        assert builder.memory_top_k == 8
        assert builder.min_confidence == 0.7
        assert builder.token_budget is None

    def test_initialization_with_custom_params(self, mock_gateway):
        """Test initialization with custom parameters."""
        builder = ContextBuilder(
            gateway=mock_gateway,
            history_tail_n=20,
            memory_top_k=10,
            min_confidence=0.8,
            token_budget=5000
        )

        assert builder.history_tail_n == 20
        assert builder.memory_top_k == 10
        assert builder.min_confidence == 0.8
        assert builder.token_budget == 5000

    def test_invalid_history_tail_n(self, mock_gateway):
        """Test that invalid history_tail_n raises error."""
        with pytest.raises(ValueError, match="history_tail_n must be >= 1"):
            ContextBuilder(mock_gateway, history_tail_n=0)

        with pytest.raises(ValueError, match="history_tail_n must be >= 1"):
            ContextBuilder(mock_gateway, history_tail_n=-5)

    def test_invalid_memory_top_k(self, mock_gateway):
        """Test that invalid memory_top_k raises error."""
        with pytest.raises(ValueError, match="memory_top_k must be >= 1"):
            ContextBuilder(mock_gateway, memory_top_k=0)

    def test_invalid_min_confidence(self, mock_gateway):
        """Test that invalid min_confidence raises error."""
        with pytest.raises(ValueError, match="min_confidence must be in \\[0.0, 1.0\\]"):
            ContextBuilder(mock_gateway, min_confidence=-0.1)

        with pytest.raises(ValueError, match="min_confidence must be in \\[0.0, 1.0\\]"):
            ContextBuilder(mock_gateway, min_confidence=1.5)

    def test_invalid_token_budget(self, mock_gateway):
        """Test that invalid token_budget raises error."""
        with pytest.raises(ValueError, match="token_budget must be >= 1 or None"):
            ContextBuilder(mock_gateway, token_budget=0)

        with pytest.raises(ValueError, match="token_budget must be >= 1 or None"):
            ContextBuilder(mock_gateway, token_budget=-100)


@pytest.mark.asyncio
class TestContextBuilderBuildContext:
    """Test context building functionality."""

    async def test_build_context_empty_results(self, mock_gateway):
        """Test building context when gateway returns empty results."""
        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test message")

        assert isinstance(context, ContextPackage)
        assert len(context.history) == 0
        assert len(context.memories) == 0
        assert context.latest_message == "Test message"
        assert context.metadata["history_count"] == 0
        assert context.metadata["memory_count"] == 0

    async def test_build_context_with_history(self, mock_gateway, sample_history_result):
        """Test building context with history results."""
        mock_gateway.tail_history = AsyncMock(return_value=[sample_history_result])
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test message")

        assert len(context.history) == 1
        assert context.history[0].text == "This is a test message"
        assert context.history[0].role == "user"
        assert context.metadata["history_count"] == 1

    async def test_build_context_with_memories(self, mock_gateway, sample_memory_result):
        """Test building context with memory results."""
        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(return_value=[sample_memory_result])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test message")

        assert len(context.memories) == 1
        memory_item, similarity = context.memories[0]
        assert memory_item.text == "User prefers Docker for deployment"
        assert memory_item.memory_type == "preference"
        assert 0.0 <= similarity <= 1.0
        assert context.metadata["memory_count"] == 1

    async def test_build_context_parallel_fetching(self, mock_gateway):
        """Test that history and memories are fetched in parallel."""
        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway)
        await builder.build_context("conv_123", "Test message")

        # Both methods should have been called
        mock_gateway.tail_history.assert_called_once()
        mock_gateway.recall_memory.assert_called_once()

    async def test_build_context_correct_parameters(self, mock_gateway):
        """Test that correct parameters are passed to gateway."""
        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(
            mock_gateway,
            history_tail_n=20,
            memory_top_k=10,
            min_confidence=0.8
        )

        await builder.build_context("conv_456", "Query text")

        # Check tail_history call
        mock_gateway.tail_history.assert_called_once_with("conv_456", 20)

        # Check recall_memory call
        mock_gateway.recall_memory.assert_called_once_with(
            "Query text",
            10,
            0.8,
            conversation_id=None
        )

    async def test_build_context_history_error_graceful_degradation(self, mock_gateway):
        """Test graceful degradation when history fetch fails."""
        mock_gateway.tail_history = AsyncMock(side_effect=Exception("History fetch failed"))
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test message")

        # Should still return context with empty history
        assert len(context.history) == 0
        assert context.latest_message == "Test message"

    async def test_build_context_memory_error_graceful_degradation(self, mock_gateway):
        """Test graceful degradation when memory fetch fails."""
        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(side_effect=Exception("Memory fetch failed"))

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test message")

        # Should still return context with empty memories
        assert len(context.memories) == 0
        assert context.latest_message == "Test message"

    async def test_build_context_both_errors_graceful_degradation(self, mock_gateway):
        """Test graceful degradation when both fetches fail."""
        mock_gateway.tail_history = AsyncMock(side_effect=Exception("History failed"))
        mock_gateway.recall_memory = AsyncMock(side_effect=Exception("Memory failed"))

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test message")

        # Should still return minimal context
        assert len(context.history) == 0
        assert len(context.memories) == 0
        assert context.latest_message == "Test message"

    async def test_build_context_similarity_score_conversion(self, mock_gateway):
        """Test that distance is converted to similarity score."""
        memory_result = {
            "id": "mem_001",
            "document": "Test memory",
            "metadata": {"type": "fact", "confidence": 0.8, "ts": "2025-12-25T12:00:00Z"},
            "distance": 0.3  # Distance of 0.3 should become similarity of 0.7
        }

        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(return_value=[memory_result])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test")

        _, similarity = context.memories[0]
        assert similarity == pytest.approx(0.7, abs=0.01)

    async def test_build_context_multiple_history_items(self, mock_gateway):
        """Test building context with multiple history items."""
        history_results = [
            {
                "id": "msg_001",
                "document": "First message",
                "metadata": {
                    "conversation_id": "conv_123",
                    "role": "user",
                    "turn_index": 0,
                    "ts": "2025-12-25T12:00:00Z"
                }
            },
            {
                "id": "msg_002",
                "document": "Second message",
                "metadata": {
                    "conversation_id": "conv_123",
                    "role": "assistant",
                    "turn_index": 1,
                    "ts": "2025-12-25T12:00:01Z"
                }
            }
        ]

        mock_gateway.tail_history = AsyncMock(return_value=history_results)
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test")

        assert len(context.history) == 2
        assert context.history[0].text == "First message"
        assert context.history[1].text == "Second message"


@pytest.mark.asyncio
class TestContextBuilderTokenBudget:
    """Test token budget and truncation functionality."""

    async def test_no_truncation_under_budget(self, mock_gateway):
        """Test that context under budget is not truncated."""
        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway, token_budget=10000)
        context = await builder.build_context("conv_123", "Short message")

        assert context.metadata["truncated"] is False

    @patch('context_builder.count_tokens')
    async def test_truncation_when_over_budget(self, mock_count_tokens, mock_gateway):
        """Test that context is truncated when over budget."""
        # Setup mock to return high token counts
        mock_count_tokens.return_value = 100

        history_result = {
            "id": "msg_001",
            "document": "Long message",
            "metadata": {
                "conversation_id": "conv_123",
                "role": "user",
                "turn_index": 0,
                "ts": "2025-12-25T12:00:00Z"
            }
        }

        mock_gateway.tail_history = AsyncMock(return_value=[history_result])
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway, token_budget=50)
        context = await builder.build_context("conv_123", "Message")

        # Context should be truncated
        assert context.metadata["truncated"] is True

    @patch('context_builder.count_tokens')
    async def test_truncation_priority(self, mock_count_tokens, mock_gateway):
        """Test that truncation preserves latest message priority."""
        # Latest message: 100 tokens
        # History items: 50 tokens each
        # Memories: 30 tokens each
        def token_counter(text):
            if "Latest" in text:
                return 100
            elif "History" in text:
                return 50
            else:
                return 30

        mock_count_tokens.side_effect = token_counter

        history_results = [
            {
                "id": f"msg_{i}",
                "document": f"History {i}",
                "metadata": {
                    "conversation_id": "conv_123",
                    "role": "user",
                    "turn_index": i,
                    "ts": "2025-12-25T12:00:00Z"
                }
            }
            for i in range(5)
        ]

        memory_results = [
            {
                "id": f"mem_{i}",
                "document": f"Memory {i}",
                "metadata": {"type": "fact", "confidence": 0.8, "ts": "2025-12-25T12:00:00Z"},
                "distance": 0.1
            }
            for i in range(3)
        ]

        mock_gateway.tail_history = AsyncMock(return_value=history_results)
        mock_gateway.recall_memory = AsyncMock(return_value=memory_results)

        # Budget: 200 tokens
        # Latest message takes 100, leaving 100 for history (60%) and memories (40%)
        builder = ContextBuilder(mock_gateway, token_budget=200)
        context = await builder.build_context("conv_123", "Latest message")

        # Latest message should always be preserved
        assert context.latest_message == "Latest message"
        assert context.metadata["truncated"] is True


@pytest.mark.asyncio
class TestContextBuilderFormatting:
    """Test context formatting functionality."""

    async def test_format_for_prompt_empty(self, mock_gateway):
        """Test formatting empty context."""
        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test message")

        formatted = builder.format_for_prompt(context)

        assert "=== Current Message ===" in formatted
        assert "User: Test message" in formatted
        assert "=== Recent Conversation History ===" not in formatted
        assert "=== Relevant Memories ===" not in formatted

    async def test_format_for_prompt_with_history(self, mock_gateway, sample_history_result):
        """Test formatting context with history."""
        mock_gateway.tail_history = AsyncMock(return_value=[sample_history_result])
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test message")

        formatted = builder.format_for_prompt(context)

        assert "=== Recent Conversation History ===" in formatted
        assert "[0] User: This is a test message" in formatted

    async def test_format_for_prompt_with_memories(self, mock_gateway, sample_memory_result):
        """Test formatting context with memories."""
        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(return_value=[sample_memory_result])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test message")

        formatted = builder.format_for_prompt(context)

        assert "=== Relevant Memories ===" in formatted
        assert "User prefers Docker for deployment" in formatted
        assert "preference" in formatted
        assert "confidence:" in formatted

    async def test_format_history_multiple_turns(self, mock_gateway):
        """Test formatting multiple history turns."""
        history_results = [
            {
                "id": "msg_001",
                "document": "User message",
                "metadata": {
                    "conversation_id": "conv_123",
                    "role": "user",
                    "turn_index": 0,
                    "ts": "2025-12-25T12:00:00Z"
                }
            },
            {
                "id": "msg_002",
                "document": "Assistant response",
                "metadata": {
                    "conversation_id": "conv_123",
                    "role": "assistant",
                    "turn_index": 1,
                    "ts": "2025-12-25T12:00:01Z"
                }
            }
        ]

        mock_gateway.tail_history = AsyncMock(return_value=history_results)
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test")

        formatted = builder.format_for_prompt(context)

        assert "[0] User: User message" in formatted
        assert "[1] Assistant: Assistant response" in formatted


@pytest.mark.asyncio
class TestContextBuilderPrivateMethods:
    """Test private helper methods."""

    async def test_parse_history_invalid_result(self, mock_gateway):
        """Test that history results are parsed with defaults for missing fields."""
        history_results = [
            {
                "id": "msg_001",
                "document": "Valid message",
                "metadata": {
                    "conversation_id": "conv_123",
                    "role": "user",
                    "turn_index": 0,
                    "ts": "2025-12-25T12:00:00Z"
                }
            },
            {
                "id": "msg_002",
                "document": "Invalid message",
                "metadata": {}  # Missing required fields - will use empty/default values
            }
        ]

        mock_gateway.tail_history = AsyncMock(return_value=history_results)
        mock_gateway.recall_memory = AsyncMock(return_value=[])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test")

        # Implementation parses both, using defaults for missing metadata
        assert len(context.history) == 2
        assert context.history[0].text == "Valid message"
        assert context.history[1].text == "Invalid message"

    async def test_parse_memories_invalid_result(self, mock_gateway):
        """Test that memory results are parsed with defaults for missing fields."""
        memory_results = [
            {
                "id": "mem_001",
                "document": "Valid memory",
                "metadata": {"type": "fact", "confidence": 0.8, "ts": "2025-12-25T12:00:00Z"},
                "distance": 0.2
            },
            {
                "id": "mem_002",
                "document": "Invalid memory",
                "metadata": {},  # Missing required fields - will use default values
                "distance": 0.3
            }
        ]

        mock_gateway.tail_history = AsyncMock(return_value=[])
        mock_gateway.recall_memory = AsyncMock(return_value=memory_results)

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Test")

        # Implementation parses both, using defaults for missing metadata
        assert len(context.memories) == 2
        assert context.memories[0][0].text == "Valid memory"
        assert context.memories[1][0].text == "Invalid memory"

    @patch('context_builder.count_tokens')
    async def test_count_context_tokens(self, mock_count_tokens, mock_gateway):
        """Test token counting for complete context."""
        mock_count_tokens.return_value = 10

        history_result = {
            "id": "msg_001",
            "document": "History message",
            "metadata": {
                "conversation_id": "conv_123",
                "role": "user",
                "turn_index": 0,
                "ts": "2025-12-25T12:00:00Z"
            }
        }

        memory_result = {
            "id": "mem_001",
            "document": "Memory text",
            "metadata": {"type": "fact", "confidence": 0.8, "ts": "2025-12-25T12:00:00Z"},
            "distance": 0.2
        }

        mock_gateway.tail_history = AsyncMock(return_value=[history_result])
        mock_gateway.recall_memory = AsyncMock(return_value=[memory_result])

        builder = ContextBuilder(mock_gateway)
        context = await builder.build_context("conv_123", "Latest message")

        # Should count tokens for: latest_message (10) + history (10) + memory (10) = 30
        assert context.metadata["total_tokens"] == 30
