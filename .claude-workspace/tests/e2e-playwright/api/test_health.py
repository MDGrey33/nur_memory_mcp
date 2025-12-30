"""
API Health Tests - Smoke Tests for System Health Checks.

Tests the embedding_health tool to verify:
- OpenAI embeddings are working
- ChromaDB connectivity
- PostgreSQL connectivity

This should be the first test run (smoke test) to verify all
external dependencies are healthy before running other tests.
"""

import json
import os
import pytest
import requests
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# =============================================================================
# Configuration
# =============================================================================

# MCP_URL is expected to be the full MCP endpoint (e.g., http://localhost:3201/mcp/)
# We derive the base URL and health endpoint from it
_mcp_url: str = os.getenv("MCP_URL", "http://localhost:3201/mcp/")
# Strip /mcp/ suffix to get base URL
MCP_BASE_URL: str = _mcp_url.rstrip("/").replace("/mcp", "")
MCP_ENDPOINT: str = _mcp_url.rstrip("/")
HEALTH_ENDPOINT: str = f"{MCP_BASE_URL}/health"
REQUEST_TIMEOUT: int = int(os.getenv("MCP_TIMEOUT", "30"))


# =============================================================================
# Response Dataclass
# =============================================================================

@dataclass
class MCPResponse:
    """Parsed response from MCP server."""
    success: bool
    data: Optional[Dict[str, Any]]
    error: Optional[str]
    raw: Dict[str, Any]
    latency_ms: float

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from response data."""
        if self.data:
            return self.data.get(key, default)
        return default

    def __bool__(self) -> bool:
        """Allow truthiness check: if response: ..."""
        return self.success


# =============================================================================
# MCP Client Helper
# =============================================================================

class MCPClient:
    """
    Lightweight JSON-RPC client for MCP server health tests.

    Uses requests library for simplicity in health/smoke tests.
    For full API tests, use the MCPClient from utils/mcp_client.py.
    """

    def __init__(
        self,
        base_url: str = MCP_ENDPOINT,
        timeout: int = REQUEST_TIMEOUT
    ) -> None:
        """
        Initialize MCP client.

        Args:
            base_url: MCP server endpoint URL
            timeout: Request timeout in seconds
        """
        self.base_url = base_url
        self.timeout = timeout
        self._request_id = 0
        self._session_id: Optional[str] = None
        self._initialized = False

    def _next_id(self) -> int:
        """Generate next request ID."""
        self._request_id += 1
        return self._request_id

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with session ID if available."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _parse_sse_response(self, text: str) -> Dict[str, Any]:
        """
        Parse Server-Sent Events response.

        Args:
            text: Raw SSE response text

        Returns:
            Parsed JSON-RPC response
        """
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('data:'):
                data_str = line[5:].strip()
                if data_str:
                    try:
                        return json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
        return {"error": {"code": -1, "message": "No valid data in SSE response"}}

    def _send_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send JSON-RPC request.

        Args:
            method: JSON-RPC method name
            params: Method parameters

        Returns:
            Parsed JSON-RPC response
        """
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_id(),
            "params": params or {}
        }

        try:
            response = requests.post(
                self.base_url,
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout
            )

            # Update session ID if provided
            if "Mcp-Session-Id" in response.headers:
                self._session_id = response.headers["Mcp-Session-Id"]

            if response.status_code == 200:
                return self._parse_sse_response(response.text)
            else:
                return {
                    "error": {
                        "code": response.status_code,
                        "message": f"HTTP {response.status_code}: {response.text[:200]}"
                    }
                }

        except requests.exceptions.Timeout:
            return {"error": {"code": -1, "message": f"Request timeout after {self.timeout}s"}}
        except requests.exceptions.ConnectionError as e:
            return {"error": {"code": -1, "message": f"Connection error: {e}"}}
        except Exception as e:
            return {"error": {"code": -1, "message": f"Request failed: {e}"}}

    def initialize(self) -> bool:
        """
        Initialize MCP session.

        Returns:
            True if initialization successful
        """
        if self._initialized:
            return True

        result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {
                "name": "playwright-health-test",
                "version": "1.0.0"
            },
            "capabilities": {}
        })

        if "result" in result and "protocolVersion" in result.get("result", {}):
            # Send initialized notification
            self._send_request("notifications/initialized", {})
            self._initialized = True
            return True

        return False

    def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None
    ) -> MCPResponse:
        """
        Call an MCP tool.

        Args:
            name: Tool name (e.g., "embedding_health")
            arguments: Tool arguments

        Returns:
            MCPResponse with success status and data
        """
        import time

        if not self._initialized:
            self.initialize()

        start_time = time.time()

        result = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments or {}
        })

        latency_ms = (time.time() - start_time) * 1000

        # Parse result
        if "result" in result:
            content = result["result"].get("content", [{}])
            is_error = result["result"].get("isError", False)

            if is_error:
                error_text = content[0].get("text", "Unknown error") if content else "Unknown error"
                return MCPResponse(
                    success=False,
                    data=None,
                    error=error_text,
                    raw=result,
                    latency_ms=latency_ms
                )

            if content and content[0].get("type") == "text":
                try:
                    data = json.loads(content[0]["text"])
                    return MCPResponse(
                        success=True,
                        data=data,
                        error=None,
                        raw=result,
                        latency_ms=latency_ms
                    )
                except json.JSONDecodeError:
                    return MCPResponse(
                        success=True,
                        data={"text": content[0]["text"]},
                        error=None,
                        raw=result,
                        latency_ms=latency_ms
                    )

        # Error response
        error = result.get("error", {})
        error_msg = error.get("message", str(result))
        return MCPResponse(
            success=False,
            data=None,
            error=error_msg,
            raw=result,
            latency_ms=latency_ms
        )


# =============================================================================
# Pytest Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def mcp_client() -> MCPClient:
    """Create MCP client for tests."""
    client = MCPClient()
    return client


@pytest.fixture(scope="module")
def initialized_client(mcp_client: MCPClient) -> MCPClient:
    """Create and initialize MCP client for tests."""
    if not mcp_client.initialize():
        pytest.skip("Could not initialize MCP session - server may be down")
    return mcp_client


# =============================================================================
# Marker Configuration
# =============================================================================

pytestmark = [
    pytest.mark.api,
    pytest.mark.health,
    pytest.mark.smoke
]


# =============================================================================
# Health Check Tests
# =============================================================================

class TestServerHealth:
    """Tests for server health endpoint."""

    def test_health_endpoint_accessible(self) -> None:
        """
        Test that the /health endpoint is accessible.

        This is a basic connectivity check that doesn't require MCP protocol.
        """
        try:
            response = requests.get(HEALTH_ENDPOINT, timeout=REQUEST_TIMEOUT)
            assert response.status_code == 200, \
                f"Health endpoint returned {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.fail(f"Cannot connect to MCP server at {HEALTH_ENDPOINT}")
        except requests.exceptions.Timeout:
            pytest.fail(f"Health endpoint timeout after {REQUEST_TIMEOUT}s")

    def test_health_response_structure(self) -> None:
        """
        Test that /health returns expected structure.

        Expected structure:
        {
            "status": "ok",
            "version": "x.x.x",
            "chromadb": {...},
            "postgres": {...},
            "openai": {...}
        }
        """
        response = requests.get(HEALTH_ENDPOINT, timeout=REQUEST_TIMEOUT)
        health = response.json()

        assert "status" in health, "Health response missing 'status' field"
        assert health["status"] == "ok", f"Server unhealthy: status={health['status']}"
        assert "version" in health, "Health response missing 'version' field"

    def test_health_response_has_component_status(self) -> None:
        """Test that /health includes all component statuses."""
        response = requests.get(HEALTH_ENDPOINT, timeout=REQUEST_TIMEOUT)
        health = response.json()

        # Verify component status sections exist
        assert "chromadb" in health, "Health response missing 'chromadb' status"
        assert "postgres" in health, "Health response missing 'postgres' status"
        assert "openai" in health, "Health response missing 'openai' status"


class TestEmbeddingHealthTool:
    """Tests for the embedding_health MCP tool."""

    def test_embedding_health_returns_healthy(
        self,
        initialized_client: MCPClient
    ) -> None:
        """
        Test embedding_health tool returns healthy status.

        Verifies that OpenAI embeddings, ChromaDB, and PostgreSQL
        are all working correctly.
        """
        response = initialized_client.call_tool("embedding_health", {})

        assert response.success, f"embedding_health failed: {response.error}"
        assert response.data is not None, "embedding_health returned no data"
        assert response.get("status") == "healthy", \
            f"Embedding health status not healthy: {response.get('status')}"

    def test_embedding_health_includes_openai_status(
        self,
        initialized_client: MCPClient
    ) -> None:
        """
        Test embedding_health includes OpenAI status.

        Verifies the OpenAI embedding service is connected and working.
        """
        response = initialized_client.call_tool("embedding_health", {})

        assert response.success, f"embedding_health failed: {response.error}"

        # Check for OpenAI-related info in response
        data = response.data
        assert data is not None

        # The response should indicate OpenAI is working
        # Actual field names may vary by implementation
        openai_ok = (
            data.get("openai_status") == "healthy" or
            data.get("openai", {}).get("status") == "healthy" or
            data.get("embedding_service") == "healthy" or
            data.get("status") == "healthy"  # Overall healthy implies OpenAI works
        )
        assert openai_ok, f"OpenAI status not healthy in response: {data}"

    def test_embedding_health_includes_chromadb_status(
        self,
        initialized_client: MCPClient
    ) -> None:
        """
        Test embedding_health includes ChromaDB status.

        Verifies ChromaDB vector store is connected and working.
        """
        response = initialized_client.call_tool("embedding_health", {})

        assert response.success, f"embedding_health failed: {response.error}"

        data = response.data
        assert data is not None

        # The response should indicate ChromaDB is working
        chromadb_ok = (
            data.get("chromadb_status") == "healthy" or
            data.get("chromadb", {}).get("status") == "healthy" or
            data.get("vector_store") == "healthy" or
            data.get("status") == "healthy"  # Overall healthy implies ChromaDB works
        )
        assert chromadb_ok, f"ChromaDB status not healthy in response: {data}"

    def test_embedding_health_includes_postgres_status(
        self,
        initialized_client: MCPClient
    ) -> None:
        """
        Test embedding_health includes PostgreSQL status.

        Verifies PostgreSQL database is connected and working.
        """
        response = initialized_client.call_tool("embedding_health", {})

        assert response.success, f"embedding_health failed: {response.error}"

        data = response.data
        assert data is not None

        # The response should indicate Postgres is working
        postgres_ok = (
            data.get("postgres_status") == "healthy" or
            data.get("postgres", {}).get("status") == "healthy" or
            data.get("database") == "healthy" or
            data.get("status") == "healthy"  # Overall healthy implies Postgres works
        )
        assert postgres_ok, f"PostgreSQL status not healthy in response: {data}"

    def test_embedding_health_response_time(
        self,
        initialized_client: MCPClient
    ) -> None:
        """
        Test embedding_health responds within acceptable time.

        Health checks should be fast - under 5 seconds.
        """
        response = initialized_client.call_tool("embedding_health", {})

        assert response.success, f"embedding_health failed: {response.error}"
        assert response.latency_ms < 5000, \
            f"embedding_health took too long: {response.latency_ms}ms"


class TestMCPSessionInitialization:
    """Tests for MCP session initialization."""

    def test_can_initialize_session(self, mcp_client: MCPClient) -> None:
        """
        Test that MCP session can be initialized.

        This is a prerequisite for all other MCP tool tests.
        """
        success = mcp_client.initialize()
        assert success, "Failed to initialize MCP session"

    def test_can_list_tools(self, initialized_client: MCPClient) -> None:
        """
        Test that tools/list returns available tools.

        Verifies MCP protocol is working correctly.
        """
        result = initialized_client._send_request("tools/list", {})

        assert "result" in result, f"tools/list failed: {result}"
        assert "tools" in result["result"], "tools/list missing 'tools' in result"

        tools = result["result"]["tools"]
        assert len(tools) > 0, "No tools returned from tools/list"

        # Verify embedding_health tool is available
        tool_names = [t["name"] for t in tools]
        assert "embedding_health" in tool_names, \
            f"embedding_health tool not found. Available: {tool_names}"


class TestComponentConnectivity:
    """
    Tests for individual component connectivity.

    These tests verify each external dependency is working.
    """

    def test_chromadb_heartbeat(self) -> None:
        """
        Test ChromaDB heartbeat is accessible.

        ChromaDB exposes a heartbeat endpoint for health checks.
        """
        chroma_host = os.getenv("CHROMA_HOST", "localhost")
        chroma_port = os.getenv("CHROMA_PORT", "8001")
        chroma_url = f"http://{chroma_host}:{chroma_port}/api/v2/heartbeat"

        try:
            response = requests.get(chroma_url, timeout=5)
            assert response.status_code == 200, \
                f"ChromaDB heartbeat returned {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.fail(f"Cannot connect to ChromaDB at {chroma_url}")
        except requests.exceptions.Timeout:
            pytest.fail(f"ChromaDB heartbeat timeout")

    def test_postgres_via_mcp(self, initialized_client: MCPClient) -> None:
        """
        Test PostgreSQL connectivity via MCP health check.

        Uses the embedding_health tool to verify Postgres is working.
        """
        response = initialized_client.call_tool("embedding_health", {})

        assert response.success, \
            f"Cannot verify Postgres connectivity: {response.error}"

        # If embedding_health succeeds, Postgres is working
        # The tool internally checks Postgres connection

    def test_openai_via_mcp(self, initialized_client: MCPClient) -> None:
        """
        Test OpenAI connectivity via MCP health check.

        Uses the embedding_health tool to verify OpenAI is working.
        """
        response = initialized_client.call_tool("embedding_health", {})

        assert response.success, \
            f"Cannot verify OpenAI connectivity: {response.error}"

        # If embedding_health succeeds, OpenAI embeddings are working


class TestSmokeTestSuite:
    """
    Comprehensive smoke test suite.

    This class runs all critical health checks that should pass
    before running any other tests.
    """

    def test_all_systems_healthy(self, initialized_client: MCPClient) -> None:
        """
        Comprehensive smoke test verifying all systems are healthy.

        This single test verifies:
        - MCP server is accessible
        - MCP session can be initialized
        - embedding_health tool works
        - All external dependencies (OpenAI, ChromaDB, Postgres) are healthy

        If this test passes, the system is ready for full test suite.
        """
        # Verify MCP server is accessible
        response = requests.get(HEALTH_ENDPOINT, timeout=REQUEST_TIMEOUT)
        assert response.status_code == 200, "MCP server not accessible"

        health = response.json()
        assert health.get("status") == "ok", f"Server unhealthy: {health}"

        # Verify embedding_health tool works
        tool_response = initialized_client.call_tool("embedding_health", {})
        assert tool_response.success, f"embedding_health failed: {tool_response.error}"
        assert tool_response.get("status") == "healthy", \
            f"System not healthy: {tool_response.data}"

        # Verify response time is acceptable
        assert tool_response.latency_ms < 10000, \
            f"System responding slowly: {tool_response.latency_ms}ms"

    def test_critical_tools_available(self, initialized_client: MCPClient) -> None:
        """
        Verify all critical tools are available.

        These tools must be present for the MCP server to be functional.
        """
        result = initialized_client._send_request("tools/list", {})
        assert "result" in result and "tools" in result["result"]

        tool_names = {t["name"] for t in result["result"]["tools"]}

        critical_tools = [
            "embedding_health",
            "memory_store",
            "memory_search",
            "artifact_ingest",
            "artifact_search",
            "hybrid_search"
        ]

        missing_tools = [t for t in critical_tools if t not in tool_names]
        assert not missing_tools, f"Missing critical tools: {missing_tools}"


# =============================================================================
# Run as standalone script
# =============================================================================

if __name__ == "__main__":
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "-m", "smoke"
    ])
