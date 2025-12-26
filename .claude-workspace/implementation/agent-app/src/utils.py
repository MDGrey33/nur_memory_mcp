"""
Utility functions for MCP Memory system.
"""

from datetime import datetime
import logging
import json
from typing import Any


def get_iso_timestamp() -> str:
    """
    Return current timestamp in ISO-8601 format with Z suffix.

    Returns:
        ISO-8601 formatted timestamp string
    """
    return datetime.utcnow().isoformat() + 'Z'


def count_tokens(text: str) -> int:
    """
    Estimate token count using simple heuristic.

    V1 uses a simple word count * 1.3 approximation.
    V2 should use tiktoken library for accurate counting.

    Args:
        text: Text to count tokens for

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return int(len(text.split()) * 1.3)


def setup_logging(level: str = 'INFO') -> logging.Logger:
    """
    Configure structured JSON logging.

    Args:
        level: Log level (DEBUG, INFO, WARN, ERROR)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger('mcp_memory')
    logger.setLevel(level.upper())

    # Remove existing handlers
    logger.handlers.clear()

    # Create console handler with JSON formatter
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    return logger


class JsonFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, 'extra'):
            log_data.update(record.extra)

        return json.dumps(log_data)


def validate_metadata(metadata: dict[str, Any]) -> None:
    """
    Validate metadata dictionary.

    Args:
        metadata: Metadata dictionary to validate

    Raises:
        ValueError: If metadata is invalid
    """
    if not isinstance(metadata, dict):
        raise ValueError(f"metadata must be a dictionary, got {type(metadata)}")

    # Check for reserved keys that might conflict
    reserved_keys = ['_id', 'id', 'embedding']
    for key in reserved_keys:
        if key in metadata:
            raise ValueError(f"metadata cannot contain reserved key: {key}")
