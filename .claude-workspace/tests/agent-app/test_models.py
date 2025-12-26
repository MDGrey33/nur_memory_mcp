"""
Unit tests for models.py

Tests data models, validation, and serialization.
"""

import pytest
from datetime import datetime

# Imports from src (path setup in conftest.py)
import models

HistoryTurn = models.HistoryTurn
MemoryItem = models.MemoryItem
ContextPackage = models.ContextPackage


class TestHistoryTurn:
    """Test HistoryTurn dataclass."""

    def test_create_valid_history_turn(self):
        """Test creating a valid history turn."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="Hello, world!",
            turn_index=0,
            ts="2025-12-25T12:00:00Z"
        )

        assert turn.conversation_id == "conv_123"
        assert turn.role == "user"
        assert turn.text == "Hello, world!"
        assert turn.turn_index == 0
        assert turn.ts == "2025-12-25T12:00:00Z"
        assert turn.message_id is None
        assert turn.channel is None

    def test_create_with_optional_fields(self):
        """Test creating history turn with optional fields."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="assistant",
            text="Response text",
            turn_index=1,
            ts="2025-12-25T12:00:00Z",
            message_id="msg_001",
            channel="web"
        )

        assert turn.message_id == "msg_001"
        assert turn.channel == "web"

    def test_validate_valid_turn(self):
        """Test validation passes for valid turn."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="Test message",
            turn_index=0,
            ts="2025-12-25T12:00:00Z"
        )
        turn.validate()  # Should not raise

    def test_validate_empty_conversation_id(self):
        """Test validation fails for empty conversation_id."""
        turn = HistoryTurn(
            conversation_id="",
            role="user",
            text="Test",
            turn_index=0,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="conversation_id cannot be empty"):
            turn.validate()

    def test_validate_invalid_role(self):
        """Test validation fails for invalid role."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="invalid_role",
            text="Test",
            turn_index=0,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="role must be one of"):
            turn.validate()

    def test_validate_all_valid_roles(self):
        """Test that all valid roles are accepted."""
        for role in ["user", "assistant", "system"]:
            turn = HistoryTurn(
                conversation_id="conv_123",
                role=role,
                text="Test",
                turn_index=0,
                ts="2025-12-25T12:00:00Z"
            )
            turn.validate()  # Should not raise

    def test_validate_empty_text(self):
        """Test validation fails for empty text."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="",
            turn_index=0,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="text cannot be empty"):
            turn.validate()

    def test_validate_text_too_long(self):
        """Test validation fails for text exceeding 100,000 characters."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="x" * 100001,
            turn_index=0,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="text too long"):
            turn.validate()

    def test_validate_text_at_limit(self):
        """Test validation passes for text at 100,000 character limit."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="x" * 100000,
            turn_index=0,
            ts="2025-12-25T12:00:00Z"
        )
        turn.validate()  # Should not raise

    def test_validate_negative_turn_index(self):
        """Test validation fails for negative turn_index."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="Test",
            turn_index=-1,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="turn_index must be non-negative"):
            turn.validate()

    def test_validate_zero_turn_index(self):
        """Test validation passes for turn_index of 0."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="Test",
            turn_index=0,
            ts="2025-12-25T12:00:00Z"
        )
        turn.validate()  # Should not raise

    def test_validate_invalid_timestamp(self):
        """Test validation fails for invalid timestamp format."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="Test",
            turn_index=0,
            ts="not-a-timestamp"
        )
        with pytest.raises(ValueError, match="ts must be valid ISO-8601 timestamp"):
            turn.validate()

    def test_validate_valid_timestamp_formats(self):
        """Test various valid ISO-8601 timestamp formats."""
        valid_timestamps = [
            "2025-12-25T12:00:00Z",
            "2025-12-25T12:00:00+00:00",
            "2025-12-25T12:00:00.123456Z",
            "2025-12-25T12:00:00"
        ]

        for ts in valid_timestamps:
            turn = HistoryTurn(
                conversation_id="conv_123",
                role="user",
                text="Test",
                turn_index=0,
                ts=ts
            )
            turn.validate()  # Should not raise

    def test_to_dict(self):
        """Test conversion to dictionary."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="Test message",
            turn_index=5,
            ts="2025-12-25T12:00:00Z",
            message_id="msg_001",
            channel="web"
        )

        result = turn.to_dict()

        assert result["conversation_id"] == "conv_123"
        assert result["role"] == "user"
        assert result["text"] == "Test message"
        assert result["turn_index"] == 5
        assert result["ts"] == "2025-12-25T12:00:00Z"
        assert result["message_id"] == "msg_001"
        assert result["channel"] == "web"

    def test_to_dict_with_none_optionals(self):
        """Test to_dict includes None values for optional fields."""
        turn = HistoryTurn(
            conversation_id="conv_123",
            role="user",
            text="Test",
            turn_index=0,
            ts="2025-12-25T12:00:00Z"
        )

        result = turn.to_dict()

        assert result["message_id"] is None
        assert result["channel"] is None


class TestMemoryItem:
    """Test MemoryItem dataclass."""

    def test_create_valid_memory_item(self):
        """Test creating a valid memory item."""
        memory = MemoryItem(
            text="User prefers dark mode",
            memory_type="preference",
            confidence=0.85,
            ts="2025-12-25T12:00:00Z"
        )

        assert memory.text == "User prefers dark mode"
        assert memory.memory_type == "preference"
        assert memory.confidence == 0.85
        assert memory.ts == "2025-12-25T12:00:00Z"
        assert memory.conversation_id is None
        assert memory.entities is None
        assert memory.source is None
        assert memory.tags is None

    def test_create_with_all_fields(self):
        """Test creating memory item with all optional fields."""
        memory = MemoryItem(
            text="User prefers Docker",
            memory_type="preference",
            confidence=0.9,
            ts="2025-12-25T12:00:00Z",
            conversation_id="conv_123",
            entities="Docker",
            source="chat",
            tags="deployment,tools"
        )

        assert memory.conversation_id == "conv_123"
        assert memory.entities == "Docker"
        assert memory.source == "chat"
        assert memory.tags == "deployment,tools"

    def test_validate_valid_memory(self):
        """Test validation passes for valid memory."""
        memory = MemoryItem(
            text="Test memory",
            memory_type="fact",
            confidence=0.8,
            ts="2025-12-25T12:00:00Z"
        )
        memory.validate()  # Should not raise

    def test_validate_empty_text(self):
        """Test validation fails for empty text."""
        memory = MemoryItem(
            text="",
            memory_type="fact",
            confidence=0.8,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="text cannot be empty"):
            memory.validate()

    def test_validate_text_too_long(self):
        """Test validation fails for text exceeding 2,000 characters."""
        memory = MemoryItem(
            text="x" * 2001,
            memory_type="fact",
            confidence=0.8,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="text too long.*max 2,000.*Summarize"):
            memory.validate()

    def test_validate_text_at_limit(self):
        """Test validation passes for text at 2,000 character limit."""
        memory = MemoryItem(
            text="x" * 2000,
            memory_type="fact",
            confidence=0.8,
            ts="2025-12-25T12:00:00Z"
        )
        memory.validate()  # Should not raise

    def test_validate_all_memory_types(self):
        """Test that all valid memory types are accepted."""
        for memory_type in ["preference", "fact", "project", "decision"]:
            memory = MemoryItem(
                text="Test",
                memory_type=memory_type,
                confidence=0.8,
                ts="2025-12-25T12:00:00Z"
            )
            memory.validate()  # Should not raise

    def test_validate_invalid_memory_type(self):
        """Test validation fails for invalid memory type."""
        memory = MemoryItem(
            text="Test",
            memory_type="invalid_type",
            confidence=0.8,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="memory_type must be one of"):
            memory.validate()

    def test_validate_confidence_below_range(self):
        """Test validation fails for confidence below 0.0."""
        memory = MemoryItem(
            text="Test",
            memory_type="fact",
            confidence=-0.1,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="confidence must be in \\[0.0, 1.0\\]"):
            memory.validate()

    def test_validate_confidence_above_range(self):
        """Test validation fails for confidence above 1.0."""
        memory = MemoryItem(
            text="Test",
            memory_type="fact",
            confidence=1.1,
            ts="2025-12-25T12:00:00Z"
        )
        with pytest.raises(ValueError, match="confidence must be in \\[0.0, 1.0\\]"):
            memory.validate()

    def test_validate_confidence_at_bounds(self):
        """Test validation passes for confidence at 0.0 and 1.0."""
        for confidence in [0.0, 1.0]:
            memory = MemoryItem(
                text="Test",
                memory_type="fact",
                confidence=confidence,
                ts="2025-12-25T12:00:00Z"
            )
            memory.validate()  # Should not raise

    def test_validate_invalid_timestamp(self):
        """Test validation fails for invalid timestamp."""
        memory = MemoryItem(
            text="Test",
            memory_type="fact",
            confidence=0.8,
            ts="invalid-timestamp"
        )
        with pytest.raises(ValueError, match="ts must be valid ISO-8601 timestamp"):
            memory.validate()

    def test_validate_valid_source_values(self):
        """Test that all valid source values are accepted."""
        for source in ["chat", "tool", "import"]:
            memory = MemoryItem(
                text="Test",
                memory_type="fact",
                confidence=0.8,
                ts="2025-12-25T12:00:00Z",
                source=source
            )
            memory.validate()  # Should not raise

    def test_validate_invalid_source(self):
        """Test validation fails for invalid source."""
        memory = MemoryItem(
            text="Test",
            memory_type="fact",
            confidence=0.8,
            ts="2025-12-25T12:00:00Z",
            source="invalid_source"
        )
        with pytest.raises(ValueError, match="source must be one of"):
            memory.validate()

    def test_to_dict(self):
        """Test conversion to dictionary."""
        memory = MemoryItem(
            text="Test memory",
            memory_type="preference",
            confidence=0.85,
            ts="2025-12-25T12:00:00Z",
            conversation_id="conv_123",
            entities="Entity1,Entity2",
            source="chat",
            tags="tag1,tag2"
        )

        result = memory.to_dict()

        assert result["text"] == "Test memory"
        assert result["type"] == "preference"
        assert result["confidence"] == 0.85
        assert result["ts"] == "2025-12-25T12:00:00Z"
        assert result["conversation_id"] == "conv_123"
        assert result["entities"] == "Entity1,Entity2"
        assert result["source"] == "chat"
        assert result["tags"] == "tag1,tag2"

    def test_to_dict_key_mapping(self):
        """Test that to_dict maps memory_type to type."""
        memory = MemoryItem(
            text="Test",
            memory_type="fact",
            confidence=0.8,
            ts="2025-12-25T12:00:00Z"
        )

        result = memory.to_dict()

        assert "type" in result
        assert "memory_type" not in result
        assert result["type"] == "fact"


class TestContextPackage:
    """Test ContextPackage dataclass."""

    def test_create_context_package(self):
        """Test creating a context package."""
        history = [
            HistoryTurn(
                conversation_id="conv_123",
                role="user",
                text="Hello",
                turn_index=0,
                ts="2025-12-25T12:00:00Z"
            )
        ]

        memory = MemoryItem(
            text="Test memory",
            memory_type="fact",
            confidence=0.8,
            ts="2025-12-25T12:00:00Z"
        )

        context = ContextPackage(
            history=history,
            memories=[(memory, 0.95)],
            latest_message="Current message"
        )

        assert len(context.history) == 1
        assert len(context.memories) == 1
        assert context.latest_message == "Current message"
        assert context.metadata is not None

    def test_metadata_defaults(self):
        """Test that metadata is initialized with defaults."""
        context = ContextPackage(
            history=[],
            memories=[],
            latest_message="Test"
        )

        assert context.metadata["history_count"] == 0
        assert context.metadata["memory_count"] == 0
        assert context.metadata["truncated"] is False
        assert context.metadata["total_tokens"] == 0

    def test_metadata_counts(self):
        """Test that metadata counts match actual items."""
        history = [
            HistoryTurn("c1", "user", "msg1", 0, "2025-12-25T12:00:00Z"),
            HistoryTurn("c1", "assistant", "msg2", 1, "2025-12-25T12:00:01Z")
        ]

        memories = [
            (MemoryItem("mem1", "fact", 0.8, "2025-12-25T12:00:00Z"), 0.9),
            (MemoryItem("mem2", "preference", 0.85, "2025-12-25T12:00:00Z"), 0.85)
        ]

        context = ContextPackage(
            history=history,
            memories=memories,
            latest_message="Test"
        )

        assert context.metadata["history_count"] == 2
        assert context.metadata["memory_count"] == 2

    def test_custom_metadata(self):
        """Test that custom metadata can be provided."""
        custom_metadata = {
            "history_count": 5,
            "memory_count": 3,
            "truncated": True,
            "total_tokens": 1000,
            "custom_field": "custom_value"
        }

        context = ContextPackage(
            history=[],
            memories=[],
            latest_message="Test",
            metadata=custom_metadata
        )

        assert context.metadata["custom_field"] == "custom_value"
        assert context.metadata["history_count"] == 5

    def test_memory_tuples(self):
        """Test that memories are stored as (MemoryItem, score) tuples."""
        memory = MemoryItem("test", "fact", 0.8, "2025-12-25T12:00:00Z")

        context = ContextPackage(
            history=[],
            memories=[(memory, 0.92)],
            latest_message="Test"
        )

        assert len(context.memories) == 1
        mem_item, score = context.memories[0]
        assert isinstance(mem_item, MemoryItem)
        assert score == 0.92
        assert mem_item.text == "test"
