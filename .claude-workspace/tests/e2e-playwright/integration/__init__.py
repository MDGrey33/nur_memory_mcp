"""
Integration Tests for MCP Memory Server.

This package contains end-to-end integration tests that verify cross-service
functionality:

- test_event_extraction_pipeline.py: Full extraction pipeline tests
  (ingest -> job completes -> events created with correct categories)

- test_entity_resolution.py: V4 entity extraction and POSSIBLY_SAME edges

- test_graph_expansion.py: hybrid_search with graph_expand=true

These tests require:
- MCP server running (port 3201 by default)
- PostgreSQL running (for event/entity storage)
- Event extraction worker running (for some tests)
- ChromaDB running (for embeddings)

Markers:
- @pytest.mark.integration: All integration tests
- @pytest.mark.v3: V3-specific tests (basic event extraction)
- @pytest.mark.v4: V4-specific tests (entity resolution, graph expansion)
- @pytest.mark.slow: Tests that may take >30 seconds
- @pytest.mark.requires_worker: Tests requiring event extraction worker

Usage:
    # Run all integration tests
    pytest tests/e2e-playwright/integration -v

    # Run V4 tests only
    pytest tests/e2e-playwright/integration -v -m "v4"

    # Run slow tests with extended timeout
    pytest tests/e2e-playwright/integration -v -m "slow" --timeout=300
"""
