"""
MCP Client Adapter for E2E Tests

This module wraps the official MCP Python SDK to provide a simple synchronous
interface for E2E testing. It connects to the MCP Memory Server via HTTP
and provides call_tool() functionality.

Usage:
    from mcp_client import MCPClient, MCPResponse

    client = MCPClient()
    client.initialize()

    response = client.call_tool("remember", {"content": "test"})
    if response.success:
        print(response.data)

    client.close()
"""

import os
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@dataclass
class MCPResponse:
    """Response from an MCP tool call."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class MCPClient:
    """
    Synchronous MCP client wrapper for E2E tests.

    Wraps the official MCP Python SDK's async interface in a synchronous API
    suitable for pytest tests.
    """

    def __init__(self, url: Optional[str] = None):
        """
        Initialize MCP client.

        Args:
            url: MCP server URL. Defaults to http://localhost:3001/mcp/
                 or MCP_SERVER_URL environment variable.
        """
        self.url = url or os.getenv("MCP_SERVER_URL", "http://localhost:3001/mcp/")
        self._session: Optional[ClientSession] = None
        self._read_stream = None
        self._write_stream = None
        self._context_manager = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._initialized = False

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create an event loop."""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop

    def _run_async(self, coro):
        """Run an async coroutine synchronously."""
        loop = self._get_loop()
        if loop.is_running():
            # If we're already in an async context, create a new loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)

    async def _async_initialize(self):
        """Async initialization - connect to MCP server."""
        self._context_manager = streamable_http_client(self.url)
        self._read_stream, self._write_stream, _ = await self._context_manager.__aenter__()

        self._session = ClientSession(self._read_stream, self._write_stream)
        await self._session.__aenter__()

        # Initialize the session
        await self._session.initialize()
        self._initialized = True

    def initialize(self):
        """Initialize connection to MCP server."""
        self._run_async(self._async_initialize())

    async def _async_call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPResponse:
        """Async tool call."""
        if not self._initialized or self._session is None:
            return MCPResponse(success=False, error="Client not initialized")

        try:
            result = await self._session.call_tool(tool_name, arguments)

            # Parse the result - MCP returns content blocks
            if result.content:
                # Get the first text content block
                for block in result.content:
                    if hasattr(block, 'text'):
                        import json
                        try:
                            data = json.loads(block.text)
                            # Check if response contains an error
                            if isinstance(data, dict) and "error" in data:
                                return MCPResponse(success=True, data=data)
                            return MCPResponse(success=True, data=data)
                        except json.JSONDecodeError:
                            return MCPResponse(success=True, data={"text": block.text})

            return MCPResponse(success=True, data={})

        except Exception as e:
            return MCPResponse(success=False, error=str(e))

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPResponse:
        """
        Call an MCP tool synchronously.

        Args:
            tool_name: Name of the tool (remember, recall, forget, status)
            arguments: Tool arguments as a dictionary

        Returns:
            MCPResponse with success status and data/error
        """
        return self._run_async(self._async_call_tool(tool_name, arguments))

    async def _async_close(self):
        """Async cleanup."""
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
                self._session = None
        except RuntimeError:
            # Task scope issues during cleanup - ignore
            self._session = None

        try:
            if self._context_manager:
                await self._context_manager.__aexit__(None, None, None)
                self._context_manager = None
        except RuntimeError:
            # Task scope issues during cleanup - ignore
            self._context_manager = None

        self._initialized = False

    def close(self):
        """Close the connection to MCP server."""
        if self._initialized:
            try:
                self._run_async(self._async_close())
            except RuntimeError:
                # Task scope issues - mark as closed anyway
                self._initialized = False
                self._session = None
                self._context_manager = None

        if self._loop and not self._loop.is_running():
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

    def __enter__(self):
        """Context manager entry."""
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False


# For convenience, also export async versions
class AsyncMCPClient:
    """
    Async MCP client for use in async test contexts.
    """

    def __init__(self, url: Optional[str] = None):
        self.url = url or os.getenv("MCP_SERVER_URL", "http://localhost:3001/mcp/")
        self._session: Optional[ClientSession] = None
        self._read_stream = None
        self._write_stream = None
        self._context_manager = None

    async def initialize(self):
        """Initialize connection to MCP server."""
        self._context_manager = streamable_http_client(self.url)
        self._read_stream, self._write_stream, _ = await self._context_manager.__aenter__()

        self._session = ClientSession(self._read_stream, self._write_stream)
        await self._session.__aenter__()
        await self._session.initialize()

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPResponse:
        """Call an MCP tool."""
        if self._session is None:
            return MCPResponse(success=False, error="Client not initialized")

        try:
            result = await self._session.call_tool(tool_name, arguments)

            if result.content:
                for block in result.content:
                    if hasattr(block, 'text'):
                        import json
                        try:
                            data = json.loads(block.text)
                            return MCPResponse(success=True, data=data)
                        except json.JSONDecodeError:
                            return MCPResponse(success=True, data={"text": block.text})

            return MCPResponse(success=True, data={})

        except Exception as e:
            return MCPResponse(success=False, error=str(e))

    async def close(self):
        """Close the connection."""
        if self._session:
            await self._session.__aexit__(None, None, None)
        if self._context_manager:
            await self._context_manager.__aexit__(None, None, None)

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False
