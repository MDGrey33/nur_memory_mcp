"""Unit tests for custom error classes."""

import pytest
from utils.errors import (
    MCPMemoryError,
    ValidationError,
    ConfigurationError,
    EmbeddingError,
    StorageError,
    RetrievalError,
    NotFoundError
)


def test_base_error():
    """Test MCPMemoryError base exception."""
    error = MCPMemoryError("Base error message")
    assert str(error) == "Base error message"
    assert isinstance(error, Exception)


def test_validation_error():
    """Test ValidationError inherits from MCPMemoryError."""
    error = ValidationError("Invalid input")
    assert str(error) == "Invalid input"
    assert isinstance(error, MCPMemoryError)
    assert isinstance(error, Exception)


def test_configuration_error():
    """Test ConfigurationError inherits from MCPMemoryError."""
    error = ConfigurationError("Invalid config")
    assert str(error) == "Invalid config"
    assert isinstance(error, MCPMemoryError)


def test_embedding_error():
    """Test EmbeddingError inherits from MCPMemoryError."""
    error = EmbeddingError("Embedding failed")
    assert str(error) == "Embedding failed"
    assert isinstance(error, MCPMemoryError)


def test_storage_error():
    """Test StorageError inherits from MCPMemoryError."""
    error = StorageError("Storage failed")
    assert str(error) == "Storage failed"
    assert isinstance(error, MCPMemoryError)


def test_retrieval_error():
    """Test RetrievalError inherits from MCPMemoryError."""
    error = RetrievalError("Retrieval failed")
    assert str(error) == "Retrieval failed"
    assert isinstance(error, MCPMemoryError)


def test_not_found_error():
    """Test NotFoundError inherits from MCPMemoryError."""
    error = NotFoundError("Resource not found")
    assert str(error) == "Resource not found"
    assert isinstance(error, MCPMemoryError)


def test_catch_specific_error():
    """Test catching specific error types."""
    try:
        raise ValidationError("Test validation error")
    except ValidationError as e:
        assert str(e) == "Test validation error"
    except Exception:
        pytest.fail("Should have caught ValidationError specifically")


def test_catch_base_error():
    """Test catching base MCPMemoryError."""
    try:
        raise ConfigurationError("Test config error")
    except MCPMemoryError as e:
        assert str(e) == "Test config error"
    except Exception:
        pytest.fail("Should have caught as MCPMemoryError")
