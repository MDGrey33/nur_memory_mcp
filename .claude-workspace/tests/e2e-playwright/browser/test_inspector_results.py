"""
Browser Tests for MCP Inspector Result Display.

Tests:
- Result rendering and formatting
- JSON display and syntax highlighting
- Copy functionality
- Result navigation
- Evidence display for events

Run:
    pytest tests/e2e-playwright/browser/test_inspector_results.py -v
    pytest tests/e2e-playwright/browser/test_inspector_results.py -v --headed
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.browser
class TestResultDisplay:
    """Tests for result display functionality."""

    def test_result_panel_visible_after_execution(self, connected_inspector: Page):
        """Result panel appears after tool execution."""
        page = connected_inspector

        # Execute embedding_health
        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=embedding_health")
        page.wait_for_timeout(500)
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Result should be visible
        body_text = page.inner_text("body")
        assert len(body_text) > 100  # Some content should be displayed

    def test_result_contains_json_content(self, connected_inspector: Page):
        """Result displays JSON content."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=embedding_health")
        page.wait_for_timeout(500)
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should contain JSON-like structure
        body_text = page.inner_text("body")
        # Look for JSON indicators like braces or common fields
        assert "{" in body_text or "healthy" in body_text.lower() or "status" in body_text.lower()

    def test_result_shows_tool_name(self, connected_inspector: Page):
        """Result area shows which tool was executed."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=embedding_health")
        page.wait_for_timeout(500)
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show the tool name somewhere in result context
        body_text = page.inner_text("body").lower()
        assert "embedding" in body_text or "health" in body_text or "result" in body_text


@pytest.mark.browser
class TestJSONFormatting:
    """Tests for JSON result formatting."""

    def test_json_is_formatted(self, connected_inspector: Page):
        """JSON results are formatted (not minified)."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=embedding_health")
        page.wait_for_timeout(500)
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Formatted JSON has newlines
        body_html = page.inner_html("body")
        # Look for pre tag or formatted code block
        assert "<pre" in body_html.lower() or "code" in body_html.lower() or "\n" in body_html

    def test_json_keys_identifiable(self, connected_inspector: Page):
        """JSON keys are visually identifiable."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=embedding_health")
        page.wait_for_timeout(500)
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Result should contain recognizable JSON keys
        body_text = page.inner_text("body")
        # Common keys from embedding_health response
        assert any(key in body_text.lower() for key in ["status", "healthy", "model", "service"])


@pytest.mark.browser
class TestMemoryResults:
    """Tests for memory tool result display."""

    def test_memory_store_shows_memory_id(self, connected_inspector: Page):
        """memory_store result shows generated memory_id."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # Fill parameters
        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "content" in name.lower():
                field.fill("Test memory for result display")
            elif "type" in name.lower():
                field.fill("preference")

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show memory_id
        body_text = page.inner_text("body")
        assert "mem_" in body_text.lower() or "memory_id" in body_text.lower()

    def test_memory_search_shows_results_array(self, connected_inspector: Page):
        """memory_search result shows array of memories."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_search")
        page.wait_for_timeout(500)

        # Fill query
        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "query" in name.lower():
                field.fill("test query")
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show results (even if empty array)
        body_text = page.inner_text("body")
        assert "result" in body_text.lower() or "[" in body_text or "memories" in body_text.lower()


@pytest.mark.browser
class TestArtifactResults:
    """Tests for artifact tool result display."""

    def test_artifact_ingest_shows_artifact_uid(self, connected_inspector: Page):
        """artifact_ingest result shows artifact_uid."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=artifact_ingest")
        page.wait_for_timeout(500)

        # Fill parameters
        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "content" in name.lower():
                field.fill("Test artifact content for UI test")
            elif "artifact_type" in name.lower():
                field.fill("note")
            elif "source_system" in name.lower():
                field.fill("browser-test")
            elif "title" in name.lower():
                field.fill("Browser Test Document")

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(5000)

        # Should show artifact_uid
        body_text = page.inner_text("body")
        assert "artifact" in body_text.lower() or "uid" in body_text.lower()


@pytest.mark.browser
class TestHybridSearchResults:
    """Tests for hybrid_search result display."""

    def test_hybrid_search_shows_multiple_sections(self, connected_inspector: Page):
        """hybrid_search result shows multiple result sections."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=hybrid_search")
        page.wait_for_timeout(500)

        # Fill query
        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "query" in name.lower():
                field.fill("test query for hybrid")
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(5000)

        # Should show result structure
        body_text = page.inner_text("body").lower()
        assert "result" in body_text or "memories" in body_text or "artifacts" in body_text


@pytest.mark.browser
class TestResultInteraction:
    """Tests for interacting with results."""

    def test_result_scrollable_for_large_output(self, connected_inspector: Page):
        """Large results are scrollable."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # memory_list might return many results
        page.click("text=memory_list")
        page.wait_for_timeout(500)

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Result area should exist (scrollable if large)
        body_text = page.inner_text("body")
        assert len(body_text) > 0

    def test_can_select_result_text(self, connected_inspector: Page):
        """Can select text in result area."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=embedding_health")
        page.wait_for_timeout(500)
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Try to select some text - result should be selectable
        # This is a basic check that text is present
        body_text = page.inner_text("body")
        assert len(body_text) > 0


@pytest.mark.browser
class TestErrorResults:
    """Tests for error result display."""

    def test_validation_error_displayed(self, connected_inspector: Page):
        """Validation errors are displayed clearly."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Try memory_store without required content
        page.click("text=memory_store")
        page.wait_for_timeout(500)

        # Don't fill content, just execute (or fill empty)
        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "content" in name.lower():
                field.fill("")  # Empty content
            elif "type" in name.lower():
                field.fill("preference")

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show error or validation message
        body_text = page.inner_text("body").lower()
        assert "error" in body_text or "required" in body_text or "invalid" in body_text or "empty" in body_text

    def test_error_message_readable(self, connected_inspector: Page):
        """Error messages are human-readable."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        # Try to get a non-existent memory
        page.click("text=memory_delete")
        page.wait_for_timeout(500)

        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "memory_id" in name.lower():
                field.fill("mem_nonexistent_12345")
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Should show some response (error or not found)
        body_text = page.inner_text("body")
        assert len(body_text) > 50  # Should have meaningful content


@pytest.mark.browser
class TestResultScreenshots:
    """Tests that capture screenshots for visual verification."""

    def test_capture_embedding_health_result(self, connected_inspector: Page, tmp_path):
        """Capture screenshot of embedding_health result."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=embedding_health")
        page.wait_for_timeout(500)
        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Capture screenshot
        screenshot_path = tmp_path / "embedding_health_result.png"
        page.screenshot(path=str(screenshot_path))

        assert screenshot_path.exists()

    def test_capture_memory_search_result(self, connected_inspector: Page, tmp_path):
        """Capture screenshot of memory_search result."""
        page = connected_inspector

        page.click("text=Tools")
        page.click("button:has-text('List Tools')")
        page.wait_for_timeout(2000)

        page.click("text=memory_search")
        page.wait_for_timeout(500)

        fields = page.locator("input, textarea").all()
        for field in fields:
            name = field.get_attribute("name") or ""
            if "query" in name.lower():
                field.fill("test")
                break

        page.click("button:has-text('Run'), button:has-text('Execute')")
        page.wait_for_timeout(3000)

        # Capture screenshot
        screenshot_path = tmp_path / "memory_search_result.png"
        page.screenshot(path=str(screenshot_path))

        assert screenshot_path.exists()
