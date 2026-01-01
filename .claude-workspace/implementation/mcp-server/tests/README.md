# MCP Memory Server V6.2 - Test Suite

Comprehensive test suite targeting >80% code coverage for the MCP Memory Server V6.2.

## V6 Tools (4 total)

| Tool | Description |
|------|-------------|
| `remember` | Store content with automatic chunking and event extraction |
| `recall` | Search/retrieve with semantic search and graph expansion |
| `forget` | Delete with cascade (chunks, events, entities) |
| `status` | Health check and job status |

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── unit/                    # Unit tests (isolated component testing)
│   ├── services/           # Service layer tests
│   │   ├── test_embedding_service.py
│   │   ├── test_chunking_service.py
│   │   ├── test_retrieval_service.py
│   │   └── test_privacy_service.py
│   ├── storage/            # Storage layer tests
│   │   ├── test_chroma_client.py
│   │   ├── test_collections.py
│   │   └── test_models.py
│   ├── test_config.py      # Configuration tests
│   └── test_errors.py      # Error class tests
└── integration/            # Integration tests (multi-component)
    ├── test_artifact_ingestion.py
    ├── test_search_and_retrieval.py
    └── test_artifact_operations.py
```

## Running Tests

### Run All Tests

```bash
pytest
```

### Run with Coverage Report

```bash
pytest --cov=src --cov-report=term-missing --cov-report=html
```

### Run Specific Test Categories

```bash
# Unit tests only
pytest tests/unit -v

# Integration tests only
pytest tests/integration -v

# Tests for specific module
pytest tests/unit/services/test_embedding_service.py -v
```

### Run Tests by Marker

```bash
# Run only OpenAI mock tests
pytest -m mock_openai

# Run only ChromaDB mock tests
pytest -m mock_chroma

# Run unit tests
pytest -m unit

# Run integration tests
pytest -m integration
```

### Run with Verbose Output

```bash
pytest -v
```

### Run Failing Tests First

```bash
pytest --failed-first
```

## Coverage Goals

The test suite targets **>80% code coverage** across all modules:

### Unit Test Coverage

**EmbeddingService:**
- Initialization and configuration
- Single embedding generation
- Batch embedding generation
- Retry logic (rate limits, timeouts, auth errors)
- Health checks

**ChunkingService:**
- Token counting
- Chunking decision logic
- Chunk generation with overlap
- Character offset calculation
- Deterministic chunk IDs
- Neighbor expansion

**RetrievalService:**
- RRF score merging
- Deduplication (chunks vs artifacts)
- Collection searching
- Hybrid search
- Neighbor expansion

**Storage Layer:**
- ChromaDB client management
- Collection operations
- Chunk retrieval
- Artifact lookup
- Cascade deletion

**Configuration:**
- Environment variable loading
- Default values
- Validation rules

### Integration Test Coverage

**Artifact Ingestion:**
- Small artifacts (unchunked)
- Large artifacts (chunked)
- Idempotency checks
- Content change detection
- Two-phase atomic writes
- Error handling

**Search & Retrieval:**
- Unchunked artifact search
- Chunk search
- Neighbor expansion
- Hybrid search (with/without memory)
- Metadata filtering

**Artifact Operations:**
- Get unchunked artifact
- Get chunked artifact (reconstructed)
- Get with chunk list
- Delete unchunked
- Delete with cascade

## Test Isolation

All tests are fully isolated:

- **OpenAI API calls are mocked** - Tests run offline without real API calls
- **ChromaDB operations are mocked** - No real database required for most tests
- **Environment variables are set via fixtures** - Clean state per test

## Writing New Tests

### Test Naming Convention

- Test files: `test_<module_name>.py`
- Test functions: `test_<what_is_being_tested>`
- Use descriptive names: `test_retry_on_rate_limit` instead of `test_retry_1`

### Using Fixtures

Shared fixtures are defined in `conftest.py`:

```python
def test_my_feature(embedding_service, mock_chroma_client):
    # embedding_service and mock_chroma_client are auto-injected
    result = embedding_service.generate_embedding("test")
    assert len(result) == 3072
```

### Mocking External Services

```python
from unittest.mock import patch

@patch("server.embedding_service")
def test_with_mock(mock_embed):
    mock_embed.generate_embedding.return_value = [0.1] * 3072
    # Your test code
```

### Adding Test Markers

```python
@pytest.mark.integration
@pytest.mark.slow
def test_large_operation():
    # Test code
```

## Continuous Integration

These tests are designed to run in CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    pip install -r requirements.txt
    pytest --cov=src --cov-report=xml --cov-report=term
```

## Coverage Report

After running tests with coverage, view the HTML report:

```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## Troubleshooting

### Import Errors

If you see import errors, ensure you're running pytest from the project root:

```bash
cd /path/to/mcp-server
pytest
```

### Missing Dependencies

```bash
pip install -r requirements.txt
```

### Environment Variables

Tests automatically set required environment variables via `conftest.py`. If you need to override:

```bash
OPENAI_API_KEY=your-key pytest
```

## Test Performance

- Unit tests: ~2-5 seconds (all mocked)
- Integration tests: ~5-10 seconds (mocked external services)
- Full suite: ~10-15 seconds

## Quality Standards

All tests must:

1. **Be deterministic** - Same input = same output
2. **Be isolated** - No shared state between tests
3. **Be fast** - Mock external services
4. **Be readable** - Clear assertions and error messages
5. **Be maintainable** - Use fixtures, avoid duplication

## Contributing

When adding new features:

1. Write tests first (TDD)
2. Ensure tests pass: `pytest`
3. Check coverage: `pytest --cov=src`
4. Add integration tests if feature spans multiple components
5. Update this README if adding new test categories
