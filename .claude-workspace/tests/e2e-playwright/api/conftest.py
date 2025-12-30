"""
Pytest Configuration for Playwright API Tests.

Provides:
- Custom markers registration (api, hybrid, v4)
- Shared fixtures for API testing
- Environment configuration
"""

from __future__ import annotations

import os
import sys
import pytest
from typing import List

# Add lib directory to path
LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)


# =============================================================================
# Marker Registration
# =============================================================================

def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "api: API-level tests (MCP JSON-RPC)"
    )
    config.addinivalue_line(
        "markers",
        "hybrid: Tests for hybrid_search functionality"
    )
    config.addinivalue_line(
        "markers",
        "history: Tests for history_append and history_get tools"
    )
    config.addinivalue_line(
        "markers",
        "v3: V3-specific tests (event extraction)"
    )
    config.addinivalue_line(
        "markers",
        "v4: V4-specific tests (graph expansion, entities)"
    )
    config.addinivalue_line(
        "markers",
        "slow: Slow running tests"
    )
    config.addinivalue_line(
        "markers",
        "workflow: Complete E2E workflow tests"
    )
    config.addinivalue_line(
        "markers",
        "requires_events: Tests requiring event extraction to be complete"
    )
    config.addinivalue_line(
        "markers",
        "requires_graph: Tests requiring Apache AGE graph database"
    )


# =============================================================================
# Environment Configuration
# =============================================================================

@pytest.fixture(scope="session", autouse=True)
def configure_environment() -> None:
    """Configure environment variables for test session."""
    # Set default MCP URL if not already set
    if "MCP_URL" not in os.environ:
        os.environ["MCP_URL"] = "http://localhost:3201/mcp/"


@pytest.fixture(scope="session")
def mcp_url() -> str:
    """Get MCP server URL."""
    return os.environ.get("MCP_URL", "http://localhost:3201/mcp/")


# =============================================================================
# Test Data Constants
# =============================================================================

@pytest.fixture(scope="session")
def valid_event_categories() -> List[str]:
    """List of valid event categories for V4."""
    return [
        "Commitment",
        "Execution",
        "Decision",
        "Collaboration",
        "QualityRisk",
        "Feedback",
        "Change",
        "Stakeholder"
    ]


@pytest.fixture(scope="session")
def default_graph_filters() -> List[str]:
    """Default graph_filters value per V4 spec."""
    return ["Decision", "Commitment", "QualityRisk"]


# =============================================================================
# Skip Conditions
# =============================================================================

@pytest.fixture(scope="session")
def skip_if_no_server(mcp_url: str) -> None:
    """Skip tests if MCP server is not available."""
    import requests

    try:
        # Try to connect to the server
        response = requests.post(
            mcp_url,
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "test", "version": "1.0"},
                    "capabilities": {}
                }
            },
            timeout=5
        )
        if response.status_code != 200:
            pytest.skip(f"MCP server not responding correctly at {mcp_url}")
    except requests.exceptions.ConnectionError:
        pytest.skip(f"MCP server not available at {mcp_url}")
    except requests.exceptions.Timeout:
        pytest.skip(f"MCP server timeout at {mcp_url}")


# =============================================================================
# Collection Hooks
# =============================================================================

def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """Modify test collection to add skip markers based on environment."""
    # Check if server is available
    mcp_url = os.environ.get("MCP_URL", "http://localhost:3201/mcp/")

    try:
        import requests
        response = requests.post(
            mcp_url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            },
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "test", "version": "1.0"},
                    "capabilities": {}
                }
            },
            timeout=5
        )
        server_available = response.status_code == 200
    except Exception:
        server_available = False

    if not server_available:
        skip_marker = pytest.mark.skip(
            reason=f"MCP server not available at {mcp_url}"
        )
        for item in items:
            item.add_marker(skip_marker)


# =============================================================================
# Reporting Hooks
# =============================================================================

def pytest_report_header(config: pytest.Config) -> List[str]:
    """Add custom header to pytest report."""
    mcp_url = os.environ.get("MCP_URL", "http://localhost:3201/mcp/")
    return [
        f"MCP Server URL: {mcp_url}",
        "Test Categories: api, hybrid, history, v3, v4, workflow, slow"
    ]
