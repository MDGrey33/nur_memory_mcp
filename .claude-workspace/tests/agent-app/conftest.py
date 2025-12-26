"""
Pytest configuration and fixtures for agent-app tests.
"""

import pytest
import asyncio
import sys
from datetime import datetime
from typing import Optional
from pathlib import Path

# Add src directory to Python path to allow imports
src_path = Path(__file__).parent.parent.parent / "implementation" / "agent-app" / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def sample_timestamp() -> str:
    """Return a fixed ISO-8601 timestamp for testing."""
    return "2025-12-25T12:00:00Z"


@pytest.fixture
def sample_conversation_id() -> str:
    """Return a test conversation ID."""
    return "conv_test_123"


@pytest.fixture
def sample_history_turn(sample_conversation_id: str, sample_timestamp: str) -> dict:
    """Return a sample history turn as dict."""
    return {
        "conversation_id": sample_conversation_id,
        "role": "user",
        "text": "This is a test message",
        "turn_index": 0,
        "ts": sample_timestamp,
        "message_id": "msg_001",
        "channel": "test"
    }


@pytest.fixture
def sample_history_result(sample_conversation_id: str, sample_timestamp: str) -> dict:
    """Return a sample history result from gateway."""
    return {
        "id": "msg_001",
        "document": "This is a test message",
        "metadata": {
            "conversation_id": sample_conversation_id,
            "role": "user",
            "turn_index": 0,
            "ts": sample_timestamp,
            "message_id": "msg_001",
            "channel": "test"
        }
    }


@pytest.fixture
def sample_memory_item(sample_conversation_id: str, sample_timestamp: str) -> dict:
    """Return a sample memory item as dict."""
    return {
        "text": "User prefers Docker for deployment",
        "memory_type": "preference",
        "confidence": 0.85,
        "ts": sample_timestamp,
        "conversation_id": sample_conversation_id,
        "entities": "Docker",
        "source": "chat",
        "tags": "deployment,preferences"
    }


@pytest.fixture
def sample_memory_result(sample_conversation_id: str, sample_timestamp: str) -> dict:
    """Return a sample memory result from gateway."""
    return {
        "id": "mem_001",
        "document": "User prefers Docker for deployment",
        "metadata": {
            "type": "preference",
            "confidence": 0.85,
            "ts": sample_timestamp,
            "conversation_id": sample_conversation_id,
            "entities": "Docker",
            "source": "chat",
            "tags": "deployment,preferences"
        },
        "distance": 0.2
    }


@pytest.fixture
def mock_gateway():
    """Return a mock gateway for testing."""
    from unittest.mock import AsyncMock, MagicMock

    gateway = MagicMock()
    gateway.tail_history = AsyncMock(return_value=[])
    gateway.recall_memory = AsyncMock(return_value=[])
    gateway.append_history = AsyncMock(return_value="doc_id_001")
    gateway.write_memory = AsyncMock(return_value="mem_id_001")
    gateway.ensure_collections = AsyncMock(return_value=None)

    return gateway


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
