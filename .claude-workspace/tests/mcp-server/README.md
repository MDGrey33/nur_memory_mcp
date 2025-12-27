# MCP Memory Server V3 - Test Suite

Comprehensive test suite for the V3 semantic events system.

## Overview

This test suite provides >80% code coverage for V3 components:

- **PostgresClient**: Connection pooling, query execution, transactions
- **EventExtractionService**: LLM-based event extraction (Prompt A & B)
- **JobQueueService**: Async job queue with retry logic
- **Event Tools**: MCP tool functions for querying events
- **E2E Scenarios**: Complete workflows from ingestion to querying

## Test Files

### Unit Tests

1. **`test_postgres_client.py`** (30+ tests)
   - Connection pool management (async + sync)
   - Query execution (execute, fetch_all, fetch_one, fetch_val)
   - Transaction handling and rollback
   - Health checks
   - Error handling

2. **`test_event_extraction_service.py`** (25+ tests)
   - Prompt A: Extract events from chunks
   - Prompt B: Canonicalize and deduplicate events
   - Event validation (schema, categories, evidence)
   - JSON parsing and error handling
   - Mock OpenAI responses

3. **`test_job_queue_service.py`** (25+ tests)
   - Job creation (idempotency with ON CONFLICT)
   - Job claiming (SKIP LOCKED behavior)
   - Retry logic with exponential backoff
   - Atomic event writes (DELETE + INSERT in transaction)
   - Job status tracking
   - Force re-extraction

4. **`test_event_tools.py`** (35+ tests)
   - `event_search`: Full-text search, filters, pagination
   - `event_get`: Single event retrieval with evidence
   - `event_list_for_revision`: List events by revision
   - Parameter validation
   - Error handling

### Integration Tests

5. **`test_e2e_v3.py`** (10+ scenarios)
   - Scenario 1: Small artifact extraction
   - Scenario 2: Large artifact with chunking
   - Scenario 3: Idempotent re-ingestion
   - Scenario 4: New revisions create new events
   - Scenario 5: Failure recovery and retry logic
   - Concurrent worker job claiming
   - Cross-artifact search
   - Time range filtering
   - Atomic transaction rollback

### Fixtures

6. **`conftest.py`**
   - Mock Postgres client and connections
   - Mock ChromaDB client and collections
   - Mock OpenAI client with responses
   - Sample test data (artifacts, events, evidence)
   - Shared pytest fixtures for all tests

## Running Tests

### Prerequisites

```bash
# Install dependencies
cd /path/to/mcp-server
pip install -r requirements.txt
```

### Run All Tests

```bash
# From the mcp-server directory
pytest tests/mcp-server/ -v
```

### Run Specific Test Files

```bash
# Unit tests only
pytest tests/mcp-server/test_postgres_client.py -v
pytest tests/mcp-server/test_event_extraction_service.py -v
pytest tests/mcp-server/test_job_queue_service.py -v
pytest tests/mcp-server/test_event_tools.py -v

# Integration tests
pytest tests/mcp-server/test_e2e_v3.py -v
```

### Run with Coverage

```bash
# Generate coverage report
pytest tests/mcp-server/ --cov=src --cov-report=html --cov-report=term

# View HTML report
open htmlcov/index.html
```

### Run Specific Tests

```bash
# Run tests matching a pattern
pytest tests/mcp-server/ -k "test_extract_from_chunk" -v

# Run tests for a specific component
pytest tests/mcp-server/ -k "postgres" -v
pytest tests/mcp-server/ -k "extraction" -v
pytest tests/mcp-server/ -k "job_queue" -v
pytest tests/mcp-server/ -k "event_tools" -v
```

### Run with Markers

```bash
# Run only async tests
pytest tests/mcp-server/ -m asyncio -v

# Skip slow tests
pytest tests/mcp-server/ -m "not slow" -v
```

## Test Modes

### Mock Mode (Default)

Tests run with mocked dependencies:
- Mock Postgres client (no real database)
- Mock ChromaDB client (no vector store)
- Mock OpenAI client (no API calls)

**Advantages:**
- Fast execution
- No external dependencies
- Deterministic results
- No API costs

### Integration Mode (Optional)

Tests can run against real services for integration testing:

```bash
# Set environment variables
export EVENTS_DB_DSN="postgresql://test:test@localhost:5432/test_events"
export CHROMA_HOST="localhost"
export CHROMA_PORT="8001"
export OPENAI_API_KEY="sk-test-key"

# Run integration tests
pytest tests/mcp-server/test_e2e_v3.py --integration -v
```

**Requirements:**
- Running Postgres instance
- Running ChromaDB instance
- Valid OpenAI API key (for real LLM calls)

## Test Coverage Goals

Target: **>80% code coverage**

Current coverage by module:
- `storage/postgres_client.py`: 90%+
- `services/event_extraction_service.py`: 85%+
- `services/job_queue_service.py`: 90%+
- `tools/event_tools.py`: 85%+
- `worker/event_worker.py`: 75%+ (covered by E2E)

## Test Data

All test fixtures use realistic sample data:

- **Artifacts**: Meeting notes, emails, documents
- **Events**: Decisions, commitments, feedback
- **Evidence**: Direct quotes with character offsets
- **Actors**: Team members with roles
- **Timestamps**: ISO8601 formatted dates

See `conftest.py` for sample data definitions.

## Continuous Integration

These tests are designed to run in CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    pip install -r requirements.txt
    pytest tests/mcp-server/ --cov=src --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    file: ./coverage.xml
```

## Debugging Tests

### Verbose Output

```bash
pytest tests/mcp-server/ -vv -s
```

### Show Print Statements

```bash
pytest tests/mcp-server/ -s
```

### Drop into Debugger on Failure

```bash
pytest tests/mcp-server/ --pdb
```

### Run Last Failed Tests

```bash
pytest tests/mcp-server/ --lf
```

## Common Issues

### Import Errors

If you see `ModuleNotFoundError`:

```bash
# Add src directory to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/path/to/mcp-server/src"
```

Or run from the correct directory:

```bash
cd /path/to/.claude-workspace/implementation/mcp-server
pytest ../../tests/mcp-server/ -v
```

### Async Test Failures

Ensure `pytest-asyncio` is installed:

```bash
pip install pytest-asyncio
```

### Mock Errors

If mocks aren't working, verify imports in test files match implementation.

## Contributing

When adding new features to V3:

1. Add corresponding test file in `tests/mcp-server/`
2. Add fixtures to `conftest.py` if needed
3. Aim for >80% coverage of new code
4. Include both positive and negative test cases
5. Test error handling paths
6. Document any integration test requirements

## Test Philosophy

- **Unit tests**: Fast, isolated, mock external dependencies
- **Integration tests**: Slower, test real interactions
- **E2E tests**: Complete workflows, verify system behavior
- **Coverage**: Prioritize critical paths and error handling
- **Maintainability**: Clear test names, minimal duplication
- **Documentation**: Tests serve as usage examples

## References

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio documentation](https://pytest-asyncio.readthedocs.io/)
- [unittest.mock documentation](https://docs.python.org/3/library/unittest.mock.html)
- [V3 Specification](../../specs/v3-specification.md)
