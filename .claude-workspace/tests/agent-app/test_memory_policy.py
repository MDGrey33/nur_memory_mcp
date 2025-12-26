"""
Unit tests for memory_policy.py

Tests policy decisions, confidence gating, and rate limiting.
"""

import pytest
from datetime import datetime
from unittest.mock import patch

# Imports from src (path setup in conftest.py)
import memory_policy

MemoryPolicy = memory_policy.MemoryPolicy


class TestMemoryPolicyInitialization:
    """Test MemoryPolicy initialization."""

    def test_default_initialization(self):
        """Test initialization with default parameters."""
        policy = MemoryPolicy()

        assert policy.min_confidence == 0.7
        assert policy.max_per_window == 3
        assert isinstance(policy._window_counts, dict)
        assert len(policy._window_counts) == 0

    def test_custom_initialization(self):
        """Test initialization with custom parameters."""
        policy = MemoryPolicy(min_confidence=0.8, max_per_window=5)

        assert policy.min_confidence == 0.8
        assert policy.max_per_window == 5

    def test_invalid_min_confidence_below_range(self):
        """Test that min_confidence below 0.0 raises error."""
        with pytest.raises(ValueError, match="min_confidence must be in \\[0.0, 1.0\\]"):
            MemoryPolicy(min_confidence=-0.1)

    def test_invalid_min_confidence_above_range(self):
        """Test that min_confidence above 1.0 raises error."""
        with pytest.raises(ValueError, match="min_confidence must be in \\[0.0, 1.0\\]"):
            MemoryPolicy(min_confidence=1.5)

    def test_min_confidence_at_bounds(self):
        """Test that min_confidence at 0.0 and 1.0 are valid."""
        policy1 = MemoryPolicy(min_confidence=0.0)
        policy2 = MemoryPolicy(min_confidence=1.0)

        assert policy1.min_confidence == 0.0
        assert policy2.min_confidence == 1.0

    def test_invalid_max_per_window_zero(self):
        """Test that max_per_window of 0 raises error."""
        with pytest.raises(ValueError, match="max_per_window must be >= 1"):
            MemoryPolicy(max_per_window=0)

    def test_invalid_max_per_window_negative(self):
        """Test that negative max_per_window raises error."""
        with pytest.raises(ValueError, match="max_per_window must be >= 1"):
            MemoryPolicy(max_per_window=-5)

    def test_max_per_window_minimum(self):
        """Test that max_per_window of 1 is valid."""
        policy = MemoryPolicy(max_per_window=1)
        assert policy.max_per_window == 1


class TestMemoryPolicyValidateMemoryType:
    """Test memory type validation."""

    def test_valid_memory_types(self):
        """Test that all valid memory types are recognized."""
        policy = MemoryPolicy()

        assert policy.validate_memory_type("preference") is True
        assert policy.validate_memory_type("fact") is True
        assert policy.validate_memory_type("project") is True
        assert policy.validate_memory_type("decision") is True

    def test_invalid_memory_type(self):
        """Test that invalid memory type is rejected."""
        policy = MemoryPolicy()

        assert policy.validate_memory_type("invalid") is False
        assert policy.validate_memory_type("") is False
        assert policy.validate_memory_type("PREFERENCE") is False


class TestMemoryPolicyShouldStore:
    """Test should_store decision logic."""

    def test_should_store_valid_above_threshold(self):
        """Test that memory above threshold is accepted."""
        policy = MemoryPolicy(min_confidence=0.7)

        assert policy.should_store("fact", 0.8) is True
        assert policy.should_store("preference", 0.9) is True
        assert policy.should_store("decision", 1.0) is True

    def test_should_store_at_threshold(self):
        """Test that memory at exactly threshold is accepted."""
        policy = MemoryPolicy(min_confidence=0.7)

        assert policy.should_store("fact", 0.7) is True

    def test_should_store_below_threshold(self):
        """Test that memory below threshold is rejected."""
        policy = MemoryPolicy(min_confidence=0.7)

        assert policy.should_store("fact", 0.69) is False
        assert policy.should_store("preference", 0.5) is False
        assert policy.should_store("decision", 0.0) is False

    def test_should_store_invalid_type(self):
        """Test that invalid memory type is rejected."""
        policy = MemoryPolicy(min_confidence=0.7)

        assert policy.should_store("invalid_type", 0.9) is False
        assert policy.should_store("", 0.9) is False

    def test_should_store_all_memory_types(self):
        """Test should_store works for all valid memory types."""
        policy = MemoryPolicy(min_confidence=0.7)

        for memory_type in ["preference", "fact", "project", "decision"]:
            assert policy.should_store(memory_type, 0.8) is True

    def test_should_store_zero_confidence_threshold(self):
        """Test behavior with zero confidence threshold."""
        policy = MemoryPolicy(min_confidence=0.0)

        assert policy.should_store("fact", 0.0) is True
        assert policy.should_store("fact", 0.1) is True

    def test_should_store_max_confidence_threshold(self):
        """Test behavior with maximum confidence threshold."""
        policy = MemoryPolicy(min_confidence=1.0)

        assert policy.should_store("fact", 1.0) is True
        assert policy.should_store("fact", 0.99) is False


class TestMemoryPolicyRateLimiting:
    """Test rate limiting functionality."""

    def test_enforce_rate_limit_under_limit(self):
        """Test that requests under limit are allowed."""
        policy = MemoryPolicy(max_per_window=3)

        assert policy.enforce_rate_limit("window_1") is True
        assert policy.enforce_rate_limit("window_1") is True
        assert policy.enforce_rate_limit("window_1") is True

    def test_enforce_rate_limit_at_limit(self):
        """Test that request at limit is rejected."""
        policy = MemoryPolicy(max_per_window=3)

        # Fill up to limit
        assert policy.enforce_rate_limit("window_1") is True
        assert policy.enforce_rate_limit("window_1") is True
        assert policy.enforce_rate_limit("window_1") is True

        # Next request should be rejected
        assert policy.enforce_rate_limit("window_1") is False

    def test_enforce_rate_limit_increments_count(self):
        """Test that enforce_rate_limit increments the count."""
        policy = MemoryPolicy(max_per_window=3)

        assert policy.get_window_count("window_1") == 0

        policy.enforce_rate_limit("window_1")
        assert policy.get_window_count("window_1") == 1

        policy.enforce_rate_limit("window_1")
        assert policy.get_window_count("window_1") == 2

    def test_enforce_rate_limit_different_windows(self):
        """Test that different windows have independent limits."""
        policy = MemoryPolicy(max_per_window=2)

        # Fill window_1
        assert policy.enforce_rate_limit("window_1") is True
        assert policy.enforce_rate_limit("window_1") is True

        # window_2 should still be available
        assert policy.enforce_rate_limit("window_2") is True
        assert policy.enforce_rate_limit("window_2") is True

        # Both should now be at limit
        assert policy.enforce_rate_limit("window_1") is False
        assert policy.enforce_rate_limit("window_2") is False

    def test_enforce_rate_limit_max_one(self):
        """Test rate limiting with max_per_window of 1."""
        policy = MemoryPolicy(max_per_window=1)

        assert policy.enforce_rate_limit("window_1") is True
        assert policy.enforce_rate_limit("window_1") is False

    def test_get_window_count_nonexistent(self):
        """Test getting count for window that doesn't exist."""
        policy = MemoryPolicy()

        assert policy.get_window_count("nonexistent") == 0

    def test_get_window_count_after_increment(self):
        """Test getting count after incrementing."""
        policy = MemoryPolicy(max_per_window=5)

        policy.enforce_rate_limit("window_1")
        policy.enforce_rate_limit("window_1")

        assert policy.get_window_count("window_1") == 2

    def test_reset_window(self):
        """Test resetting a window."""
        policy = MemoryPolicy(max_per_window=2)

        # Fill window
        policy.enforce_rate_limit("window_1")
        policy.enforce_rate_limit("window_1")
        assert policy.get_window_count("window_1") == 2

        # Reset window
        policy.reset_window("window_1")
        assert policy.get_window_count("window_1") == 0

        # Should be able to use again
        assert policy.enforce_rate_limit("window_1") is True

    def test_reset_window_nonexistent(self):
        """Test resetting a window that doesn't exist."""
        policy = MemoryPolicy()

        # Should not raise error
        policy.reset_window("nonexistent")

    def test_reset_window_after_limit_reached(self):
        """Test that reset allows more requests after limit reached."""
        policy = MemoryPolicy(max_per_window=1)

        # Reach limit
        assert policy.enforce_rate_limit("window_1") is True
        assert policy.enforce_rate_limit("window_1") is False

        # Reset and try again
        policy.reset_window("window_1")
        assert policy.enforce_rate_limit("window_1") is True


class TestMemoryPolicyGenerateWindowKey:
    """Test window key generation."""

    def test_generate_window_key_format(self):
        """Test that window key has expected format."""
        window_key = MemoryPolicy.generate_window_key("conv_123")

        assert window_key.startswith("conv_123_window_")
        assert "_window_" in window_key

    def test_generate_window_key_deterministic(self):
        """Test that window key is deterministic within same time window."""
        key1 = MemoryPolicy.generate_window_key("conv_123")
        key2 = MemoryPolicy.generate_window_key("conv_123")

        # Should be same within same time window
        assert key1 == key2

    def test_generate_window_key_different_conversations(self):
        """Test that different conversations get different keys."""
        key1 = MemoryPolicy.generate_window_key("conv_123")
        key2 = MemoryPolicy.generate_window_key("conv_456")

        assert key1 != key2
        assert "conv_123" in key1
        assert "conv_456" in key2

    def test_generate_window_key_custom_time_window(self):
        """Test window key with custom time window."""
        # Different time windows should produce different bucket sizes
        key_60 = MemoryPolicy.generate_window_key("conv_123", time_window_minutes=60)
        key_30 = MemoryPolicy.generate_window_key("conv_123", time_window_minutes=30)

        # Both should be valid window keys
        assert "conv_123_window_" in key_60
        assert "conv_123_window_" in key_30

    @patch('memory_policy.datetime')
    def test_generate_window_key_buckets_time(self, mock_datetime):
        """Test that window key buckets time correctly."""
        # Mock specific timestamp
        mock_now = datetime(2025, 12, 25, 12, 0, 0)
        mock_datetime.utcnow.return_value = mock_now

        key1 = MemoryPolicy.generate_window_key("conv_123", time_window_minutes=60)

        # Advance time by 30 minutes (still in same 60-minute bucket)
        mock_now = datetime(2025, 12, 25, 12, 30, 0)
        mock_datetime.utcnow.return_value = mock_now

        key2 = MemoryPolicy.generate_window_key("conv_123", time_window_minutes=60)

        # Should be same bucket
        assert key1 == key2

        # Advance time by another 31 minutes (now in different bucket)
        mock_now = datetime(2025, 12, 25, 13, 1, 0)
        mock_datetime.utcnow.return_value = mock_now

        key3 = MemoryPolicy.generate_window_key("conv_123", time_window_minutes=60)

        # Should be different bucket
        assert key1 != key3


class TestMemoryPolicyPrivateMethods:
    """Test private helper methods."""

    def test_check_confidence_above_threshold(self):
        """Test _check_confidence with value above threshold."""
        policy = MemoryPolicy(min_confidence=0.7)

        assert policy._check_confidence(0.8) is True
        assert policy._check_confidence(0.9) is True
        assert policy._check_confidence(1.0) is True

    def test_check_confidence_at_threshold(self):
        """Test _check_confidence with value at threshold."""
        policy = MemoryPolicy(min_confidence=0.7)

        assert policy._check_confidence(0.7) is True

    def test_check_confidence_below_threshold(self):
        """Test _check_confidence with value below threshold."""
        policy = MemoryPolicy(min_confidence=0.7)

        assert policy._check_confidence(0.69) is False
        assert policy._check_confidence(0.5) is False
        assert policy._check_confidence(0.0) is False

    def test_check_window_limit_under_limit(self):
        """Test _check_window_limit when under limit."""
        policy = MemoryPolicy(max_per_window=3)

        assert policy._check_window_limit("window_1") is True

        # Add one
        policy._window_counts["window_1"] = 1
        assert policy._check_window_limit("window_1") is True

        # Add two more
        policy._window_counts["window_1"] = 2
        assert policy._check_window_limit("window_1") is True

    def test_check_window_limit_at_limit(self):
        """Test _check_window_limit when at limit."""
        policy = MemoryPolicy(max_per_window=3)

        policy._window_counts["window_1"] = 3
        assert policy._check_window_limit("window_1") is False

    def test_check_window_limit_over_limit(self):
        """Test _check_window_limit when over limit."""
        policy = MemoryPolicy(max_per_window=3)

        policy._window_counts["window_1"] = 5
        assert policy._check_window_limit("window_1") is False


class TestMemoryPolicyIntegration:
    """Integration tests combining multiple policy features."""

    def test_full_workflow(self):
        """Test complete workflow with type validation, confidence, and rate limiting."""
        policy = MemoryPolicy(min_confidence=0.7, max_per_window=2)

        # Test memory that passes all checks
        assert policy.should_store("fact", 0.8) is True
        window_key = "window_test"
        assert policy.enforce_rate_limit(window_key) is True

        # Second memory
        assert policy.should_store("preference", 0.9) is True
        assert policy.enforce_rate_limit(window_key) is True

        # Third memory - rate limited
        assert policy.should_store("decision", 0.85) is True
        assert policy.enforce_rate_limit(window_key) is False

    def test_multiple_windows_simultaneously(self):
        """Test managing multiple windows at once."""
        policy = MemoryPolicy(min_confidence=0.7, max_per_window=2)

        # Window 1
        assert policy.enforce_rate_limit("window_1") is True
        assert policy.enforce_rate_limit("window_1") is True

        # Window 2
        assert policy.enforce_rate_limit("window_2") is True

        # Window 1 should be at limit
        assert policy.enforce_rate_limit("window_1") is False

        # Window 2 should still have capacity
        assert policy.enforce_rate_limit("window_2") is True
        assert policy.enforce_rate_limit("window_2") is False

        # Reset window 1
        policy.reset_window("window_1")

        # Window 1 should now work again
        assert policy.enforce_rate_limit("window_1") is True
