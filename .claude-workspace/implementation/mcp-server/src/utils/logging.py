"""Structured logging setup for MCP Memory Server."""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service": "mcp-memory",
            "component": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        if hasattr(record, "extra") and record.extra:
            log_data.update(record.extra)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """
    Setup structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Configured logger instance
    """
    # Create root logger
    logger = logging.getLogger("mcp-memory")
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers.clear()

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, log_level.upper()))

    # Use structured formatter
    formatter = StructuredFormatter()
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


class StructuredLogger:
    """Wrapper for structured logging with extra fields."""

    def __init__(self, logger: logging.Logger):
        """Initialize with base logger."""
        self.logger = logger

    def _log(self, level: str, event: str, extra: Optional[Dict[str, Any]] = None):
        """Log with structured data."""
        log_record = self.logger.makeRecord(
            self.logger.name,
            getattr(logging, level.upper()),
            "",
            0,
            event,
            (),
            None,
        )
        log_record.extra = extra or {}
        self.logger.handle(log_record)

    def debug(self, event: str, extra: Optional[Dict[str, Any]] = None):
        """Log debug event."""
        self._log("DEBUG", event, extra)

    def info(self, event: str, extra: Optional[Dict[str, Any]] = None):
        """Log info event."""
        self._log("INFO", event, extra)

    def warning(self, event: str, extra: Optional[Dict[str, Any]] = None):
        """Log warning event."""
        self._log("WARNING", event, extra)

    def error(self, event: str, extra: Optional[Dict[str, Any]] = None):
        """Log error event."""
        self._log("ERROR", event, extra)

    def critical(self, event: str, extra: Optional[Dict[str, Any]] = None):
        """Log critical event."""
        self._log("CRITICAL", event, extra)
