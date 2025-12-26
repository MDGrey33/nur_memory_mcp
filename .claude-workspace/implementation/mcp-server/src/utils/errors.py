"""Custom exception classes for MCP Memory Server."""


class MCPMemoryError(Exception):
    """Base exception for all MCP Memory errors."""
    pass


class ValidationError(MCPMemoryError):
    """Raised when input validation fails."""
    pass


class ConfigurationError(MCPMemoryError):
    """Raised when configuration is invalid."""
    pass


class EmbeddingError(MCPMemoryError):
    """Raised when embedding generation fails."""
    pass


class StorageError(MCPMemoryError):
    """Raised when storage operations fail."""
    pass


class RetrievalError(MCPMemoryError):
    """Raised when retrieval operations fail."""
    pass


class NotFoundError(MCPMemoryError):
    """Raised when a requested resource is not found."""
    pass
