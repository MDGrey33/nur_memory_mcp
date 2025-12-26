"""Unit tests for ChromaClientManager."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from storage.chroma_client import ChromaClientManager


def test_init():
    """Test ChromaClientManager initialization."""
    manager = ChromaClientManager(host="localhost", port=8001)

    assert manager.host == "localhost"
    assert manager.port == 8001
    assert manager._client is None


@patch("storage.chroma_client.chromadb.HttpClient")
def test_get_client_creates_new(mock_http_client):
    """Test get_client creates new client if none exists."""
    mock_client = MagicMock()
    mock_client.heartbeat.return_value = True
    mock_http_client.return_value = mock_client

    manager = ChromaClientManager(host="localhost", port=8001)
    client = manager.get_client()

    assert client is not None
    assert manager._client is not None
    mock_http_client.assert_called_once_with(host="localhost", port=8001)
    mock_client.heartbeat.assert_called_once()


@patch("storage.chroma_client.chromadb.HttpClient")
def test_get_client_reuses_existing(mock_http_client):
    """Test get_client reuses existing client."""
    mock_client = MagicMock()
    mock_client.heartbeat.return_value = True
    mock_http_client.return_value = mock_client

    manager = ChromaClientManager(host="localhost", port=8001)

    # Get client twice
    client1 = manager.get_client()
    client2 = manager.get_client()

    # Should only create once
    assert client1 is client2
    mock_http_client.assert_called_once()


@patch("storage.chroma_client.chromadb.HttpClient")
def test_get_client_connection_error(mock_http_client):
    """Test get_client raises ConnectionError on failure."""
    mock_client = MagicMock()
    mock_client.heartbeat.side_effect = Exception("Connection failed")
    mock_http_client.return_value = mock_client

    manager = ChromaClientManager(host="localhost", port=8001)

    with pytest.raises(ConnectionError, match="Cannot connect to ChromaDB"):
        manager.get_client()


@patch("storage.chroma_client.chromadb.HttpClient")
def test_health_check_healthy(mock_http_client):
    """Test health_check with healthy connection."""
    mock_client = MagicMock()
    mock_client.heartbeat.return_value = True
    mock_http_client.return_value = mock_client

    manager = ChromaClientManager(host="localhost", port=8001)
    health = manager.health_check()

    assert health["status"] == "healthy"
    assert health["host"] == "localhost"
    assert health["port"] == 8001
    assert "latency_ms" in health
    assert isinstance(health["latency_ms"], int)


@patch("storage.chroma_client.chromadb.HttpClient")
def test_health_check_unhealthy(mock_http_client):
    """Test health_check with unhealthy connection."""
    mock_client = MagicMock()
    mock_client.heartbeat.side_effect = Exception("Connection failed")
    mock_http_client.return_value = mock_client

    manager = ChromaClientManager(host="localhost", port=8001)
    health = manager.health_check()

    assert health["status"] == "unhealthy"
    assert health["host"] == "localhost"
    assert health["port"] == 8001
    assert "error" in health
    assert "Connection failed" in health["error"]


@patch("storage.chroma_client.chromadb.HttpClient")
def test_close(mock_http_client):
    """Test close method."""
    mock_client = MagicMock()
    mock_client.heartbeat.return_value = True
    mock_http_client.return_value = mock_client

    manager = ChromaClientManager(host="localhost", port=8001)
    manager.get_client()  # Create client

    assert manager._client is not None

    manager.close()

    assert manager._client is None
