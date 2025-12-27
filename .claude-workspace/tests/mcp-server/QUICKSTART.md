# Quick Start Guide - V3 Test Suite

## Install Dependencies

```bash
cd /Users/roland/Library/Mobile\ Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server

pip install -r requirements.txt
```

## Run All Tests

```bash
# From the mcp-server directory
pytest ../../tests/mcp-server/ -v
```

## Run with Coverage

```bash
pytest ../../tests/mcp-server/ --cov=src --cov-report=html --cov-report=term

# View HTML report
open htmlcov/index.html
```

## Run Specific Test Files

```bash
# Postgres client tests
pytest ../../tests/mcp-server/test_postgres_client.py -v

# Event extraction tests
pytest ../../tests/mcp-server/test_event_extraction_service.py -v

# Job queue tests
pytest ../../tests/mcp-server/test_job_queue_service.py -v

# Event tools tests
pytest ../../tests/mcp-server/test_event_tools.py -v

# E2E integration tests
pytest ../../tests/mcp-server/test_e2e_v3.py -v
```

## Run Specific Tests

```bash
# Run tests matching a pattern
pytest ../../tests/mcp-server/ -k "test_extract_from_chunk" -v

# Run all async tests
pytest ../../tests/mcp-server/ -m asyncio -v
```

## Expected Output

```
======================== test session starts =========================
platform darwin -- Python 3.11.x, pytest-8.x, pluggy-1.x
rootdir: .../tests/mcp-server
configfile: pytest.ini
plugins: asyncio-0.23.x, cov-4.1.x, mock-3.12.x
collected 120 items

test_postgres_client.py::test_connect_creates_pool PASSED      [  1%]
test_postgres_client.py::test_execute_runs_query PASSED        [  2%]
test_postgres_client.py::test_fetch_all_returns_rows PASSED    [  3%]
...
test_e2e_v3.py::test_scenario_5_failure_recovery PASSED        [100%]

=================== 120 passed in 15.23s ========================
```

## Troubleshooting

### Import Errors

If you see `ModuleNotFoundError: No module named 'storage'`:

```bash
# Set PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"

# Or run from correct directory
cd /Users/roland/Library/Mobile\ Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server
pytest ../../tests/mcp-server/ -v
```

### Async Test Errors

Ensure pytest-asyncio is installed:

```bash
pip install pytest-asyncio
```

### Coverage Not Working

Install coverage packages:

```bash
pip install pytest-cov coverage
```

## What Gets Tested

- **PostgresClient:** Connection pooling, queries, transactions
- **EventExtractionService:** LLM extraction, validation
- **JobQueueService:** Job queue, retry logic, atomic writes
- **Event Tools:** MCP tool functions (search, get, list)
- **E2E Scenarios:** Complete workflows from ingestion to querying

## Test Modes

### Mock Mode (Default)
Tests run with mocked dependencies - fast and deterministic.

### Integration Mode (Optional)
Set environment variables for real service testing:

```bash
export EVENTS_DB_DSN="postgresql://test:test@localhost:5432/test_events"
export CHROMA_HOST="localhost"
export CHROMA_PORT="8001"
export OPENAI_API_KEY="sk-test-key"

pytest ../../tests/mcp-server/ --integration -v
```

## Next Steps

1. Run tests: `pytest ../../tests/mcp-server/ -v`
2. Check coverage: `pytest ../../tests/mcp-server/ --cov=src --cov-report=html`
3. Review results: `open htmlcov/index.html`
4. See TEST_SUMMARY.md for detailed information
