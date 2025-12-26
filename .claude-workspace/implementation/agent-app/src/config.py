"""
Configuration management and environment variables.

Loads configuration from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AppConfig:
    """Application configuration loaded from environment variables."""

    mcp_endpoint: str
    memory_confidence_min: float
    history_tail_n: int
    memory_top_k: int
    memory_max_per_window: int
    context_token_budget: Optional[int]
    log_level: str

    @classmethod
    def from_env(cls) -> 'AppConfig':
        """
        Load configuration from environment variables.

        Returns:
            AppConfig instance with values from environment or defaults

        Raises:
            ValueError: If any configuration value is invalid
        """
        config = cls(
            mcp_endpoint=os.getenv('MCP_ENDPOINT', 'chroma-mcp'),
            memory_confidence_min=float(os.getenv('MEMORY_CONFIDENCE_MIN', '0.7')),
            history_tail_n=int(os.getenv('HISTORY_TAIL_N', '16')),
            memory_top_k=int(os.getenv('MEMORY_TOP_K', '8')),
            memory_max_per_window=int(os.getenv('MEMORY_MAX_PER_WINDOW', '3')),
            context_token_budget=int(os.getenv('CONTEXT_TOKEN_BUDGET')) if os.getenv('CONTEXT_TOKEN_BUDGET') else None,
            log_level=os.getenv('LOG_LEVEL', 'INFO')
        )

        config.validate()
        return config

    def validate(self) -> None:
        """
        Validate configuration values.

        Raises:
            ValueError: If any value is invalid
        """
        if not self.mcp_endpoint:
            raise ValueError("MCP_ENDPOINT cannot be empty")

        if not (0.0 <= self.memory_confidence_min <= 1.0):
            raise ValueError(f"MEMORY_CONFIDENCE_MIN must be in [0.0, 1.0], got {self.memory_confidence_min}")

        if self.history_tail_n < 1:
            raise ValueError(f"HISTORY_TAIL_N must be >= 1, got {self.history_tail_n}")

        if self.memory_top_k < 1:
            raise ValueError(f"MEMORY_TOP_K must be >= 1, got {self.memory_top_k}")

        if self.memory_max_per_window < 1:
            raise ValueError(f"MEMORY_MAX_PER_WINDOW must be >= 1, got {self.memory_max_per_window}")

        if self.context_token_budget is not None and self.context_token_budget < 1:
            raise ValueError(f"CONTEXT_TOKEN_BUDGET must be >= 1 or None, got {self.context_token_budget}")

        valid_log_levels = ['DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'CRITICAL']
        if self.log_level.upper() not in valid_log_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_log_levels}, got {self.log_level}")
