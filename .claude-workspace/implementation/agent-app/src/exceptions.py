"""
Custom exception hierarchy for MCP Memory system.
"""


class MCPMemoryError(Exception):
    """Base exception for MCP memory system."""
    pass


class MCPError(MCPMemoryError):
    """MCP operation failed."""
    pass


class ConnectionError(MCPMemoryError):
    """Cannot connect to MCP server."""
    pass


class ContextBuildError(MCPMemoryError):
    """Context assembly failed."""
    pass


class ValidationError(MCPMemoryError):
    """Data validation failed."""
    pass


class PolicyRejectionError(MCPMemoryError):
    """Memory rejected by policy."""
    pass
