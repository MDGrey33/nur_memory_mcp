"""Unit tests for EmbeddingService."""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch
import openai

from services.embedding_service import EmbeddingService
from utils.errors import ValidationError, ConfigurationError, EmbeddingError


# ============================================================================
# Initialization Tests
# ============================================================================

def test_init_with_valid_config():
    """Test initialization with valid configuration."""
    service = EmbeddingService(
        api_key="test-key",
        model="text-embedding-3-large",
        dimensions=3072,
        timeout=30,
        max_retries=3,
        batch_size=100
    )

    assert service.model == "text-embedding-3-large"
    assert service.dimensions == 3072
    assert service.max_retries == 3
    assert service.batch_size == 100
    assert service.timeout == 30


def test_init_without_api_key():
    """Test initialization fails without API key."""
    with pytest.raises(ConfigurationError, match="API key is required"):
        EmbeddingService(api_key="", model="text-embedding-3-large")


def test_init_limits_batch_size():
    """Test batch size is capped at OpenAI limit."""
    service = EmbeddingService(
        api_key="test-key",
        batch_size=5000  # Exceeds OpenAI limit
    )
    assert service.batch_size == 2048  # Should be capped


# ============================================================================
# Single Embedding Tests
# ============================================================================

@pytest.mark.mock_openai
def test_generate_embedding_success(embedding_service):
    """Test successful embedding generation."""
    result = embedding_service.generate_embedding("test text")

    assert isinstance(result, list)
    assert len(result) == 3072
    assert all(isinstance(x, float) for x in result)
    embedding_service.client.embeddings.create.assert_called_once()


@pytest.mark.mock_openai
def test_generate_embedding_empty_text(embedding_service):
    """Test embedding generation fails with empty text."""
    with pytest.raises(ValidationError, match="cannot be empty"):
        embedding_service.generate_embedding("")


@pytest.mark.mock_openai
def test_generate_embedding_whitespace_only(embedding_service):
    """Test embedding generation fails with whitespace-only text."""
    with pytest.raises(ValidationError, match="cannot be empty"):
        embedding_service.generate_embedding("   \n\t  ")


# ============================================================================
# Batch Embedding Tests
# ============================================================================

@pytest.mark.mock_openai
def test_generate_embeddings_batch_success(mock_openai_batch_client):
    """Test successful batch embedding generation."""
    service = EmbeddingService(api_key="test-key")
    service.client = mock_openai_batch_client

    texts = ["text 1", "text 2", "text 3"]
    results = service.generate_embeddings_batch(texts)

    assert len(results) == 3
    assert all(isinstance(emb, list) for emb in results)
    assert all(len(emb) == 3072 for emb in results)


@pytest.mark.mock_openai
def test_generate_embeddings_batch_empty_list(embedding_service):
    """Test batch generation with empty list."""
    results = embedding_service.generate_embeddings_batch([])
    assert results == []


@pytest.mark.mock_openai
def test_generate_embeddings_batch_with_empty_text(embedding_service):
    """Test batch generation fails if any text is empty."""
    texts = ["valid text", "", "another valid"]

    with pytest.raises(ValidationError, match="at index 1 is empty"):
        embedding_service.generate_embeddings_batch(texts)


@pytest.mark.mock_openai
def test_generate_embeddings_batch_splits_large_batches(mock_openai_batch_client):
    """Test batch generation splits large batches correctly."""
    service = EmbeddingService(api_key="test-key", batch_size=10)
    service.client = mock_openai_batch_client

    # 25 texts with batch_size=10 should require 3 API calls
    texts = [f"text {i}" for i in range(25)]
    results = service.generate_embeddings_batch(texts)

    assert len(results) == 25
    # Should have made 3 calls (10 + 10 + 5)
    assert service.client.embeddings.create.call_count == 3


# ============================================================================
# Retry Logic Tests
# ============================================================================

@pytest.mark.mock_openai
def test_retry_on_rate_limit(mock_openai_client):
    """Test retry logic on rate limit errors."""
    service = EmbeddingService(api_key="test-key", max_retries=3)
    service.client = mock_openai_client

    # First 2 calls fail with rate limit, 3rd succeeds
    mock_response = Mock()
    mock_response.data = [Mock(embedding=[0.1] * 3072)]

    mock_openai_client.embeddings.create.side_effect = [
        openai.RateLimitError("Rate limit exceeded", response=Mock(), body={}),
        openai.RateLimitError("Rate limit exceeded", response=Mock(), body={}),
        mock_response
    ]

    with patch("time.sleep"):  # Mock sleep to speed up test
        result = service.generate_embedding("test")

    assert len(result) == 3072
    assert mock_openai_client.embeddings.create.call_count == 3


@pytest.mark.mock_openai
def test_no_retry_on_auth_error(mock_openai_client):
    """Test no retry on authentication errors."""
    service = EmbeddingService(api_key="test-key", max_retries=3)
    service.client = mock_openai_client

    mock_openai_client.embeddings.create.side_effect = openai.AuthenticationError(
        "Invalid API key", response=Mock(), body={}
    )

    with pytest.raises(ConfigurationError, match="Invalid OpenAI API key"):
        service.generate_embedding("test")

    # Should only try once (no retries)
    assert mock_openai_client.embeddings.create.call_count == 1


@pytest.mark.mock_openai
def test_no_retry_on_bad_request(mock_openai_client):
    """Test no retry on bad request errors."""
    service = EmbeddingService(api_key="test-key", max_retries=3)
    service.client = mock_openai_client

    mock_openai_client.embeddings.create.side_effect = openai.BadRequestError(
        "Invalid input", response=Mock(), body={}
    )

    with pytest.raises(ValidationError, match="Invalid input"):
        service.generate_embedding("test")

    # Should only try once (no retries)
    assert mock_openai_client.embeddings.create.call_count == 1


@pytest.mark.mock_openai
def test_retry_on_timeout(mock_openai_client):
    """Test retry logic on timeout errors."""
    service = EmbeddingService(api_key="test-key", max_retries=3)
    service.client = mock_openai_client

    mock_response = Mock()
    mock_response.data = [Mock(embedding=[0.1] * 3072)]

    mock_openai_client.embeddings.create.side_effect = [
        openai.APITimeoutError("Timeout"),
        mock_response
    ]

    with patch("time.sleep"):
        result = service.generate_embedding("test")

    assert len(result) == 3072
    assert mock_openai_client.embeddings.create.call_count == 2


@pytest.mark.mock_openai
def test_retry_on_connection_error(mock_openai_client):
    """Test retry logic on connection errors."""
    service = EmbeddingService(api_key="test-key", max_retries=3)
    service.client = mock_openai_client

    mock_response = Mock()
    mock_response.data = [Mock(embedding=[0.1] * 3072)]

    # APIConnectionError requires request parameter
    conn_error = openai.APIConnectionError(request=Mock())
    mock_openai_client.embeddings.create.side_effect = [
        conn_error,
        mock_response
    ]

    with patch("time.sleep"):
        result = service.generate_embedding("test")

    assert len(result) == 3072
    assert mock_openai_client.embeddings.create.call_count == 2


@pytest.mark.mock_openai
def test_retry_exhausted(mock_openai_client):
    """Test error raised after max retries exhausted."""
    service = EmbeddingService(api_key="test-key", max_retries=3)
    service.client = mock_openai_client

    mock_openai_client.embeddings.create.side_effect = openai.RateLimitError(
        "Rate limit", response=Mock(), body={}
    )

    with patch("time.sleep"):
        with pytest.raises(EmbeddingError, match="after 3 attempts"):
            service.generate_embedding("test")

    assert mock_openai_client.embeddings.create.call_count == 3


@pytest.mark.mock_openai
def test_exponential_backoff(mock_openai_client):
    """Test exponential backoff timing."""
    service = EmbeddingService(api_key="test-key", max_retries=3)
    service.client = mock_openai_client

    mock_openai_client.embeddings.create.side_effect = openai.RateLimitError(
        "Rate limit", response=Mock(), body={}
    )

    sleep_times = []

    def mock_sleep(duration):
        sleep_times.append(duration)

    with patch("time.sleep", side_effect=mock_sleep):
        with pytest.raises(EmbeddingError):
            service.generate_embedding("test")

    # Should have exponential backoff: 1s, 2s, 4s
    assert sleep_times == [1.0, 2.0]  # Only 2 sleeps (after 1st and 2nd failure)


# ============================================================================
# Model Info and Health Check Tests
# ============================================================================

def test_get_model_info(embedding_service):
    """Test get_model_info returns correct information."""
    info = embedding_service.get_model_info()

    assert info["provider"] == "openai"
    assert info["model"] == "text-embedding-3-large"
    assert info["dimensions"] == 3072
    assert info["batch_size"] == 100
    assert info["timeout"] == 30
    assert info["max_retries"] == 3


@pytest.mark.mock_openai
def test_health_check_healthy(embedding_service):
    """Test health check with healthy service."""
    result = embedding_service.health_check()

    assert result["status"] == "healthy"
    assert result["model"] == "text-embedding-3-large"
    assert result["dimensions"] == 3072
    assert "api_latency_ms" in result
    assert isinstance(result["api_latency_ms"], int)


@pytest.mark.mock_openai
def test_health_check_unhealthy(mock_openai_client):
    """Test health check with unhealthy service."""
    service = EmbeddingService(api_key="test-key")
    service.client = mock_openai_client

    mock_openai_client.embeddings.create.side_effect = Exception("API Error")

    result = service.health_check()

    assert result["status"] == "unhealthy"
    assert result["model"] == "text-embedding-3-large"
    assert "error" in result
    assert "API Error" in result["error"]
