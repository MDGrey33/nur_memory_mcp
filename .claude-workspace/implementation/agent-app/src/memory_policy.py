"""
Memory storage policy and rate limiting.

Implements business rules for determining when and what to store as memories.
Pure logic, no I/O operations.
"""

import logging
from typing import Dict
from datetime import datetime


logger = logging.getLogger('mcp_memory.policy')


class MemoryPolicy:
    """
    Policy decisions for memory storage.

    Implements confidence gating and rate limiting to prevent memory spam.
    """

    def __init__(self, min_confidence: float = 0.7, max_per_window: int = 3):
        """
        Initialize memory policy.

        Args:
            min_confidence: Minimum confidence to store (0.0-1.0)
            max_per_window: Maximum memories per window

        Raises:
            ValueError: If parameters are invalid
        """
        if not (0.0 <= min_confidence <= 1.0):
            raise ValueError(f"min_confidence must be in [0.0, 1.0], got {min_confidence}")
        if max_per_window < 1:
            raise ValueError(f"max_per_window must be >= 1, got {max_per_window}")

        self.min_confidence = min_confidence
        self.max_per_window = max_per_window

        # In-memory window counts (simple dict for V1)
        # Key: window_key (e.g., "conv_123_window_1"), Value: count
        self._window_counts: Dict[str, int] = {}

        logger.info(f"Policy initialized: min_confidence={min_confidence}, max_per_window={max_per_window}")

    def should_store(self, memory_type: str, confidence: float) -> bool:
        """
        Determine if a memory should be stored based on type and confidence.

        Args:
            memory_type: Type of memory (preference, fact, project, decision)
            confidence: Confidence score [0.0, 1.0]

        Returns:
            True if memory meets storage criteria, False otherwise
        """
        # Validate memory type
        if not self.validate_memory_type(memory_type):
            logger.warning(f"Invalid memory type: {memory_type}")
            return False

        # Check confidence threshold
        if not self._check_confidence(confidence):
            logger.debug(f"Memory rejected: confidence {confidence} < min {self.min_confidence}")
            return False

        logger.debug(f"Memory accepted: type={memory_type}, confidence={confidence}")
        return True

    def enforce_rate_limit(self, window_key: str) -> bool:
        """
        Check if rate limit allows storing another memory.

        Args:
            window_key: Identifier for current window (e.g., conversation_id + time_bucket)

        Returns:
            True if under limit (can store), False if limit reached
        """
        current_count = self._window_counts.get(window_key, 0)

        if current_count >= self.max_per_window:
            logger.warning(f"Rate limit reached for window {window_key}: {current_count}/{self.max_per_window}")
            return False

        # Increment count
        self._window_counts[window_key] = current_count + 1
        logger.debug(f"Rate limit check passed: {current_count + 1}/{self.max_per_window} for window {window_key}")
        return True

    def validate_memory_type(self, memory_type: str) -> bool:
        """
        Validate memory type is recognized.

        Args:
            memory_type: Type to validate

        Returns:
            True if valid type, False otherwise
        """
        valid_types = ["preference", "fact", "project", "decision"]
        return memory_type in valid_types

    def reset_window(self, window_key: str) -> None:
        """
        Reset rate limit counter for a window.

        Args:
            window_key: Window identifier to reset
        """
        if window_key in self._window_counts:
            del self._window_counts[window_key]
            logger.debug(f"Reset window: {window_key}")

    def get_window_count(self, window_key: str) -> int:
        """
        Get current count for a window.

        Args:
            window_key: Window identifier

        Returns:
            Current memory count for the window
        """
        return self._window_counts.get(window_key, 0)

    def _check_confidence(self, confidence: float) -> bool:
        """
        Check if confidence meets minimum threshold.

        Args:
            confidence: Confidence score to check

        Returns:
            True if confidence >= min_confidence
        """
        return confidence >= self.min_confidence

    def _check_window_limit(self, window_key: str) -> bool:
        """
        Check if window is under the limit.

        Args:
            window_key: Window identifier

        Returns:
            True if under limit
        """
        return self._window_counts.get(window_key, 0) < self.max_per_window

    @staticmethod
    def generate_window_key(conversation_id: str, time_window_minutes: int = 60) -> str:
        """
        Generate a window key based on conversation and time bucket.

        Args:
            conversation_id: Conversation identifier
            time_window_minutes: Time window size in minutes

        Returns:
            Window key string
        """
        now = datetime.utcnow()
        bucket = now.timestamp() // (time_window_minutes * 60)
        return f"{conversation_id}_window_{int(bucket)}"
