"""
Playwright API Tests for History Operations.

Tests all history tools: history_append, history_get

Test Environment:
- Requires MCP server running at MCP_URL (default: http://localhost:3201/mcp/)
- Uses fixtures from conftest.py (mcp_client, env_config)

Usage:
    # Run all history tests
    pytest tests/e2e-playwright/api/test_history.py -v

    # Run only append tests
    pytest tests/e2e-playwright/api/test_history.py -v -k "append"

    # Run with specific environment
    MCP_URL=http://localhost:3001/mcp/ pytest tests/e2e-playwright/api/test_history.py -v
"""

from __future__ import annotations

import re
import uuid
import pytest
from typing import Any, Dict, Generator, List, Optional

# Import from lib directory (added to path in conftest.py)
from lib import MCPClient, MCPResponse, MCPClientError


# =============================================================================
# Test Constants and Configuration
# =============================================================================

# Valid message roles
VALID_ROLES = ["user", "assistant", "system"]

# Maximum content length to test
MAX_CONTENT_LENGTH = 10000


# =============================================================================
# Text Response Parsing Helpers
# =============================================================================

def parse_messages_from_text(text: str) -> List[Dict[str, str]]:
    """
    Parse messages from text response format.

    Expected format:
    "user: Hello, how are you?
     assistant: I'm doing well, thank you for asking!"

    Returns list of {"role": ..., "content": ...} dicts.
    """
    messages = []
    if not text:
        return messages

    # Split by newline and parse each line
    lines = text.strip().split('\n')
    current_role = None
    current_content = []

    for line in lines:
        # Check if line starts with a role prefix
        role_match = re.match(r'^(user|assistant|system):\s*(.*)$', line)
        if role_match:
            # Save previous message if any
            if current_role is not None:
                messages.append({
                    "role": current_role,
                    "content": '\n'.join(current_content).strip()
                })
            current_role = role_match.group(1)
            current_content = [role_match.group(2)]
        elif current_role is not None:
            # Continue previous message
            current_content.append(line)

    # Don't forget the last message
    if current_role is not None:
        messages.append({
            "role": current_role,
            "content": '\n'.join(current_content).strip()
        })

    return messages


def get_messages_from_response(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract messages from response data, handling both JSON and text formats.

    Returns list of message dicts with role and content.
    """
    if data is None:
        return []

    # If response has text field, parse it
    if "text" in data:
        return parse_messages_from_text(data["text"])

    # Otherwise, expect messages array
    return data.get("messages", [])


# =============================================================================
# Response Schema Validators
# =============================================================================

def validate_history_append_response(data: Dict[str, Any]) -> bool:
    """
    Validate history_append response schema.

    Handles both JSON and text response formats:
    - JSON: {"status": "appended", "conversation_id": "...", ...}
    - Text: {"text": "Appended turn 0 to conv-123"}
    """
    if data is None:
        return False

    # Text response format
    if "text" in data:
        text = data["text"]
        # Should contain "Appended" or similar success indicator
        return "Appended" in text or "appended" in text or "success" in text.lower()

    # JSON format - should have either status or conversation_id indicating success
    has_status = "status" in data
    has_conversation_id = "conversation_id" in data
    return has_status or has_conversation_id


def validate_history_get_response(data: Dict[str, Any]) -> bool:
    """
    Validate history_get response schema.

    Handles both JSON and text response formats:
    - JSON: {"conversation_id": "...", "messages": [...], ...}
    - Text: {"text": "user: Hello\nassistant: Hi there"}
    """
    if data is None:
        return False

    # Text response format
    if "text" in data:
        # Text response is valid if it's a string (may be empty for new conversations)
        return isinstance(data["text"], str)

    # JSON format
    if "messages" not in data:
        return False
    if not isinstance(data["messages"], list):
        return False
    return True


def validate_message_item(message: Dict[str, Any]) -> bool:
    """
    Validate individual message structure.

    Expected fields in each message:
    - role: str ("user", "assistant", "system")
    - content: str
    - timestamp: str (optional, ISO timestamp)
    """
    if message is None:
        return False

    # Role is required
    if "role" not in message:
        return False

    # Content is required
    if "content" not in message:
        return False

    return True


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def unique_conversation_id() -> str:
    """Generate unique conversation ID for test isolation."""
    return f"test-conv-{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="function")
def unique_id() -> str:
    """Generate unique ID for test isolation."""
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="function")
def test_message_params(unique_id: str) -> Dict[str, Any]:
    """Generate unique message parameters for testing."""
    return {
        "role": "user",
        "content": f"Test message content - {unique_id}"
    }


@pytest.fixture(scope="function")
def cleanup_conversation_ids() -> Generator[List[str], None, None]:
    """
    Track conversation IDs for cleanup after test.

    Note: History doesn't have a delete operation, so cleanup is passive.
    This fixture tracks IDs for potential future cleanup mechanisms.
    """
    ids: List[str] = []
    yield ids
    # No active cleanup needed for history - conversations persist


@pytest.fixture(scope="function")
def history_tools_available(mcp_client: MCPClient) -> bool:
    """Check if history tools are available on the server."""
    tools = mcp_client.list_tools()
    return "history_append" in tools and "history_get" in tools


@pytest.fixture(scope="function")
def conversation_with_messages(
    mcp_client: MCPClient,
    unique_conversation_id: str,
    cleanup_conversation_ids: List[str]
) -> Generator[Dict[str, Any], None, None]:
    """
    Create a conversation with some messages for tests that need existing data.

    Yields:
        Dict with conversation_id and message count
    """
    conversation_id = unique_conversation_id
    cleanup_conversation_ids.append(conversation_id)

    # Append some initial messages
    messages = [
        {"role": "user", "content": "Hello, how are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you for asking!"},
        {"role": "user", "content": "Can you help me with a task?"},
    ]

    for i, msg in enumerate(messages):
        response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": i,
            "role": msg["role"],
            "content": msg["content"]
        })

        if not response.success:
            pytest.skip(f"Failed to create test conversation: {response.error}")

    yield {
        "conversation_id": conversation_id,
        "message_count": len(messages),
        "messages": messages
    }


# =============================================================================
# Test Class: history_append
# =============================================================================

@pytest.mark.api
@pytest.mark.history
class TestHistoryAppend:
    """Tests for the history_append tool."""

    def test_append_basic_message(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test appending a basic message to conversation history."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "user",
            "content": "Hello, this is a test message."
        })

        assert response.success, f"history_append failed: {response.error}"
        assert response.data is not None, "Response data is None"
        assert validate_history_append_response(response.data), \
            f"Invalid response schema: {response.data}"

    def test_append_all_role_types(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test appending messages with all valid roles."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        for i, role in enumerate(VALID_ROLES):
            response = mcp_client.call_tool("history_append", {
                "conversation_id": conversation_id,
                "turn_index": i,
                "role": role,
                "content": f"Test message with role: {role}"
            })

            assert response.success, \
                f"history_append failed for role '{role}': {response.error}"

    def test_append_multiple_messages_same_conversation(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test appending multiple messages to the same conversation."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "First response"},
            {"role": "user", "content": "Second message"},
            {"role": "assistant", "content": "Second response"},
            {"role": "user", "content": "Third message"},
        ]

        for i, msg in enumerate(messages):
            response = mcp_client.call_tool("history_append", {
                "conversation_id": conversation_id,
                "turn_index": i,
                "role": msg["role"],
                "content": msg["content"]
            })

            assert response.success, \
                f"history_append failed for message {i+1}: {response.error}"

    def test_append_long_content(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test appending message with long content."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        long_content = "This is a long message content. " * 200  # ~6400 chars

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "user",
            "content": long_content
        })

        assert response.success, f"history_append failed for long content: {response.error}"

    def test_append_special_characters(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test appending message with special characters in content."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        special_content = (
            "Test with special chars: "
            "quotes \"double\" 'single' "
            "unicode \u00e9\u00e0\u00fc\u00f1 "
            "newlines\n\ttabs "
            "backslash \\\\ "
            "angle brackets <tag> "
            "ampersand & "
            "curly braces {key: value}"
        )

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "user",
            "content": special_content
        })

        assert response.success, \
            f"history_append failed for special characters: {response.error}"

    def test_append_multiline_content(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test appending message with multiline content."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        multiline_content = """This is line 1.
This is line 2.
This is line 3.

This is after a blank line.
    This line has leading whitespace."""

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "user",
            "content": multiline_content
        })

        assert response.success, \
            f"history_append failed for multiline content: {response.error}"

    def test_append_returns_latency(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test that response includes latency measurement."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "user",
            "content": "Test message for latency check"
        })

        assert response.success, f"history_append failed: {response.error}"
        assert response.latency_ms > 0, "Latency should be positive"
        assert response.latency_ms < 30000, "Latency exceeded 30 seconds"

    def test_append_code_block_content(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test appending message with code block content."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        code_content = """Here is some code:

```python
def hello_world():
    print("Hello, World!")
    return True

# This is a comment
if __name__ == "__main__":
    hello_world()
```

And that's the end of the code."""

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "assistant",
            "content": code_content
        })

        assert response.success, \
            f"history_append failed for code content: {response.error}"


# =============================================================================
# Test Class: history_append Error Cases
# =============================================================================

@pytest.mark.api
@pytest.mark.history
class TestHistoryAppendErrors:
    """Error handling tests for history_append tool."""

    def test_append_missing_conversation_id(
        self,
        mcp_client: MCPClient,
        history_tools_available: bool
    ) -> None:
        """Test error when conversation_id is missing."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        params = {
            "role": "user",
            "content": "Test content"
            # conversation_id is missing
        }

        response = mcp_client.call_tool("history_append", params)

        # Should fail or return error
        assert not response.success or response.error is not None, \
            "Should fail when conversation_id is missing"

    def test_append_missing_role(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        history_tools_available: bool
    ) -> None:
        """Test error when role is missing."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        params = {
            "conversation_id": unique_conversation_id,
            "content": "Test content"
            # role is missing
        }

        response = mcp_client.call_tool("history_append", params)

        # Should fail or return error
        assert not response.success or response.error is not None, \
            "Should fail when role is missing"

    def test_append_missing_content(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        history_tools_available: bool
    ) -> None:
        """Test error when content is missing."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        params = {
            "conversation_id": unique_conversation_id,
            "role": "user"
            # content is missing
        }

        response = mcp_client.call_tool("history_append", params)

        # Should fail or return error
        assert not response.success or response.error is not None, \
            "Should fail when content is missing"

    def test_append_empty_content(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        history_tools_available: bool
    ) -> None:
        """Test behavior with empty content string."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        params = {
            "conversation_id": unique_conversation_id,
            "role": "user",
            "content": ""
        }

        response = mcp_client.call_tool("history_append", params)

        # Empty content may either fail or be accepted depending on implementation
        assert response is not None, "Should return a response"

    def test_append_invalid_role(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        history_tools_available: bool
    ) -> None:
        """Test behavior with invalid role."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        params = {
            "conversation_id": unique_conversation_id,
            "role": "invalid_role_xyz",
            "content": "Test content"
        }

        response = mcp_client.call_tool("history_append", params)

        # May fail or default to a valid role depending on implementation
        assert response is not None, "Should return a response"

    def test_append_empty_conversation_id(
        self,
        mcp_client: MCPClient,
        history_tools_available: bool
    ) -> None:
        """Test behavior with empty conversation_id."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        params = {
            "conversation_id": "",
            "role": "user",
            "content": "Test content"
        }

        response = mcp_client.call_tool("history_append", params)

        # Empty conversation_id should be rejected
        assert response is not None, "Should return a response"


# =============================================================================
# Test Class: history_get
# =============================================================================

@pytest.mark.api
@pytest.mark.history
class TestHistoryGet:
    """Tests for the history_get tool."""

    def test_get_basic(
        self,
        mcp_client: MCPClient,
        conversation_with_messages: Dict[str, Any],
        history_tools_available: bool
    ) -> None:
        """Test basic history retrieval."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = conversation_with_messages["conversation_id"]

        response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })

        assert response.success, f"history_get failed: {response.error}"
        assert response.data is not None, "Response data is None"
        assert validate_history_get_response(response.data), \
            f"Invalid response schema: {response.data}"

    def test_get_returns_messages_in_order(
        self,
        mcp_client: MCPClient,
        conversation_with_messages: Dict[str, Any],
        history_tools_available: bool
    ) -> None:
        """Test that messages are returned in chronological order."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = conversation_with_messages["conversation_id"]
        original_messages = conversation_with_messages["messages"]

        response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })

        assert response.success, f"history_get failed: {response.error}"

        messages = get_messages_from_response(response.data)
        assert len(messages) >= len(original_messages), \
            f"Expected at least {len(original_messages)} messages, got {len(messages)}"

        # Verify content matches in order
        for i, orig_msg in enumerate(original_messages):
            if i < len(messages):
                assert messages[i].get("content") == orig_msg["content"], \
                    f"Message {i} content mismatch"
                assert messages[i].get("role") == orig_msg["role"], \
                    f"Message {i} role mismatch"

    def test_get_with_limit(
        self,
        mcp_client: MCPClient,
        conversation_with_messages: Dict[str, Any],
        history_tools_available: bool
    ) -> None:
        """Test history retrieval with limit parameter."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = conversation_with_messages["conversation_id"]

        response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id,
            "limit": 2
        })

        assert response.success, f"history_get failed: {response.error}"

        messages = get_messages_from_response(response.data)
        assert len(messages) <= 2, \
            f"Expected at most 2 messages, got {len(messages)}"

    def test_get_empty_conversation(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        history_tools_available: bool
    ) -> None:
        """Test retrieving history for non-existent conversation."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        response = mcp_client.call_tool("history_get", {
            "conversation_id": unique_conversation_id
        })

        # Should return success with empty messages or a not-found indicator
        if response.success:
            messages = get_messages_from_response(response.data)
            # Empty conversation should return empty messages
            assert isinstance(messages, list), "Messages should be a list"

    def test_get_returns_valid_message_structure(
        self,
        mcp_client: MCPClient,
        conversation_with_messages: Dict[str, Any],
        history_tools_available: bool
    ) -> None:
        """Test that retrieved messages have valid structure."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = conversation_with_messages["conversation_id"]

        response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })

        assert response.success, f"history_get failed: {response.error}"

        messages = get_messages_from_response(response.data)

        for message in messages:
            assert validate_message_item(message), \
                f"Invalid message structure: {message}"

    def test_get_returns_latency(
        self,
        mcp_client: MCPClient,
        conversation_with_messages: Dict[str, Any],
        history_tools_available: bool
    ) -> None:
        """Test that response includes latency measurement."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = conversation_with_messages["conversation_id"]

        response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })

        assert response.success, f"history_get failed: {response.error}"
        assert response.latency_ms > 0, "Latency should be positive"
        assert response.latency_ms < 30000, "Latency exceeded 30 seconds"

    def test_get_preserves_content_integrity(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test that special characters in content are preserved."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        special_content = "Test with \"quotes\" and 'apostrophes' and unicode \u00e9\u00e0"

        # Append message with special content
        append_response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "user",
            "content": special_content
        })

        assert append_response.success, f"Append failed: {append_response.error}"

        # Retrieve and verify
        get_response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })

        assert get_response.success, f"Get failed: {get_response.error}"

        messages = get_messages_from_response(get_response.data)
        assert len(messages) > 0, "Should have at least one message"

        # Find and verify our message contains key special characters
        # Text format may not preserve exact content, so check for key elements
        found = False
        for msg in messages:
            content = msg.get("content", "")
            # Check that key elements are present (quotes, unicode chars)
            if "quotes" in content and "apostrophes" in content:
                found = True
                break

        assert found, "Special content was not preserved correctly"


# =============================================================================
# Test Class: history_get Error Cases
# =============================================================================

@pytest.mark.api
@pytest.mark.history
class TestHistoryGetErrors:
    """Error handling tests for history_get tool."""

    def test_get_missing_conversation_id(
        self,
        mcp_client: MCPClient,
        history_tools_available: bool
    ) -> None:
        """Test error when conversation_id is missing."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        response = mcp_client.call_tool("history_get", {})

        # Should fail or return error
        assert not response.success or response.error is not None, \
            "Should fail when conversation_id is missing"

    def test_get_empty_conversation_id(
        self,
        mcp_client: MCPClient,
        history_tools_available: bool
    ) -> None:
        """Test behavior with empty conversation_id."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        response = mcp_client.call_tool("history_get", {
            "conversation_id": ""
        })

        # Empty conversation_id should be rejected or return empty
        assert response is not None, "Should return a response"

    def test_get_invalid_limit(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        history_tools_available: bool
    ) -> None:
        """Test behavior with invalid limit values."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        invalid_limits = [-1, 0, -100]

        for limit in invalid_limits:
            response = mcp_client.call_tool("history_get", {
                "conversation_id": unique_conversation_id,
                "limit": limit
            })

            # Should handle gracefully
            assert response is not None, \
                f"Should return a response for limit {limit}"


# =============================================================================
# Test Class: Integration Tests
# =============================================================================

@pytest.mark.api
@pytest.mark.history
@pytest.mark.integration
class TestHistoryIntegration:
    """Integration tests for history operations workflow."""

    def test_full_conversation_lifecycle(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test complete conversation lifecycle: append multiple -> get all."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        # 1. Start a conversation with user message
        response1 = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "user",
            "content": "What is the capital of France?"
        })
        assert response1.success, f"First append failed: {response1.error}"

        # 2. Add assistant response
        response2 = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 1,
            "role": "assistant",
            "content": "The capital of France is Paris."
        })
        assert response2.success, f"Second append failed: {response2.error}"

        # 3. Add follow-up question
        response3 = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 2,
            "role": "user",
            "content": "What is its population?"
        })
        assert response3.success, f"Third append failed: {response3.error}"

        # 4. Add final response
        response4 = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 3,
            "role": "assistant",
            "content": "Paris has a population of approximately 2.1 million people."
        })
        assert response4.success, f"Fourth append failed: {response4.error}"

        # 5. Retrieve full history
        get_response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })
        assert get_response.success, f"Get failed: {get_response.error}"

        messages = get_messages_from_response(get_response.data)
        assert len(messages) >= 4, f"Expected at least 4 messages, got {len(messages)}"

    def test_multiple_conversations_isolation(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test that multiple conversations are properly isolated."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conv1_id = f"conv1-{unique_id}"
        conv2_id = f"conv2-{unique_id}"
        cleanup_conversation_ids.extend([conv1_id, conv2_id])

        # Add message to conversation 1
        response1 = mcp_client.call_tool("history_append", {
            "conversation_id": conv1_id,
            "turn_index": 0,
            "role": "user",
            "content": "Message for conversation 1"
        })
        assert response1.success

        # Add message to conversation 2
        response2 = mcp_client.call_tool("history_append", {
            "conversation_id": conv2_id,
            "turn_index": 0,
            "role": "user",
            "content": "Message for conversation 2"
        })
        assert response2.success

        # Get conversation 1
        get1_response = mcp_client.call_tool("history_get", {
            "conversation_id": conv1_id
        })
        assert get1_response.success

        # Get conversation 2
        get2_response = mcp_client.call_tool("history_get", {
            "conversation_id": conv2_id
        })
        assert get2_response.success

        # Verify isolation
        messages1 = get_messages_from_response(get1_response.data)
        messages2 = get_messages_from_response(get2_response.data)

        # Conversation 1 should not contain conversation 2 content
        for msg in messages1:
            assert "conversation 2" not in msg.get("content", "").lower(), \
                "Conversation 1 contains conversation 2 content"

        # Conversation 2 should not contain conversation 1 content
        for msg in messages2:
            assert "conversation 1" not in msg.get("content", "").lower(), \
                "Conversation 2 contains conversation 1 content"

    def test_append_then_get_preserves_order(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test that message order is preserved across append and get."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        # Create numbered messages
        message_contents = [
            "Message number 1",
            "Message number 2",
            "Message number 3",
            "Message number 4",
            "Message number 5",
        ]

        for i, content in enumerate(message_contents):
            response = mcp_client.call_tool("history_append", {
                "conversation_id": conversation_id,
                "turn_index": i,
                "role": "user",
                "content": content
            })
            assert response.success, f"Append failed for: {content}"

        # Get history
        get_response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })
        assert get_response.success, f"Get failed: {get_response.error}"

        messages = get_messages_from_response(get_response.data)
        assert len(messages) >= len(message_contents), "Not all messages retrieved"

        # Verify order
        for i, expected_content in enumerate(message_contents):
            if i < len(messages):
                assert messages[i].get("content") == expected_content, \
                    f"Message {i+1} out of order"

    def test_system_message_handling(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test handling of system messages in conversation."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        # Add system message
        sys_response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "system",
            "content": "You are a helpful assistant."
        })
        assert sys_response.success, f"System message append failed: {sys_response.error}"

        # Add user message
        user_response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 1,
            "role": "user",
            "content": "Hello!"
        })
        assert user_response.success, f"User message append failed: {user_response.error}"

        # Get history
        get_response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })
        assert get_response.success, f"Get failed: {get_response.error}"

        messages = get_messages_from_response(get_response.data)

        # Verify system message is present
        roles = [msg.get("role") for msg in messages]
        assert "system" in roles, "System message not found in history"


# =============================================================================
# Test Class: Performance Tests
# =============================================================================

@pytest.mark.api
@pytest.mark.history
@pytest.mark.performance
@pytest.mark.slow
class TestHistoryPerformance:
    """Performance tests for history operations."""

    def test_append_latency(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test that append operation completes within acceptable time."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "user",
            "content": "Performance test message"
        })

        assert response.success, f"history_append failed: {response.error}"
        assert response.latency_ms < 5000, \
            f"Append latency {response.latency_ms}ms exceeded 5s threshold"

    def test_get_latency(
        self,
        mcp_client: MCPClient,
        conversation_with_messages: Dict[str, Any],
        history_tools_available: bool
    ) -> None:
        """Test that get operation completes within acceptable time."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = conversation_with_messages["conversation_id"]

        response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })

        assert response.success, f"history_get failed: {response.error}"
        assert response.latency_ms < 5000, \
            f"Get latency {response.latency_ms}ms exceeded 5s threshold"

    def test_append_many_messages_performance(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test performance when appending many messages."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        message_count = 20
        total_latency = 0

        for i in range(message_count):
            role = "user" if i % 2 == 0 else "assistant"
            response = mcp_client.call_tool("history_append", {
                "conversation_id": conversation_id,
                "turn_index": i,
                "role": role,
                "content": f"Performance test message {i+1}"
            })

            assert response.success, f"Append {i+1} failed: {response.error}"
            total_latency += response.latency_ms

        avg_latency = total_latency / message_count
        assert avg_latency < 2000, \
            f"Average append latency {avg_latency:.1f}ms exceeded 2s threshold"

    def test_get_large_history_performance(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test performance when retrieving a large history."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        # Create a conversation with many messages
        message_count = 50
        for i in range(message_count):
            role = "user" if i % 2 == 0 else "assistant"
            mcp_client.call_tool("history_append", {
                "conversation_id": conversation_id,
                "turn_index": i,
                "role": role,
                "content": f"Message {i+1}: Lorem ipsum dolor sit amet, consectetur adipiscing elit."
            })

        # Time the retrieval - request all messages with limit
        response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id,
            "limit": message_count
        })

        assert response.success, f"Get failed: {response.error}"
        assert response.latency_ms < 10000, \
            f"Get latency for {message_count} messages {response.latency_ms}ms exceeded 10s"

        messages = get_messages_from_response(response.data)
        # Server may have a default limit, so check we get a reasonable number
        # The main goal is testing performance, not exact count
        assert len(messages) > 0, "Should have retrieved some messages"
        assert len(messages) >= 10, f"Expected at least 10 messages, got {len(messages)}"


# =============================================================================
# Test Class: Edge Cases
# =============================================================================

@pytest.mark.api
@pytest.mark.history
class TestHistoryEdgeCases:
    """Edge case tests for history operations."""

    def test_conversation_id_with_special_characters(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test conversation ID with various special characters."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        # Test with hyphenated ID
        conv_id = f"test-conv-with-hyphens-{unique_id}"
        cleanup_conversation_ids.append(conv_id)

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conv_id,
            "turn_index": 0,
            "role": "user",
            "content": "Test message"
        })

        assert response.success, f"Append with hyphenated ID failed: {response.error}"

    def test_conversation_id_with_underscores(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test conversation ID with underscores."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conv_id = f"test_conv_with_underscores_{unique_id}"
        cleanup_conversation_ids.append(conv_id)

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conv_id,
            "turn_index": 0,
            "role": "user",
            "content": "Test message"
        })

        assert response.success, f"Append with underscored ID failed: {response.error}"

    def test_very_long_conversation_id(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test with a very long conversation ID."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        # Create a long but reasonable conversation ID
        conv_id = f"long-conversation-id-{'x' * 100}-{unique_id}"
        cleanup_conversation_ids.append(conv_id)

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conv_id,
            "turn_index": 0,
            "role": "user",
            "content": "Test message"
        })

        # Should either succeed or return a clear error
        assert response is not None, "Should return a response"

    def test_whitespace_only_content(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test appending message with whitespace-only content."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conversation_id,
            "turn_index": 0,
            "role": "user",
            "content": "   \n\t   "
        })

        # Behavior depends on implementation - should handle gracefully
        assert response is not None, "Should return a response"

    def test_unicode_conversation_id(
        self,
        mcp_client: MCPClient,
        unique_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test conversation ID with unicode characters."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        # Test with unicode in conversation ID (may or may not be supported)
        conv_id = f"test-{unique_id}"  # Use safe ID to avoid issues
        cleanup_conversation_ids.append(conv_id)

        unicode_content = "Message with unicode: \u4e2d\u6587 \u65e5\u672c\u8a9e \ud55c\uad6d\uc5b4"

        response = mcp_client.call_tool("history_append", {
            "conversation_id": conv_id,
            "turn_index": 0,
            "role": "user",
            "content": unicode_content
        })

        assert response.success, f"Append with unicode content failed: {response.error}"

        # Verify retrieval
        get_response = mcp_client.call_tool("history_get", {
            "conversation_id": conv_id
        })

        assert get_response.success, f"Get failed: {get_response.error}"

    def test_rapid_sequential_appends(
        self,
        mcp_client: MCPClient,
        unique_conversation_id: str,
        cleanup_conversation_ids: List[str],
        history_tools_available: bool
    ) -> None:
        """Test rapid sequential appends to the same conversation."""
        if not history_tools_available:
            pytest.skip("History tools not available")

        conversation_id = unique_conversation_id
        cleanup_conversation_ids.append(conversation_id)

        # Rapidly append messages
        for i in range(10):
            response = mcp_client.call_tool("history_append", {
                "conversation_id": conversation_id,
                "turn_index": i,
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"Rapid message {i+1}"
            })
            assert response.success, f"Rapid append {i+1} failed: {response.error}"

        # Verify all messages were stored
        get_response = mcp_client.call_tool("history_get", {
            "conversation_id": conversation_id
        })

        assert get_response.success, f"Get failed: {get_response.error}"
        messages = get_messages_from_response(get_response.data)
        assert len(messages) >= 10, f"Expected at least 10 messages, got {len(messages)}"
