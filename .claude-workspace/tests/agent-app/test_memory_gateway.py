"""
Unit tests for memory_gateway.py

Tests MCP transport layer with mocked HTTP calls.
Uses respx to mock httpx requests.
"""

import pytest
import httpx
import respx
from unittest.mock import AsyncMock, patch

# Imports from src (path setup in conftest.py)
import memory_gateway
import exceptions

ChromaMcpGateway = memory_gateway.ChromaMcpGateway
MCPError = exceptions.MCPError
MCPConnectionError = exceptions.ConnectionError


class TestChromaMcpGatewayInitialization:
    """Test gateway initialization."""

    def test_initialization_with_hostname(self):
        """Test initialization with simple hostname."""
        gateway = ChromaMcpGateway("chroma-mcp")

        assert gateway.mcp_endpoint == "chroma-mcp"
        assert gateway.base_url == "http://chroma-mcp:8080"
        assert gateway.timeout == 30.0

    def test_initialization_with_http_url(self):
        """Test initialization with full HTTP URL."""
        gateway = ChromaMcpGateway("http://custom-host:9000")

        assert gateway.base_url == "http://custom-host:9000"

    def test_initialization_with_https_url(self):
        """Test initialization with HTTPS URL."""
        gateway = ChromaMcpGateway("https://secure-host:9000")

        assert gateway.base_url == "https://secure-host:9000"

    def test_initialization_with_custom_timeout(self):
        """Test initialization with custom timeout."""
        gateway = ChromaMcpGateway("chroma-mcp", timeout=60.0)

        assert gateway.timeout == 60.0

    def test_initialization_empty_endpoint_fails(self):
        """Test that empty endpoint raises error."""
        with pytest.raises(ValueError, match="mcp_endpoint cannot be empty"):
            ChromaMcpGateway("")

    def test_client_initially_none(self):
        """Test that client is None before context manager."""
        gateway = ChromaMcpGateway("chroma-mcp")

        assert gateway.client is None


@pytest.mark.asyncio
class TestChromaMcpGatewayContextManager:
    """Test async context manager functionality."""

    async def test_context_manager_creates_client(self):
        """Test that entering context creates client."""
        gateway = ChromaMcpGateway("chroma-mcp")

        async with gateway:
            assert gateway.client is not None
            assert isinstance(gateway.client, httpx.AsyncClient)

    async def test_context_manager_closes_client(self):
        """Test that exiting context closes client."""
        gateway = ChromaMcpGateway("chroma-mcp")

        async with gateway:
            client = gateway.client

        # Client should be closed after exiting context
        assert client.is_closed


@pytest.mark.asyncio
@respx.mock
class TestChromaMcpGatewayEnsureCollections:
    """Test ensure_collections functionality."""

    async def test_ensure_collections_all_exist(self):
        """Test when all collections already exist."""
        # Mock list collections endpoint
        respx.get("http://chroma-mcp:8000/api/v1/collections").mock(
            return_value=httpx.Response(200, json=["history", "memory"])
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            await gateway.ensure_collections(["history", "memory"])

        # Should not attempt to create any collections
        assert len(respx.calls) == 1  # Only the list call

    async def test_ensure_collections_creates_missing(self):
        """Test creating missing collections."""
        # Mock list collections (empty)
        respx.get("http://chroma-mcp:8000/api/v1/collections").mock(
            return_value=httpx.Response(200, json=[])
        )

        # Mock create collection
        respx.post("http://chroma-mcp:8000/api/v1/collections").mock(
            return_value=httpx.Response(200, json={"name": "history"})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            await gateway.ensure_collections(["history"])

        # Should call list once and create once
        assert len(respx.calls) == 2

    async def test_ensure_collections_partial_exist(self):
        """Test when some collections exist and some don't."""
        # Mock list collections (only history exists)
        respx.get("http://chroma-mcp:8000/api/v1/collections").mock(
            return_value=httpx.Response(200, json=["history"])
        )

        # Mock create collection for memory
        respx.post("http://chroma-mcp:8000/api/v1/collections").mock(
            return_value=httpx.Response(200, json={"name": "memory"})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            await gateway.ensure_collections(["history", "memory"])

        # Should call list once and create once (only for memory)
        assert len(respx.calls) == 2

    async def test_ensure_collections_connection_error(self):
        """Test connection error when listing collections."""
        # Mock connection failure
        respx.get("http://chroma-mcp:8000/api/v1/collections").mock(
            side_effect=httpx.ConnectError("Connection failed")
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(MCPConnectionError, match="Failed to list collections"):
                await gateway.ensure_collections(["history"])

    async def test_ensure_collections_create_error(self):
        """Test error when creating collection."""
        # Mock list collections (empty)
        respx.get("http://chroma-mcp:8000/api/v1/collections").mock(
            return_value=httpx.Response(200, json=[])
        )

        # Mock create failure
        respx.post("http://chroma-mcp:8000/api/v1/collections").mock(
            return_value=httpx.Response(500, json={"error": "Server error"})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(MCPError, match="Failed to create collection"):
                await gateway.ensure_collections(["history"])


@pytest.mark.asyncio
@respx.mock
class TestChromaMcpGatewayAppendHistory:
    """Test append_history functionality."""

    async def test_append_history_success(self):
        """Test successfully appending history."""
        # Mock add document endpoint
        respx.post("http://chroma-mcp:8000/api/v1/collections/history/add").mock(
            return_value=httpx.Response(200, json={"ids": ["msg_001"]})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            doc_id = await gateway.append_history(
                conversation_id="conv_123",
                role="user",
                text="Test message",
                turn_index=0,
                ts="2025-12-25T12:00:00Z",
                message_id="msg_001"
            )

        assert doc_id == "msg_001"

    async def test_append_history_without_message_id(self):
        """Test appending history without message_id generates ID."""
        respx.post("http://chroma-mcp:8000/api/v1/collections/history/add").mock(
            return_value=httpx.Response(200, json={"ids": ["conv_123_0"]})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            doc_id = await gateway.append_history(
                conversation_id="conv_123",
                role="user",
                text="Test message",
                turn_index=0,
                ts="2025-12-25T12:00:00Z"
            )

        assert doc_id == "conv_123_0"

    async def test_append_history_validates_conversation_id(self):
        """Test that empty conversation_id is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="conversation_id cannot be empty"):
                await gateway.append_history(
                    conversation_id="",
                    role="user",
                    text="Test",
                    turn_index=0,
                    ts="2025-12-25T12:00:00Z"
                )

    async def test_append_history_validates_role(self):
        """Test that invalid role is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="role must be one of"):
                await gateway.append_history(
                    conversation_id="conv_123",
                    role="invalid",
                    text="Test",
                    turn_index=0,
                    ts="2025-12-25T12:00:00Z"
                )

    async def test_append_history_validates_text(self):
        """Test that empty text is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="text cannot be empty"):
                await gateway.append_history(
                    conversation_id="conv_123",
                    role="user",
                    text="",
                    turn_index=0,
                    ts="2025-12-25T12:00:00Z"
                )

    async def test_append_history_validates_turn_index(self):
        """Test that negative turn_index is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="turn_index must be non-negative"):
                await gateway.append_history(
                    conversation_id="conv_123",
                    role="user",
                    text="Test",
                    turn_index=-1,
                    ts="2025-12-25T12:00:00Z"
                )

    async def test_append_history_http_error(self):
        """Test error handling for HTTP errors."""
        respx.post("http://chroma-mcp:8000/api/v1/collections/history/add").mock(
            return_value=httpx.Response(500, json={"error": "Server error"})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(MCPError, match="Failed to append history"):
                await gateway.append_history(
                    conversation_id="conv_123",
                    role="user",
                    text="Test",
                    turn_index=0,
                    ts="2025-12-25T12:00:00Z"
                )


@pytest.mark.asyncio
@respx.mock
class TestChromaMcpGatewayTailHistory:
    """Test tail_history functionality."""

    async def test_tail_history_success(self):
        """Test successfully retrieving history tail."""
        mock_response = {
            "ids": ["msg_001", "msg_002"],
            "documents": ["Message 1", "Message 2"],
            "metadatas": [
                {"conversation_id": "conv_123", "role": "user", "turn_index": 1, "ts": "2025-12-25T12:00:00Z"},
                {"conversation_id": "conv_123", "role": "assistant", "turn_index": 0, "ts": "2025-12-25T11:59:00Z"}
            ]
        }

        respx.post("http://chroma-mcp:8000/api/v1/collections/history/get").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            results = await gateway.tail_history("conv_123", 2)

        # Should return 2 results in chronological order (reversed from DESC query)
        assert len(results) == 2
        assert results[0]["metadata"]["turn_index"] == 0  # Oldest first after reverse
        assert results[1]["metadata"]["turn_index"] == 1

    async def test_tail_history_empty_results(self):
        """Test retrieving history when none exists."""
        mock_response = {
            "ids": [],
            "documents": [],
            "metadatas": []
        }

        respx.post("http://chroma-mcp:8000/api/v1/collections/history/get").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            results = await gateway.tail_history("conv_123", 10)

        assert len(results) == 0

    async def test_tail_history_validates_n(self):
        """Test that n < 1 is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="n must be >= 1"):
                await gateway.tail_history("conv_123", 0)

    async def test_tail_history_http_error(self):
        """Test error handling for HTTP errors."""
        respx.post("http://chroma-mcp:8000/api/v1/collections/history/get").mock(
            return_value=httpx.Response(500, json={"error": "Server error"})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(MCPError, match="Failed to retrieve history"):
                await gateway.tail_history("conv_123", 10)


@pytest.mark.asyncio
@respx.mock
class TestChromaMcpGatewayWriteMemory:
    """Test write_memory functionality."""

    async def test_write_memory_success(self):
        """Test successfully writing memory."""
        respx.post("http://chroma-mcp:8000/api/v1/collections/memory/add").mock(
            return_value=httpx.Response(200, json={"ids": ["mem_001"]})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            mem_id = await gateway.write_memory(
                text="User prefers Docker",
                memory_type="preference",
                confidence=0.85,
                ts="2025-12-25T12:00:00Z"
            )

        assert mem_id == "mem_001"

    async def test_write_memory_with_all_fields(self):
        """Test writing memory with all optional fields."""
        respx.post("http://chroma-mcp:8000/api/v1/collections/memory/add").mock(
            return_value=httpx.Response(200, json={"ids": ["mem_001"]})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            mem_id = await gateway.write_memory(
                text="User prefers Docker",
                memory_type="preference",
                confidence=0.85,
                ts="2025-12-25T12:00:00Z",
                conversation_id="conv_123",
                entities="Docker",
                source="chat",
                tags="deployment,tools"
            )

        assert mem_id == "mem_001"

    async def test_write_memory_validates_text(self):
        """Test that empty text is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="text cannot be empty"):
                await gateway.write_memory(
                    text="",
                    memory_type="preference",
                    confidence=0.85,
                    ts="2025-12-25T12:00:00Z"
                )

    async def test_write_memory_validates_type(self):
        """Test that invalid memory type is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="memory_type must be one of"):
                await gateway.write_memory(
                    text="Test",
                    memory_type="invalid",
                    confidence=0.85,
                    ts="2025-12-25T12:00:00Z"
                )

    async def test_write_memory_validates_confidence(self):
        """Test that invalid confidence is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="confidence must be in \\[0.0, 1.0\\]"):
                await gateway.write_memory(
                    text="Test",
                    memory_type="preference",
                    confidence=1.5,
                    ts="2025-12-25T12:00:00Z"
                )

    async def test_write_memory_http_error(self):
        """Test error handling for HTTP errors."""
        respx.post("http://chroma-mcp:8000/api/v1/collections/memory/add").mock(
            return_value=httpx.Response(500, json={"error": "Server error"})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(MCPError, match="Failed to write memory"):
                await gateway.write_memory(
                    text="Test",
                    memory_type="preference",
                    confidence=0.85,
                    ts="2025-12-25T12:00:00Z"
                )


@pytest.mark.asyncio
@respx.mock
class TestChromaMcpGatewayRecallMemory:
    """Test recall_memory functionality."""

    async def test_recall_memory_success(self):
        """Test successfully recalling memories."""
        mock_response = {
            "ids": [["mem_001", "mem_002"]],
            "documents": [["Memory 1", "Memory 2"]],
            "metadatas": [[
                {"type": "preference", "confidence": 0.85, "ts": "2025-12-25T12:00:00Z"},
                {"type": "fact", "confidence": 0.9, "ts": "2025-12-25T12:00:01Z"}
            ]],
            "distances": [[0.1, 0.2]]
        }

        respx.post("http://chroma-mcp:8000/api/v1/collections/memory/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            results = await gateway.recall_memory(
                query_text="What does user prefer?",
                k=8,
                min_confidence=0.7
            )

        assert len(results) == 2
        assert results[0]["document"] == "Memory 1"
        assert results[0]["distance"] == 0.1

    async def test_recall_memory_with_conversation_filter(self):
        """Test recalling memories with conversation filter."""
        mock_response = {
            "ids": [["mem_001"]],
            "documents": [["Memory 1"]],
            "metadatas": [[{"type": "preference", "confidence": 0.85, "ts": "2025-12-25T12:00:00Z"}]],
            "distances": [[0.1]]
        }

        respx.post("http://chroma-mcp:8000/api/v1/collections/memory/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            results = await gateway.recall_memory(
                query_text="Test query",
                k=8,
                min_confidence=0.7,
                conversation_id="conv_123"
            )

        assert len(results) == 1

    async def test_recall_memory_empty_results(self):
        """Test recalling when no memories match."""
        mock_response = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }

        respx.post("http://chroma-mcp:8000/api/v1/collections/memory/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            results = await gateway.recall_memory(
                query_text="Test query",
                k=8,
                min_confidence=0.7
            )

        assert len(results) == 0

    async def test_recall_memory_validates_k(self):
        """Test that k < 1 is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="k must be >= 1"):
                await gateway.recall_memory("Test", 0, 0.7)

    async def test_recall_memory_validates_confidence(self):
        """Test that invalid confidence is rejected."""
        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(ValueError, match="min_confidence must be in \\[0.0, 1.0\\]"):
                await gateway.recall_memory("Test", 8, 1.5)

    async def test_recall_memory_http_error(self):
        """Test error handling for HTTP errors."""
        respx.post("http://chroma-mcp:8000/api/v1/collections/memory/query").mock(
            return_value=httpx.Response(500, json={"error": "Server error"})
        )

        gateway = ChromaMcpGateway("chroma-mcp")
        async with gateway:
            with pytest.raises(MCPError, match="Failed to recall memories"):
                await gateway.recall_memory("Test", 8, 0.7)
