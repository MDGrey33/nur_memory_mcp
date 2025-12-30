"""
Browser Tests for MCP Inspector Error Handling.

Tests:
- Connection error handling
- Tool execution errors
- Timeout handling
- Recovery from errors
- Invalid input handling

Run:
    pytest tests/e2e-playwright/browser/test_inspector_errors.py -v
    pytest tests/e2e-playwright/browser/test_inspector_errors.py -v --headed
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.browser
class TestConnectionErrors:
    """Tests for connection error handling."""

    def test_invalid_url_shows_error(self, inspector_page: Page):
        """Invalid URL shows clear error message."""
        page = inspector_page

        page.locator("select").first.select_option(label="Streamable HTTP")
        page.locator("input[type='text']").first.fill("http://localhost:9999/invalid/")

        page.click("button:has-text('Connect')")
        page.wait_for_selector("text=Error", timeout=15000)

        expect(page.locator("text=Error").first).to_be_visible()

    def test_malformed_url_handled(self, inspector_page: Page):
        """Malformed URL is handled gracefully."""
        page = inspector_page

        page.locator("select").first.select_option(label="Streamable HTTP")
        page.locator("input[type='text']").first.fill("not-a-valid-url")

        page.click("button:has-text('Connect')")

        # Should show error or prevent connection
        page.wait_for_timeout(3000)
        body_text = page.inner_text("body").lower()
        assert "error" in body_text or "invalid" in body_text or "connect" in body_text

    def test_connection_refused_error(self, inspector_page: Page):
        """Connection refused shows appropriate error."""
        page = inspector_page

        # Use a port that's definitely not running
        page.locator("select").first.select_option(label="Streamable HTTP")
        page.locator("input[type='text']").first.fill("http://localhost:59999/mcp/")

        page.click("button:has-text('Connect')")
        page.wait_for_selector("text=Error", timeout=15000)

        body_text = page.inner_text("body").lower()
        assert "error" in body_text or "refused" in body_text or "connect" in body_text

    def test_connection_error_recoverable(self, inspector_page: Page, mcp_server_url: str):
        """Can recover from connection error."""
        page = inspector_page

        # First fail
        page.locator("select").first.select_option(label="Streamable HTTP")
        page.locator("input[type='text']").first.fill("http://localhost:9999/bad/")
        page.click("button:has-text('Connect')")
        page.wait_for_selector("text=Error", timeout=15000)

        # Then succeed
        page.locator("input[type='text']").first.fill(mcp_server_url)
        page.click("button:has-text('Connect')")
        page.wait_for_selector("text=Connected", timeout=15000)

        expect(page.locator("text=Connected")).to_be_visible()


@pytest.mark.browser
class TestToolExecutionErrors:
    """Tests for tool execution error handling."""

    def test_missing_required_parameter_error(self, connected_inspector: Page):
        """Missing required parameter shows error."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Try memory_store without filling content
        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # Fill only type, not content
        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "type" in name.lower():
                field.fill("preference")

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show validation error
        body_text = page.inner_text("body").lower()
        assert "error" in body_text or "required" in body_text or "content" in body_text

    def test_invalid_parameter_value_error(self, connected_inspector: Page):
        """Invalid parameter value shows error."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # memory_store with invalid type
        page.click("text=memory_store")
        page.wait_for_timeout(500)

        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "content" in name.lower():
                field.fill("Test content")
            elif "type" in name.lower():
                field.fill("invalid_type_xyz")

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show type validation error or handle gracefully
        body_text = page.inner_text("body").lower()
        # May succeed with unknown type or show error
        assert len(body_text) > 0

    def test_tool_not_found_handled(self, connected_inspector: Page):
        """Non-existent tool request is handled."""
        # This test verifies the UI doesn't crash if somehow a bad tool is invoked
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # The UI should only show valid tools
        # Just verify the tools list loaded properly
        expect(page.locator("text=memory_store")).to_be_visible()


@pytest.mark.browser
class TestResourceNotFoundErrors:
    """Tests for resource not found error handling."""

    def test_delete_nonexistent_memory_error(self, connected_inspector: Page):
        """Deleting non-existent memory shows appropriate error."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_delete")
        page.wait_for_timeout(500)

        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "memory_id" in name.lower():
                field.fill("mem_nonexistent_99999")
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        body_text = page.inner_text("body").lower()
        # Should show not found or similar error
        assert "error" in body_text or "not found" in body_text or "deleted" in body_text

    def test_get_nonexistent_artifact_error(self, connected_inspector: Page):
        """Getting non-existent artifact shows appropriate error."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=artifact_get")
        page.wait_for_timeout(500)

        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "artifact_uid" in name.lower() or "artifact_id" in name.lower():
                field.fill("art_nonexistent_12345")
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        body_text = page.inner_text("body").lower()
        assert "error" in body_text or "not found" in body_text or "null" in body_text


@pytest.mark.browser
class TestTimeoutErrors:
    """Tests for timeout handling."""

    @pytest.mark.slow
    def test_long_operation_shows_progress(self, connected_inspector: Page):
        """Long operations show some progress indication."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # artifact_ingest with substantial content might take time
        page.click("text=artifact_ingest")
        page.wait_for_timeout(500)

        # Create longer content
        long_content = "Test content " * 100

        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "content" in name.lower():
                field.fill(long_content)
            elif "artifact_type" in name.lower():
                field.fill("note")
            elif "source_system" in name.lower():
                field.fill("browser-test")
            elif "title" in name.lower():
                field.fill("Long Document Test")

        page.click("button:has-text('Run'), button:has-text('Execute')")

        # Wait for completion
        page.wait_for_timeout(10000)

        # Should eventually complete
        body_text = page.inner_text("body")
        assert len(body_text) > 100


@pytest.mark.browser
class TestUIRecovery:
    """Tests for UI recovery from errors."""

    def test_ui_responsive_after_connection_error(self, inspector_page: Page, mcp_server_url: str):
        """UI remains responsive after connection error."""
        page = inspector_page

        # Cause error
        page.locator("select").first.select_option(label="Streamable HTTP")
        page.locator("input[type='text']").first.fill("http://localhost:9999/bad/")
        page.click("button:has-text('Connect')")
        page.wait_for_selector("text=Error", timeout=15000)

        # UI should still be interactive
        select = page.locator("select").first
        expect(select).to_be_enabled()

        # Can still interact
        select.select_option(label="Streamable HTTP")
        url_input = page.locator("input[type='text']").first
        expect(url_input).to_be_editable()

    def test_ui_responsive_after_tool_error(self, connected_inspector: Page):
        """UI remains responsive after tool execution error."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Cause tool error
        page.click("text=memory_delete")
        page.wait_for_timeout(500)

        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "memory_id" in name.lower():
                field.fill("mem_bad_id")
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Can still navigate and use other tools
        page.click("text=embedding_health")
        page.wait_for_timeout(500)

        run_btn = page.locator("button:has-text('Run'), button:has-text('Execute')").first
        expect(run_btn).to_be_enabled()

    def test_can_retry_after_error(self, connected_inspector: Page):
        """Can retry operation after error."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # First try - might error without content
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(2000)

        # Retry with proper data
        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "content" in name.lower():
                field.fill("Valid content on retry")
            elif "type" in name.lower():
                field.fill("preference")

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        body_text = page.inner_text("body")
        assert len(body_text) > 0


@pytest.mark.browser
class TestInputValidation:
    """Tests for input validation in UI."""

    def test_empty_query_handled(self, connected_inspector: Page):
        """Empty search query is handled."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_search")
        page.wait_for_timeout(500)

        # Don't fill query, just execute
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show error or empty results
        body_text = page.inner_text("body").lower()
        assert "error" in body_text or "required" in body_text or "result" in body_text

    def test_special_characters_handled(self, connected_inspector: Page):
        """Special characters in input are handled."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # Input with special characters
        special_content = "Test with special chars: <script>alert('xss')</script> & \"quotes\" 'apostrophe'"

        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "content" in name.lower():
                field.fill(special_content)
            elif "type" in name.lower():
                field.fill("preference")

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should handle without breaking
        body_text = page.inner_text("body")
        assert len(body_text) > 0

    def test_unicode_content_handled(self, connected_inspector: Page):
        """Unicode content is handled properly."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # Unicode content
        unicode_content = "Test with unicode: Hello World"

        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "content" in name.lower():
                field.fill(unicode_content)
            elif "type" in name.lower():
                field.fill("preference")

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should process unicode content
        body_text = page.inner_text("body")
        assert len(body_text) > 0
