"""Unit tests for configuration module."""

import pytest
import os
from config import Config, load_config, validate_config


# ============================================================================
# Load Config Tests
# ============================================================================

def test_load_config_success(monkeypatch):
    """Test load_config with valid environment variables."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")

    config = load_config()

    assert isinstance(config, Config)
    assert config.openai_api_key == "test-key-123"
    assert config.openai_embed_model == "text-embedding-3-large"
    assert config.openai_embed_dims == 3072


def test_load_config_missing_api_key(monkeypatch):
    """Test load_config fails without OPENAI_API_KEY."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable is required"):
        load_config()


def test_load_config_custom_values(monkeypatch):
    """Test load_config with custom environment variables."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
    monkeypatch.setenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("OPENAI_EMBED_DIMS", "1024")
    monkeypatch.setenv("SINGLE_PIECE_MAX_TOKENS", "2000")
    monkeypatch.setenv("CHUNK_TARGET_TOKENS", "1500")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "200")
    monkeypatch.setenv("CHROMA_HOST", "remote-host")
    monkeypatch.setenv("CHROMA_PORT", "9000")
    monkeypatch.setenv("MCP_PORT", "4000")
    monkeypatch.setenv("RRF_CONSTANT", "100")

    config = load_config()

    assert config.openai_embed_model == "text-embedding-3-small"
    assert config.openai_embed_dims == 1024
    assert config.single_piece_max_tokens == 2000
    assert config.chunk_target_tokens == 1500
    assert config.chunk_overlap_tokens == 200
    assert config.chroma_host == "remote-host"
    assert config.chroma_port == 9000
    assert config.mcp_port == 4000
    assert config.rrf_constant == 100


def test_load_config_defaults(monkeypatch):
    """Test load_config uses default values."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")

    config = load_config()

    # Check defaults
    assert config.openai_embed_model == "text-embedding-3-large"
    assert config.openai_embed_dims == 3072
    assert config.openai_timeout == 30
    assert config.openai_max_retries == 3
    assert config.openai_batch_size == 100
    assert config.single_piece_max_tokens == 1200
    assert config.chunk_target_tokens == 900
    assert config.chunk_overlap_tokens == 100
    assert config.chroma_host == "localhost"
    assert config.chroma_port == 8001
    assert config.mcp_port == 3000
    assert config.log_level == "INFO"
    assert config.rrf_constant == 60


# ============================================================================
# Validate Config Tests
# ============================================================================

def test_validate_config_success(test_config):
    """Test validate_config with valid configuration."""
    # Should not raise any exception
    validate_config(test_config)


def test_validate_config_invalid_embed_dims(test_config):
    """Test validate_config fails with invalid embedding dimensions."""
    test_config.openai_embed_dims = 512  # Invalid value

    with pytest.raises(ValueError, match="Invalid OPENAI_EMBED_DIMS"):
        validate_config(test_config)


def test_validate_config_valid_embed_dims(test_config):
    """Test validate_config accepts all valid embedding dimensions."""
    for dims in [256, 1024, 3072]:
        test_config.openai_embed_dims = dims
        validate_config(test_config)  # Should not raise


def test_validate_config_chunk_target_too_large(test_config):
    """Test validate_config fails if chunk_target >= single_piece_max."""
    test_config.chunk_target_tokens = 1200
    test_config.single_piece_max_tokens = 1200

    with pytest.raises(ValueError, match="CHUNK_TARGET_TOKENS.*must be less than"):
        validate_config(test_config)


def test_validate_config_chunk_overlap_too_large(test_config):
    """Test validate_config fails if chunk_overlap >= chunk_target."""
    test_config.chunk_overlap_tokens = 900
    test_config.chunk_target_tokens = 900

    with pytest.raises(ValueError, match="CHUNK_OVERLAP_TOKENS.*must be less than"):
        validate_config(test_config)


def test_validate_config_batch_size_too_large(test_config):
    """Test validate_config fails if batch_size exceeds OpenAI limit."""
    test_config.openai_batch_size = 3000

    with pytest.raises(ValueError, match="OPENAI_BATCH_SIZE.*exceeds OpenAI limit"):
        validate_config(test_config)


def test_validate_config_invalid_log_level(test_config):
    """Test validate_config fails with invalid log level."""
    test_config.log_level = "INVALID"

    with pytest.raises(ValueError, match="Invalid LOG_LEVEL"):
        validate_config(test_config)


def test_validate_config_valid_log_levels(test_config):
    """Test validate_config accepts all valid log levels."""
    for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        test_config.log_level = level
        validate_config(test_config)  # Should not raise


def test_validate_config_case_insensitive_log_level(test_config):
    """Test validate_config handles lowercase log levels."""
    test_config.log_level = "info"
    validate_config(test_config)  # Should not raise (uppercase check)
