"""
Playwright Test Suite for MCP Memory Server.

This package contains:
- api/: API tests using Playwright's request fixture
- browser/: Browser tests for MCP Inspector UI

Usage:
    pytest tests/playwright/ -v
    pytest tests/playwright/api/ -v -m "api"
    pytest tests/playwright/api/ -v -m "event and v3"
"""
