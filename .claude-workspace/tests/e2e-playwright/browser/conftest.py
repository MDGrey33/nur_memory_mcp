"""
Pytest Configuration for Browser Tests (MCP Inspector).

Provides:
- Browser fixtures for Playwright
- MCP Inspector navigation helpers
- Connection flow utilities
"""

from __future__ import annotations

import os
import pytest
from typing import Generator
from playwright.sync_api import Page, Browser, BrowserContext, Playwright, sync_playwright


# =============================================================================
# Environment Configuration
# =============================================================================

MCP_URL = os.getenv("MCP_URL", "http://localhost:3201/mcp/")
MCP_INSPECTOR_URL = os.getenv("MCP_INSPECTOR_URL", "http://localhost:6274/")
MCP_PROXY_AUTH_TOKEN = os.getenv("MCP_PROXY_AUTH_TOKEN", "")


# =============================================================================
# Browser Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def playwright_instance() -> Generator[Playwright, None, None]:
    """Session-scoped Playwright instance."""
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright_instance: Playwright) -> Generator[Browser, None, None]:
    """Session-scoped browser instance."""
    # Use chromium by default, can be configured via env
    browser_type = os.getenv("BROWSER", "chromium")
    headless = os.getenv("HEADLESS", "true").lower() == "true"
    slow_mo = int(os.getenv("SLOW_MO", "0"))

    browser = getattr(playwright_instance, browser_type).launch(
        headless=headless,
        slow_mo=slow_mo
    )
    yield browser
    browser.close()


@pytest.fixture(scope="function")
def browser_context(browser: Browser) -> Generator[BrowserContext, None, None]:
    """Function-scoped browser context for test isolation."""
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir="reports/videos" if os.getenv("RECORD_VIDEO") else None
    )
    yield context
    context.close()


@pytest.fixture(scope="function")
def page(browser_context: BrowserContext) -> Generator[Page, None, None]:
    """Function-scoped page for each test."""
    page = browser_context.new_page()
    yield page
    page.close()


# =============================================================================
# Inspector Navigation Fixtures
# =============================================================================

@pytest.fixture
def inspector_url() -> str:
    """Get MCP Inspector URL with auth token if configured."""
    if MCP_PROXY_AUTH_TOKEN:
        return f"{MCP_INSPECTOR_URL}?MCP_PROXY_AUTH_TOKEN={MCP_PROXY_AUTH_TOKEN}"
    return MCP_INSPECTOR_URL


@pytest.fixture
def mcp_server_url() -> str:
    """Get MCP server URL for connection."""
    return MCP_URL


@pytest.fixture
def inspector_page(page: Page, inspector_url: str) -> Generator[Page, None, None]:
    """Page navigated to MCP Inspector."""
    page.goto(inspector_url)
    page.wait_for_load_state("networkidle")
    yield page


# =============================================================================
# Connection Helper Fixtures
# =============================================================================

@pytest.fixture
def connect_to_mcp(inspector_page: Page, mcp_server_url: str):
    """Factory fixture to connect to MCP server."""
    def _connect(custom_url: str = None) -> Page:
        url = custom_url or mcp_server_url

        # Select Streamable HTTP transport
        inspector_page.locator("select").first.select_option(label="Streamable HTTP")

        # Enter URL
        url_input = inspector_page.locator("input[type='text']").first
        url_input.fill(url)

        # Click Connect
        inspector_page.click("button:has-text('Connect')")

        # Wait for connection
        inspector_page.wait_for_selector("text=Connected", timeout=15000)

        return inspector_page

    return _connect


@pytest.fixture
def connected_inspector(connect_to_mcp) -> Page:
    """Page already connected to MCP server."""
    return connect_to_mcp()


# =============================================================================
# Tool Execution Fixtures
# =============================================================================

@pytest.fixture
def list_tools(connected_inspector: Page):
    """Factory to list tools and return to tools page."""
    def _list_tools() -> Page:
        # Navigate to Tools tab if not already there
        tools_tab = connected_inspector.locator("text=Tools").first
        if tools_tab.is_visible():
            tools_tab.click()

        # Click List Tools
        connected_inspector.click("button:has-text('List Tools')")
        connected_inspector.wait_for_timeout(2000)

        return connected_inspector

    return _list_tools


@pytest.fixture
def execute_tool(connected_inspector: Page, list_tools):
    """Factory to execute a tool with parameters."""
    def _execute(tool_name: str, params: dict = None) -> dict:
        page = list_tools()

        # Click on the tool
        page.click(f"text={tool_name}")
        page.wait_for_timeout(500)

        # Fill parameters if provided
        if params:
            for key, value in params.items():
                # Try to find input by name or placeholder
                input_selector = f"input[name='{key}'], textarea[name='{key}']"
                input_el = page.locator(input_selector).first
                if input_el.is_visible():
                    if isinstance(value, str):
                        input_el.fill(value)
                    else:
                        input_el.fill(str(value))

        # Click Run/Execute
        run_button = page.locator("button:has-text('Run'), button:has-text('Execute')").first
        run_button.click()

        # Wait for result
        page.wait_for_timeout(3000)

        # Return page for further assertions
        return {"page": page}

    return _execute


# =============================================================================
# Screenshot Fixtures
# =============================================================================

@pytest.fixture
def screenshot_on_failure(page: Page, request):
    """Capture screenshot on test failure."""
    yield

    if request.node.rep_call.failed:
        screenshot_dir = "reports/screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        screenshot_path = f"{screenshot_dir}/{request.node.name}.png"
        page.screenshot(path=screenshot_path, full_page=True)


# =============================================================================
# Expected Tools List
# =============================================================================

EXPECTED_TOOLS = [
    "memory_store",
    "memory_search",
    "memory_list",
    "memory_delete",
    "history_append",
    "history_get",
    "artifact_ingest",
    "artifact_search",
    "artifact_get",
    "artifact_delete",
    "hybrid_search",
    "embedding_health",
    "event_search_tool",
    "event_get_tool",
    "event_list_for_artifact",
    "event_reextract",
    "job_status"
]


@pytest.fixture
def expected_tools() -> list:
    """List of expected MCP tools."""
    return EXPECTED_TOOLS
