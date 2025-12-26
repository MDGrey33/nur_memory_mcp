"""
Unit tests for config.py

Tests configuration loading, validation, and environment variable handling.
"""

import pytest
import os
from unittest.mock import patch

# Imports from src (path setup in conftest.py)
import config

AppConfig = config.AppConfig


class TestAppConfigDefaults:
    """Test default configuration values."""

    @patch.dict(os.environ, {}, clear=True)
    def test_default_values(self):
        """Test that defaults are correctly loaded when no env vars are set."""
        config = AppConfig.from_env()

        assert config.mcp_endpoint == 'chroma-mcp'
        assert config.memory_confidence_min == 0.7
        assert config.history_tail_n == 16
        assert config.memory_top_k == 8
        assert config.memory_max_per_window == 3
        assert config.context_token_budget is None
        assert config.log_level == 'INFO'

    @patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'}, clear=True)
    def test_partial_override(self):
        """Test that partial env var overrides work with defaults."""
        config = AppConfig.from_env()

        assert config.mcp_endpoint == 'chroma-mcp'  # default
        assert config.log_level == 'DEBUG'  # override


class TestAppConfigEnvironmentOverrides:
    """Test environment variable overrides."""

    @patch.dict(os.environ, {
        'MCP_ENDPOINT': 'custom-endpoint',
        'MEMORY_CONFIDENCE_MIN': '0.8',
        'HISTORY_TAIL_N': '20',
        'MEMORY_TOP_K': '10',
        'MEMORY_MAX_PER_WINDOW': '5',
        'CONTEXT_TOKEN_BUDGET': '4000',
        'LOG_LEVEL': 'DEBUG'
    }, clear=True)
    def test_all_env_vars_override(self):
        """Test that all environment variables can override defaults."""
        config = AppConfig.from_env()

        assert config.mcp_endpoint == 'custom-endpoint'
        assert config.memory_confidence_min == 0.8
        assert config.history_tail_n == 20
        assert config.memory_top_k == 10
        assert config.memory_max_per_window == 5
        assert config.context_token_budget == 4000
        assert config.log_level == 'DEBUG'

    @patch.dict(os.environ, {'MEMORY_CONFIDENCE_MIN': '0.5'}, clear=True)
    def test_float_parsing(self):
        """Test that float values are correctly parsed."""
        config = AppConfig.from_env()
        assert config.memory_confidence_min == 0.5
        assert isinstance(config.memory_confidence_min, float)

    @patch.dict(os.environ, {'HISTORY_TAIL_N': '32'}, clear=True)
    def test_int_parsing(self):
        """Test that integer values are correctly parsed."""
        config = AppConfig.from_env()
        assert config.history_tail_n == 32
        assert isinstance(config.history_tail_n, int)

    @patch.dict(os.environ, {'CONTEXT_TOKEN_BUDGET': ''}, clear=True)
    def test_empty_optional_value(self):
        """Test that empty optional value becomes None."""
        config = AppConfig.from_env()
        assert config.context_token_budget is None


class TestAppConfigValidation:
    """Test configuration validation rules."""

    @patch.dict(os.environ, {'MCP_ENDPOINT': ''}, clear=True)
    def test_empty_endpoint_fails(self):
        """Test that empty MCP endpoint is rejected."""
        with pytest.raises(ValueError, match="MCP_ENDPOINT cannot be empty"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'MEMORY_CONFIDENCE_MIN': '-0.1'}, clear=True)
    def test_confidence_below_range_fails(self):
        """Test that confidence below 0.0 is rejected."""
        with pytest.raises(ValueError, match="MEMORY_CONFIDENCE_MIN must be in \\[0.0, 1.0\\]"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'MEMORY_CONFIDENCE_MIN': '1.5'}, clear=True)
    def test_confidence_above_range_fails(self):
        """Test that confidence above 1.0 is rejected."""
        with pytest.raises(ValueError, match="MEMORY_CONFIDENCE_MIN must be in \\[0.0, 1.0\\]"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'MEMORY_CONFIDENCE_MIN': '0.0'}, clear=True)
    def test_confidence_at_lower_bound(self):
        """Test that confidence at 0.0 is accepted."""
        config = AppConfig.from_env()
        assert config.memory_confidence_min == 0.0

    @patch.dict(os.environ, {'MEMORY_CONFIDENCE_MIN': '1.0'}, clear=True)
    def test_confidence_at_upper_bound(self):
        """Test that confidence at 1.0 is accepted."""
        config = AppConfig.from_env()
        assert config.memory_confidence_min == 1.0

    @patch.dict(os.environ, {'HISTORY_TAIL_N': '0'}, clear=True)
    def test_history_tail_zero_fails(self):
        """Test that history_tail_n of 0 is rejected."""
        with pytest.raises(ValueError, match="HISTORY_TAIL_N must be >= 1"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'HISTORY_TAIL_N': '-5'}, clear=True)
    def test_history_tail_negative_fails(self):
        """Test that negative history_tail_n is rejected."""
        with pytest.raises(ValueError, match="HISTORY_TAIL_N must be >= 1"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'HISTORY_TAIL_N': '1'}, clear=True)
    def test_history_tail_minimum(self):
        """Test that history_tail_n of 1 is accepted."""
        config = AppConfig.from_env()
        assert config.history_tail_n == 1

    @patch.dict(os.environ, {'MEMORY_TOP_K': '0'}, clear=True)
    def test_memory_top_k_zero_fails(self):
        """Test that memory_top_k of 0 is rejected."""
        with pytest.raises(ValueError, match="MEMORY_TOP_K must be >= 1"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'MEMORY_MAX_PER_WINDOW': '0'}, clear=True)
    def test_memory_max_per_window_zero_fails(self):
        """Test that memory_max_per_window of 0 is rejected."""
        with pytest.raises(ValueError, match="MEMORY_MAX_PER_WINDOW must be >= 1"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'CONTEXT_TOKEN_BUDGET': '0'}, clear=True)
    def test_token_budget_zero_fails(self):
        """Test that token_budget of 0 is rejected."""
        with pytest.raises(ValueError, match="CONTEXT_TOKEN_BUDGET must be >= 1 or None"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'CONTEXT_TOKEN_BUDGET': '-100'}, clear=True)
    def test_token_budget_negative_fails(self):
        """Test that negative token_budget is rejected."""
        with pytest.raises(ValueError, match="CONTEXT_TOKEN_BUDGET must be >= 1 or None"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'CONTEXT_TOKEN_BUDGET': '1'}, clear=True)
    def test_token_budget_minimum(self):
        """Test that token_budget of 1 is accepted."""
        config = AppConfig.from_env()
        assert config.context_token_budget == 1

    @patch.dict(os.environ, {'LOG_LEVEL': 'INVALID'}, clear=True)
    def test_invalid_log_level_fails(self):
        """Test that invalid log level is rejected."""
        with pytest.raises(ValueError, match="LOG_LEVEL must be one of"):
            AppConfig.from_env()

    @patch.dict(os.environ, {'LOG_LEVEL': 'debug'}, clear=True)
    def test_log_level_case_insensitive(self):
        """Test that log level validation is case-insensitive."""
        config = AppConfig.from_env()
        assert config.log_level == 'debug'

    @patch.dict(os.environ, {'LOG_LEVEL': 'WARNING'}, clear=True)
    def test_log_level_warning(self):
        """Test that WARNING log level is accepted."""
        config = AppConfig.from_env()
        assert config.log_level == 'WARNING'

    @patch.dict(os.environ, {'LOG_LEVEL': 'WARN'}, clear=True)
    def test_log_level_warn(self):
        """Test that WARN log level is accepted."""
        config = AppConfig.from_env()
        assert config.log_level == 'WARN'


class TestAppConfigDirectCreation:
    """Test direct instantiation and validation."""

    def test_direct_creation_valid(self):
        """Test that valid config can be created directly."""
        config = AppConfig(
            mcp_endpoint='test-endpoint',
            memory_confidence_min=0.7,
            history_tail_n=16,
            memory_top_k=8,
            memory_max_per_window=3,
            context_token_budget=None,
            log_level='INFO'
        )
        config.validate()  # Should not raise

    def test_validate_can_be_called_multiple_times(self):
        """Test that validate() is idempotent."""
        config = AppConfig(
            mcp_endpoint='test-endpoint',
            memory_confidence_min=0.7,
            history_tail_n=16,
            memory_top_k=8,
            memory_max_per_window=3,
            context_token_budget=None,
            log_level='INFO'
        )
        config.validate()
        config.validate()  # Should not raise

    def test_direct_creation_invalid_endpoint(self):
        """Test that invalid endpoint fails validation."""
        config = AppConfig(
            mcp_endpoint='',
            memory_confidence_min=0.7,
            history_tail_n=16,
            memory_top_k=8,
            memory_max_per_window=3,
            context_token_budget=None,
            log_level='INFO'
        )
        with pytest.raises(ValueError, match="MCP_ENDPOINT cannot be empty"):
            config.validate()
