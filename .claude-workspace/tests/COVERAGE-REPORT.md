# V4 Test Coverage Report

Generated: [TIMESTAMP]

## Summary

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Overall Coverage | >80% | TBD% | [ ] |
| Entity Resolution Service | >80% | TBD% | [ ] |
| Graph Service | >80% | TBD% | [ ] |
| Retrieval Service (V4) | >80% | TBD% | [ ] |
| Event Extraction (V4) | >80% | TBD% | [ ] |

## Test Suite Summary

### Unit Tests

| Test File | Tests | Passed | Failed | Coverage |
|-----------|-------|--------|--------|----------|
| `test_entity_resolution_service.py` | TBD | TBD | TBD | TBD% |
| `test_graph_service.py` | TBD | TBD | TBD | TBD% |

### Integration Tests

| Test File | Tests | Passed | Failed | Coverage |
|-----------|-------|--------|--------|----------|
| `test_v4_extraction_integration.py` | TBD | TBD | TBD | TBD% |
| `test_v4_search_integration.py` | TBD | TBD | TBD | TBD% |

### E2E Tests

| Test File | Tests | Passed | Failed | Notes |
|-----------|-------|--------|--------|-------|
| `test_v4_e2e.py` | 10 | TBD | TBD | All 10 spec tests |

## E2E Test Results

| # | Test Name | Status | Notes |
|---|-----------|--------|-------|
| 1 | `test_entity_extraction_rich_context` | [ ] | Entity with role/org/email |
| 2 | `test_entity_dedup_same_person` | [ ] | Merge same person |
| 3 | `test_entity_dedup_different_people` | [ ] | Keep different people separate |
| 4 | `test_uncertain_merge_creates_possibly_same` | [ ] | POSSIBLY_SAME edge |
| 5 | `test_graph_upsert_materializes_nodes` | [ ] | Graph nodes/edges |
| 6 | `test_hybrid_search_expand_options` | [ ] | expand_options in response |
| 7 | `test_related_context_connected_bounded` | [ ] | Related context from graph |
| 8 | `test_graph_seed_limit_respected` | [ ] | Seed limit enforcement |
| 9 | `test_backward_compatibility` | [ ] | V3 compatible output |
| 10 | `test_chunk_to_revision_mapping` | [ ] | Chunk -> revision -> events |

## Coverage by Component

### EntityResolutionService

```
services/entity_resolution_service.py
--------------------------------------
Lines:         TBD / TBD (TBD%)
Branches:      TBD / TBD (TBD%)
Functions:     TBD / TBD (TBD%)

Methods Covered:
- [x] __init__
- [x] find_dedup_candidates
- [x] confirm_merge_with_llm
- [x] create_entity
- [x] merge_entity
- [x] add_alias
- [x] record_mention
- [x] resolve_entity
- [x] resolve_extracted_entity
- [x] generate_context_embedding
- [x] _normalize_name
- [x] get_uncertain_pairs
```

### GraphService

```
services/graph_service.py
--------------------------------------
Lines:         TBD / TBD (TBD%)
Branches:      TBD / TBD (TBD%)
Functions:     TBD / TBD (TBD%)

Methods Covered:
- [x] __init__
- [x] check_age_available
- [x] _ensure_age_session
- [x] execute_cypher
- [x] _substitute_params
- [x] _parse_agtype
- [x] upsert_entity_node
- [x] upsert_event_node
- [x] upsert_acted_in_edge
- [x] upsert_about_edge
- [x] upsert_possibly_same_edge
- [x] expand_from_events
- [x] get_health
- [x] get_entities_for_events
```

### RetrievalService (V4)

```
services/retrieval_service.py
--------------------------------------
Lines:         TBD / TBD (TBD%)
Branches:      TBD / TBD (TBD%)
Functions:     TBD / TBD (TBD%)

V4 Methods Covered:
- [x] hybrid_search_v4
- [x] _perform_graph_expansion
- [x] _get_seed_events
- [x] get_artifact_uid_for_chunk
```

### EventExtractionService (V4)

```
services/event_extraction_service.py
--------------------------------------
Lines:         TBD / TBD (TBD%)
Branches:      TBD / TBD (TBD%)
Functions:     TBD / TBD (TBD%)

V4 Methods Covered:
- [x] extract_from_chunk_v4
- [x] validate_entity
- [x] deduplicate_entities
```

## Uncovered Code

### Critical Uncovered Lines

List any critical paths not covered by tests:

1. TBD
2. TBD

### Acceptable Uncovered Lines

Lines intentionally not covered (with justification):

1. Error handling edge cases in AGE queries (tested manually)
2. Logging statements
3. `__repr__` methods

## Test Environment

- Python Version: 3.11+
- Pytest Version: 7.x+
- pytest-asyncio Version: 0.21+
- pytest-cov Version: 4.x+

## Running Tests

### Run All V4 Tests

```bash
cd .claude-workspace/implementation/mcp-server
pytest tests/v4/ -v --cov=src/services --cov-report=html
```

### Run by Category

```bash
# Unit tests only
pytest tests/v4/unit/ -v -m unit

# Integration tests only
pytest tests/v4/integration/ -v -m integration

# E2E tests only
pytest tests/v4/e2e/ -v -m e2e

# All V4 tests
pytest tests/v4/ -v -m v4
```

### Run with Coverage

```bash
pytest tests/v4/ -v \
    --cov=src/services/entity_resolution_service \
    --cov=src/services/graph_service \
    --cov=src/services/retrieval_service \
    --cov=src/services/event_extraction_service \
    --cov-report=term-missing \
    --cov-report=html:coverage_v4
```

### Run Specific E2E Tests

```bash
# Run a specific E2E test
pytest tests/v4/e2e/test_v4_e2e.py::TestEntityExtractionRichContext -v

# Run all E2E tests
pytest tests/v4/e2e/ -v -m e2e
```

## Test Dependencies

Required packages for running tests:

```
pytest>=7.0.0
pytest-asyncio>=0.21.0
pytest-cov>=4.0.0
pytest-mock>=3.10.0
```

## Known Issues

1. AGE tests require Apache AGE extension (mocked in unit tests)
2. Embedding tests require OpenAI API key (mocked in tests)
3. Some integration tests may be slow due to mock setup

## Improvement Opportunities

1. [ ] Add property-based tests for entity resolution
2. [ ] Add stress tests for graph expansion
3. [ ] Add benchmark tests for search performance
4. [ ] Add mutation testing for critical paths

## History

| Date | Coverage | Notes |
|------|----------|-------|
| TBD | TBD% | Initial V4 test suite |

---

*Report generated by pytest-cov. Update manually or regenerate with `pytest --cov-report=html`*
