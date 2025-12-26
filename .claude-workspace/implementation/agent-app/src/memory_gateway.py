"""
MCP transport layer for ChromaDB operations.

This module provides a clean abstraction over MCP tool calls with no business logic.
All communication with chroma-mcp happens through this gateway.
"""

import httpx
import asyncio
import logging
from typing import Optional

try:
    from .exceptions import MCPError, ConnectionError as MCPConnectionError
    from .utils import setup_logging
except ImportError:
    # Support both relative and absolute imports
    from exceptions import MCPError, ConnectionError as MCPConnectionError
    from utils import setup_logging


logger = logging.getLogger('mcp_memory.gateway')


class ChromaMcpGateway:
    """
    Transport layer for MCP operations.

    Handles all communication with chroma-mcp server, including connection management,
    error handling, and retry logic. No business logic - pure transport.
    """

    def __init__(self, mcp_endpoint: str, timeout: float = 30.0):
        """
        Initialize gateway connection to MCP server.

        Args:
            mcp_endpoint: MCP server endpoint (hostname or URL)
            timeout: Request timeout in seconds

        Raises:
            ValueError: If mcp_endpoint is invalid
        """
        if not mcp_endpoint:
            raise ValueError("mcp_endpoint cannot be empty")

        self.mcp_endpoint = mcp_endpoint
        self.timeout = timeout
        self.client: Optional[httpx.AsyncClient] = None

        # Build base URL
        if not mcp_endpoint.startswith('http://') and not mcp_endpoint.startswith('https://'):
            self.base_url = f"http://{mcp_endpoint}:8080"
        else:
            self.base_url = mcp_endpoint

        logger.info(f"Gateway initialized with endpoint: {self.base_url}")

    async def __aenter__(self):
        """Async context manager entry."""
        self.client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.client:
            await self.client.aclose()

    async def ensure_collections(self, names: list[str]) -> None:
        """
        Ensure collections exist, create if missing.

        This is idempotent - if collections already exist, they are not recreated.

        Args:
            names: List of collection names to ensure exist

        Raises:
            MCPConnectionError: If MCP server is unreachable
            MCPError: If collection creation fails
        """
        logger.info(f"Ensuring collections exist: {names}")

        # List existing collections
        try:
            existing = await self._list_collections()
            logger.debug(f"Existing collections: {existing}")
        except Exception as e:
            raise MCPConnectionError(f"Failed to list collections: {e}") from e

        # Create missing collections
        for name in names:
            if name not in existing:
                try:
                    await self._create_collection(name)
                    logger.info(f"Created collection: {name}")
                except Exception as e:
                    raise MCPError(f"Failed to create collection {name}: {e}") from e
            else:
                logger.debug(f"Collection already exists: {name}")

    async def append_history(
        self,
        conversation_id: str,
        role: str,
        text: str,
        turn_index: int,
        ts: str,
        message_id: Optional[str] = None,
        channel: Optional[str] = None
    ) -> str:
        """
        Append a turn to history collection.

        Args:
            conversation_id: Conversation identifier
            role: Message role (user, assistant, system)
            text: Message text content
            turn_index: Monotonic turn counter
            ts: ISO-8601 timestamp
            message_id: Optional unique message identifier
            channel: Optional source channel

        Returns:
            Document ID assigned by ChromaDB

        Raises:
            ValueError: If required fields are missing or invalid
            MCPError: If storage operation fails
        """
        # Validate inputs
        if not conversation_id:
            raise ValueError("conversation_id cannot be empty")
        if role not in ["user", "assistant", "system"]:
            raise ValueError(f"role must be one of [user, assistant, system], got {role}")
        if not text:
            raise ValueError("text cannot be empty")
        if turn_index < 0:
            raise ValueError(f"turn_index must be non-negative, got {turn_index}")

        # Build metadata
        metadata = {
            "conversation_id": conversation_id,
            "role": role,
            "ts": ts,
            "turn_index": turn_index
        }
        if message_id:
            metadata["message_id"] = message_id
        if channel:
            metadata["channel"] = channel

        # Generate ID if not provided
        doc_id = message_id if message_id else f"{conversation_id}_{turn_index}"

        logger.debug(f"Appending history: {doc_id}")

        try:
            result = await self._add_document(
                collection="history",
                document=text,
                metadata=metadata,
                doc_id=doc_id
            )
            logger.info(f"History appended: {doc_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to append history: {e}")
            raise MCPError(f"Failed to append history: {e}") from e

    async def tail_history(
        self,
        conversation_id: str,
        n: int
    ) -> list[dict]:
        """
        Retrieve last N turns from history.

        Args:
            conversation_id: Conversation identifier
            n: Number of recent turns to retrieve

        Returns:
            List of documents with text and metadata, ordered chronologically

        Raises:
            ValueError: If n < 1
            MCPError: If retrieval fails
        """
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")

        logger.debug(f"Retrieving history tail: conversation_id={conversation_id}, n={n}")

        try:
            # Query history collection with metadata filter and sort
            results = await self._get_documents(
                collection="history",
                where={"conversation_id": conversation_id},
                limit=n,
                sort_by="turn_index",
                sort_order="desc"
            )

            # Reverse to chronological order (oldest first)
            results.reverse()

            logger.info(f"Retrieved {len(results)} history turns")
            return results
        except Exception as e:
            logger.error(f"Failed to retrieve history: {e}")
            raise MCPError(f"Failed to retrieve history: {e}") from e

    async def write_memory(
        self,
        text: str,
        memory_type: str,
        confidence: float,
        ts: str,
        conversation_id: Optional[str] = None,
        entities: Optional[str] = None,
        source: Optional[str] = None,
        tags: Optional[str] = None
    ) -> str:
        """
        Store a memory to memory collection.

        Args:
            text: Memory statement or summary
            memory_type: One of: preference, fact, project, decision
            confidence: Confidence score [0.0, 1.0]
            ts: ISO-8601 timestamp
            conversation_id: Optional source conversation
            entities: Optional comma-separated entity list
            source: Optional source type (chat, tool, import)
            tags: Optional comma-separated tag list

        Returns:
            Document ID assigned by ChromaDB

        Raises:
            ValueError: If required fields are invalid
            MCPError: If storage operation fails
        """
        # Validate inputs
        if not text:
            raise ValueError("text cannot be empty")
        valid_types = ["preference", "fact", "project", "decision"]
        if memory_type not in valid_types:
            raise ValueError(f"memory_type must be one of {valid_types}, got {memory_type}")
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence}")

        # Build metadata
        metadata = {
            "type": memory_type,
            "confidence": confidence,
            "ts": ts
        }
        if conversation_id:
            metadata["conversation_id"] = conversation_id
        if entities:
            metadata["entities"] = entities
        if source:
            metadata["source"] = source
        if tags:
            metadata["tags"] = tags

        logger.debug(f"Writing memory: type={memory_type}, confidence={confidence}")

        try:
            result = await self._add_document(
                collection="memory",
                document=text,
                metadata=metadata
            )
            logger.info(f"Memory written: {result}")
            return result
        except Exception as e:
            logger.error(f"Failed to write memory: {e}")
            raise MCPError(f"Failed to write memory: {e}") from e

    async def recall_memory(
        self,
        query_text: str,
        k: int,
        min_confidence: float,
        conversation_id: Optional[str] = None
    ) -> list[dict]:
        """
        Semantic search over memory collection.

        Args:
            query_text: Query string for vector similarity
            k: Number of results to return (top-K)
            min_confidence: Minimum confidence threshold
            conversation_id: Optional filter by source conversation

        Returns:
            List of documents with text, metadata, and similarity scores

        Raises:
            ValueError: If k < 1 or min_confidence not in [0.0, 1.0]
            MCPError: If query fails
        """
        if k < 1:
            raise ValueError(f"k must be >= 1, got {k}")
        if not (0.0 <= min_confidence <= 1.0):
            raise ValueError(f"min_confidence must be in [0.0, 1.0], got {min_confidence}")

        logger.debug(f"Recalling memories: query='{query_text[:50]}...', k={k}, min_confidence={min_confidence}")

        # Build where filter
        where = {"confidence": {"$gte": min_confidence}}
        if conversation_id:
            where["conversation_id"] = conversation_id

        try:
            results = await self._query_collection(
                collection="memory",
                query_text=query_text,
                n_results=k,
                where=where
            )
            logger.info(f"Recalled {len(results)} memories")
            return results
        except Exception as e:
            logger.error(f"Failed to recall memories: {e}")
            raise MCPError(f"Failed to recall memories: {e}") from e

    # Private methods for HTTP/MCP operations

    async def _list_collections(self) -> list[str]:
        """List all collections in ChromaDB."""
        # Direct ChromaDB API call
        url = f"{self.base_url.replace(':8080', ':8000')}/api/v1/collections"

        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout)

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise MCPConnectionError(f"HTTP error listing collections: {e}") from e

    async def _create_collection(self, name: str) -> None:
        """Create a collection in ChromaDB."""
        url = f"{self.base_url.replace(':8080', ':8000')}/api/v1/collections"

        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout)

        try:
            response = await self.client.post(url, json={"name": name})
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise MCPError(f"HTTP error creating collection: {e}") from e

    async def _add_document(
        self,
        collection: str,
        document: str,
        metadata: dict,
        doc_id: Optional[str] = None
    ) -> str:
        """Add a document to a collection."""
        url = f"{self.base_url.replace(':8080', ':8000')}/api/v1/collections/{collection}/add"

        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout)

        payload = {
            "documents": [document],
            "metadatas": [metadata]
        }
        if doc_id:
            payload["ids"] = [doc_id]

        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get("ids", [doc_id or "unknown"])[0]
        except httpx.HTTPError as e:
            raise MCPError(f"HTTP error adding document: {e}") from e

    async def _get_documents(
        self,
        collection: str,
        where: Optional[dict] = None,
        limit: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "asc"
    ) -> list[dict]:
        """Get documents from a collection with filtering and sorting."""
        url = f"{self.base_url.replace(':8080', ':8000')}/api/v1/collections/{collection}/get"

        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout)

        payload = {}
        if where:
            payload["where"] = where
        if limit:
            payload["limit"] = limit
        if sort_by:
            payload["sort"] = [{"field": sort_by, "order": sort_order}]

        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

            # Transform to list of dicts
            documents = []
            ids = result.get("ids", [])
            docs = result.get("documents", [])
            metadatas = result.get("metadatas", [])

            for i in range(len(ids)):
                documents.append({
                    "id": ids[i],
                    "document": docs[i] if i < len(docs) else "",
                    "metadata": metadatas[i] if i < len(metadatas) else {}
                })

            return documents
        except httpx.HTTPError as e:
            raise MCPError(f"HTTP error getting documents: {e}") from e

    async def _query_collection(
        self,
        collection: str,
        query_text: str,
        n_results: int,
        where: Optional[dict] = None
    ) -> list[dict]:
        """Query a collection with vector similarity search."""
        url = f"{self.base_url.replace(':8080', ':8000')}/api/v1/collections/{collection}/query"

        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout)

        payload = {
            "query_texts": [query_text],
            "n_results": n_results
        }
        if where:
            payload["where"] = where

        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

            # Transform to list of dicts with scores
            documents = []
            ids = result.get("ids", [[]])[0]
            docs = result.get("documents", [[]])[0]
            metadatas = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]

            for i in range(len(ids)):
                documents.append({
                    "id": ids[i],
                    "document": docs[i] if i < len(docs) else "",
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                    "distance": distances[i] if i < len(distances) else 1.0
                })

            return documents
        except httpx.HTTPError as e:
            raise MCPError(f"HTTP error querying collection: {e}") from e
