"""
Playwright API Tests for MCP Memory Server.

This package contains API tests that use the JSON-RPC protocol
to test MCP tools directly without browser automation.

Test files:
- test_health.py: Health check and smoke tests
- test_memory.py: Memory tool tests (store, search, list, delete)
- test_event.py: V3 event tools (event_search, event_get, event_list, event_reextract, job_status)
- test_hybrid_search.py: Hybrid search tests

Run tests:
    # All API tests
    pytest tests/playwright/api/ -v

    # Memory tests only
    pytest tests/playwright/api/test_memory.py -v

    # Event tests only (V3)
    pytest tests/playwright/api/test_event.py -v -m "event"
    pytest tests/playwright/api/test_event.py -v -m "v3"

    # Tests with specific marker
    pytest tests/playwright/api/ -v -m memory
    pytest tests/playwright/api/ -v -m event
    pytest tests/playwright/api/ -v -m v3

    # Skip slow/performance tests
    pytest tests/playwright/api/ -v -m "not slow"
"""
