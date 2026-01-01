"""
V5 Test Suite

Integration, unit, and E2E tests for V5 simplified API:
- remember() - Store content with deduplication
- recall() - Find content with graph expansion
- forget() - Delete with cascade
- status() - System health

Test Organization:
- unit/: Unit tests for V5 collections and helpers
- integration/: Integration tests for V5 tools
- e2e/: End-to-end acceptance tests

Running Tests:
    # Run all V5 tests
    pytest .claude-workspace/tests/v5/ -v

    # Run only integration tests
    pytest .claude-workspace/tests/v5/integration/ -v

    # Run only E2E tests (requires infrastructure)
    pytest .claude-workspace/tests/v5/e2e/ -v --run-e2e
"""
