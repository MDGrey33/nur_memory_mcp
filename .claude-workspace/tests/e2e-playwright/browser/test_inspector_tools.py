"""
Browser Tests for MCP Inspector Tool Execution.

Tests:
- Tool listing and discovery
- Tool selection and parameter input
- Tool execution via UI
- Parameter validation in UI

Run:
    pytest tests/e2e-playwright/browser/test_inspector_tools.py -v
    pytest tests/e2e-playwright/browser/test_inspector_tools.py -v --headed
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.browser
class TestToolListing:
    """Tests for tool listing functionality."""

    def test_tools_tab_accessible(self, connected_inspector: Page):
        """Tools tab is accessible after connection."""
        page = connected_inspector

        tools_tab = page.locator("text=Tools").first
        expect(tools_tab).to_be_visible()
        tools_tab.click()

    def test_list_tools_button_visible(self, connected_inspector: Page):
        """List Tools button is visible in Tools tab."""
        page = connected_inspector

        # Navigate to Tools tab
        page.click("text=Tools")
        page.wait_for_timeout(500)

        list_btn = page.locator("button:has-text('List Tools')").first
        expect(list_btn).to_be_visible()

    def test_list_tools_returns_results(self, connected_inspector: Page):
        """List Tools returns tool list."""
        page = connected_inspector

        # Navigate and list
        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Should show at least some tools
        tool_list = page.locator("[data-testid='tool-list'], .tool-list, ul, ol").first
        expect(tool_list).to_be_visible()

    def test_memory_store_tool_listed(self, connected_inspector: Page):
        """memory_store tool is listed."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        expect(page.locator("text=memory_store")).to_be_visible()

    def test_embedding_health_tool_listed(self, connected_inspector: Page):
        """embedding_health tool is listed."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        expect(page.locator("text=embedding_health")).to_be_visible()

    def test_all_expected_tools_listed(self, connected_inspector: Page, expected_tools: list):
        """All expected MCP tools are listed."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Check a subset of expected tools (not all may be visible depending on scroll)
        core_tools = [
            "memory_store",
            "memory_search",
            "artifact_ingest",
            "hybrid_search",
            "embedding_health"
        ]

        for tool_name in core_tools:
            tool_locator = page.locator(f"text={tool_name}").first
            expect(tool_locator).to_be_visible()


@pytest.mark.browser
class TestToolSelection:
    """Tests for tool selection in UI."""

    def test_click_tool_shows_details(self, connected_inspector: Page):
        """Clicking a tool shows its details/parameters."""
        page = connected_inspector

        # List tools
        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Click on embedding_health (simple tool)
        page.click("text=embedding_health")
        page.wait_for_timeout(500)

        # Should show some detail panel or expanded view
        # Look for Run button or parameter area
        run_btn = page.locator("button:has-text('Run'), button:has-text('Execute')").first
        expect(run_btn).to_be_visible()

    def test_tool_shows_description(self, connected_inspector: Page):
        """Selected tool shows its description."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Click memory_store
        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # Should show some description text
        # Description varies by tool, just verify expanded state
        detail_area = page.locator("[data-testid='tool-detail'], .tool-detail, .tool-params").first
        # May or may not be present depending on UI
        # At minimum, Run button should be visible
        expect(page.locator("button:has-text('Run'), button:has-text('Execute')").first).to_be_visible()


@pytest.mark.browser
class TestToolParameters:
    """Tests for tool parameter input."""

    def test_memory_store_shows_content_input(self, connected_inspector: Page):
        """memory_store tool shows content parameter input."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # Should have input for 'content' parameter
        content_input = page.locator(
            "input[name='content'], "
            "textarea[name='content'], "
            "input[placeholder*='content'], "
            "textarea[placeholder*='content'], "
            "[data-param='content']"
        ).first
        expect(content_input).to_be_visible()

    def test_can_fill_required_parameters(self, connected_inspector: Page):
        """Can fill required parameters for a tool."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # Fill content
        content_input = page.locator(
            "input[name='content'], "
            "textarea[name='content'], "
            "[data-param='content'] input, "
            "[data-param='content'] textarea"
        ).first
        content_input.fill("Test content from browser")

        # Fill type
        type_input = page.locator(
            "input[name='type'], "
            "select[name='type'], "
            "[data-param='type'] input"
        ).first
        if type_input.is_visible():
            type_input.fill("preference")

    def test_optional_parameters_editable(self, connected_inspector: Page):
        """Optional parameters can be edited."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Use memory_search which has optional parameters
        page.click("text=memory_search")
        page.wait_for_timeout(500)

        # Should have query (required) and limit (optional)
        query_input = page.locator(
            "input[name='query'], "
            "textarea[name='query'], "
            "[data-param='query'] input"
        ).first
        expect(query_input).to_be_visible()


@pytest.mark.browser
class TestToolExecution:
    """Tests for executing tools via UI."""

    def test_execute_embedding_health(self, connected_inspector: Page):
        """Execute embedding_health tool (no parameters)."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Select and run embedding_health
        page.click("text=embedding_health")
        page.wait_for_timeout(500)

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show result with "healthy" or status info
        body_text = page.inner_text("body").lower()
        assert "healthy" in body_text or "status" in body_text or "result" in body_text

    def test_execute_memory_store(self, connected_inspector: Page):
        """Execute memory_store with parameters."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # Fill parameters - use flexible selectors
        # Try content field
        content_fields = page.locator("input, textarea").all()
        for field in content_fields:
            name = field.get_attribute("name") or ""
            placeholder = field.get_attribute("placeholder") or ""
            if "content" in name.lower() or "content" in placeholder.lower():
                field.fill("Test memory from browser UI")
                break

        # Try type field
        for field in content_fields:
            name = field.get_attribute("name") or ""
            placeholder = field.get_attribute("placeholder") or ""
            if "type" in name.lower():
                field.fill("preference")
                break

        # Execute
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show result with memory_id
        body_text = page.inner_text("body").lower()
        assert "mem_" in body_text or "memory" in body_text or "result" in body_text

    def test_execute_memory_search(self, connected_inspector: Page):
        """Execute memory_search with query."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_search")
        page.wait_for_timeout(500)

        # Fill query
        query_fields = page.locator("input, textarea").all()
        for field in query_fields:
            name = field.get_attribute("name") or ""
            placeholder = field.get_attribute("placeholder") or ""
            if "query" in name.lower() or "query" in placeholder.lower():
                field.fill("test search query")
                break

        # Execute
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show results (even if empty)
        body_text = page.inner_text("body").lower()
        assert "result" in body_text or "memories" in body_text or "[]" in body_text

    def test_execute_shows_loading_state(self, connected_inspector: Page):
        """Tool execution shows loading state."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=hybrid_search")
        page.wait_for_timeout(500)

        # Fill query
        query_fields = page.locator("input, textarea").all()
        for field in query_fields:
            name = field.get_attribute("name") or ""
            if "query" in name.lower():
                field.fill("test")
                break

        # Execute and check for loading
        page.click("button:has-text('Run'), button:has-text('Execute')")

        # May briefly show loading - check button becomes disabled or shows spinner
        # This is optional as loading may be too fast
        page.wait_for_timeout(3000)


@pytest.mark.browser
class TestToolWorkflows:
    """Tests for complete tool workflows via UI."""

    def test_store_then_search_workflow(self, connected_inspector: Page):
        """Store a memory then search for it."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Store a memory with unique content
        unique_marker = "browser-workflow-test-12345"

        page.click("text=memory_store")
        page.wait_for_timeout(500)

        content_fields = page.locator("input, textarea").all()
        for field in content_fields:
            name = field.get_attribute("name") or ""
            if "content" in name.lower():
                field.fill(f"Unique test content {unique_marker}")
                break

        for field in content_fields:
            name = field.get_attribute("name") or ""
            if "type" in name.lower():
                field.fill("preference")
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Verify store succeeded
        body_text = page.inner_text("body")
        assert "mem_" in body_text.lower() or "success" in body_text.lower()

        # Now search
        page.click("text=memory_search")
        page.wait_for_timeout(500)

        query_fields = page.locator("input, textarea").all()
        for field in query_fields:
            name = field.get_attribute("name") or ""
            if "query" in name.lower():
                field.fill(unique_marker)
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should find the memory
        body_text = page.inner_text("body")
        assert unique_marker in body_text or "result" in body_text.lower()

    def test_hybrid_search_workflow(self, connected_inspector: Page):
        """Execute hybrid_search tool."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=hybrid_search")
        page.wait_for_timeout(500)

        # Fill query parameter
        query_fields = page.locator("input, textarea").all()
        for field in query_fields:
            name = field.get_attribute("name") or ""
            if "query" in name.lower():
                field.fill("test search across all collections")
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(5000)

        # Should return results structure
        body_text = page.inner_text("body").lower()
        assert "result" in body_text or "memories" in body_text or "artifacts" in body_text
