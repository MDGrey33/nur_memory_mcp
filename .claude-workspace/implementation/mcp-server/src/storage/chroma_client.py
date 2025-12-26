"""ChromaDB client management for MCP Memory Server."""

import logging
from typing import Optional
import chromadb
from chromadb import HttpClient


logger = logging.getLogger("mcp-memory.storage")


class ChromaClientManager:
    """Manages ChromaDB client lifecycle and connectivity."""

    def __init__(self, host: str, port: int):
        """
        Initialize ChromaDB client manager.

        Args:
            host: ChromaDB host address
            port: ChromaDB port number
        """
        self._client: Optional[HttpClient] = None
        self.host = host
        self.port = port

    def get_client(self) -> HttpClient:
        """
        Get or create ChromaDB client.

        Returns:
            ChromaDB HTTP client instance

        Raises:
            ConnectionError: If cannot connect to ChromaDB
        """
        if self._client is None:
            try:
                self._client = chromadb.HttpClient(
                    host=self.host,
                    port=self.port
                )
                # Test connection
                self._client.heartbeat()
                logger.info(f"Connected to ChromaDB at {self.host}:{self.port}")
            except Exception as e:
                raise ConnectionError(
                    f"Cannot connect to ChromaDB at {self.host}:{self.port}. "
                    f"Ensure ChromaDB is running. Error: {e}"
                )

        return self._client

    def health_check(self) -> dict:
        """
        Check ChromaDB connectivity and health.

        Returns:
            Dict with status and optional error message
        """
        try:
            client = self.get_client()
            latency_start = __import__("time").time()
            client.heartbeat()
            latency_ms = int((__import__("time").time() - latency_start) * 1000)

            return {
                "status": "healthy",
                "host": self.host,
                "port": self.port,
                "latency_ms": latency_ms
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "host": self.host,
                "port": self.port,
                "error": str(e)
            }

    def close(self):
        """Close ChromaDB client connection."""
        if self._client is not None:
            self._client = None
            logger.info("ChromaDB client closed")
