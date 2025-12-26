# Agent-App Test Suite

Comprehensive test suite for the Chroma MCP Memory V1 agent-app.

## Overview

This test suite provides thorough coverage of all agent-app components:

- **Unit Tests**: Fast, isolated tests with mocked dependencies
- **Integration Tests**: End-to-end tests requiring Docker
- **Coverage Target**: >80% code coverage

## Test Structure

```
tests/agent-app/
├── conftest.py              # Pytest fixtures and configuration
├── pytest.ini               # Pytest settings
├── requirements-test.txt    # Test dependencies
├── README.md               # This file
├── test_config.py          # Config loading and validation tests
├── test_models.py          # Data model tests
├── test_memory_policy.py   # Policy logic tests
├── test_context_builder.py # Context assembly tests (mocked gateway)
├── test_memory_gateway.py  # Gateway tests (mocked HTTP)
└── test_integration.py     # End-to-end integration tests
```

## Quick Start

### 1. Install Test Dependencies

```bash
cd .claude-workspace/tests/agent-app
pip install -r requirements-test.txt
```

### 2. Run All Unit Tests

```bash
pytest -v
```

### 3. Run with Coverage Report

```bash
pytest --cov --cov-report=html --cov-report=term
```

This generates an HTML coverage report in `htmlcov/index.html`.

### 4. Run Specific Test Files

```bash
# Config tests only
pytest test_config.py -v

# Models tests only
pytest test_models.py -v

# Policy tests only
pytest test_memory_policy.py -v
```

### 5. Run Integration Tests (Requires Docker)

```bash
# Start Docker services first
cd ../../..
docker-compose up -d

# Run integration tests
cd .claude-workspace/tests/agent-app
pytest -m integration -v
```

## Test Categories

### Unit Tests (No External Dependencies)

Run these for fast feedback during development:

```bash
pytest -m "not integration" -v
```

**Covered modules:**
- `test_config.py` - Configuration loading and validation
- `test_models.py` - Data models (HistoryTurn, MemoryItem, ContextPackage)
- `test_memory_policy.py` - Policy decisions and rate limiting
- `test_context_builder.py` - Context assembly (mocked gateway)
- `test_memory_gateway.py` - Gateway transport layer (mocked HTTP)

### Integration Tests (Requires Docker)

Run these to validate end-to-end behavior:

```bash
pytest -m integration -v
```

**Covered scenarios:**
- Store and retrieve conversation history
- Store and recall semantic memories
- Complete context building with real data
- Memory policy enforcement with real storage
- Data persistence across operations
- Error handling in real scenarios
- Concurrent operations

## Coverage Report

Generate and view coverage:

```bash
# Generate coverage report
pytest --cov --cov-report=html

# Open in browser (macOS)
open htmlcov/index.html

# Open in browser (Linux)
xdg-open htmlcov/index.html
```

Target: **>80% code coverage**

Current coverage by module:
- `config.py`: ~95%
- `models.py`: ~95%
- `memory_policy.py`: ~95%
- `context_builder.py`: ~90%
- `memory_gateway.py`: ~90%

## Test Fixtures

Shared fixtures are defined in `conftest.py`:

- `sample_timestamp` - Fixed ISO-8601 timestamp
- `sample_conversation_id` - Test conversation ID
- `sample_history_turn` - Sample history data
- `sample_history_result` - Sample gateway history result
- `sample_memory_item` - Sample memory data
- `sample_memory_result` - Sample gateway memory result
- `mock_gateway` - Mocked gateway for unit tests

## Running Specific Test Classes

```bash
# Run all tests in a specific class
pytest test_config.py::TestAppConfigDefaults -v

# Run a single test method
pytest test_config.py::TestAppConfigDefaults::test_default_values -v
```

## Debugging Failed Tests

### Show full error output
```bash
pytest -vv --tb=long
```

### Stop on first failure
```bash
pytest -x
```

### Show print statements
```bash
pytest -s
```

### Run last failed tests only
```bash
pytest --lf
```

## Continuous Integration

For CI/CD pipelines:

```bash
# Fast unit tests only (no Docker required)
pytest -m "not integration" --cov --cov-report=xml --cov-fail-under=80

# Full test suite (requires Docker)
docker-compose up -d
pytest --cov --cov-report=xml --cov-fail-under=80
docker-compose down
```

## Test Writing Guidelines

### Unit Test Example

```python
import pytest
from config import AppConfig

class TestAppConfig:
    def test_default_values(self):
        """Test that defaults are correctly loaded."""
        config = AppConfig.from_env()
        assert config.memory_confidence_min == 0.7
```

### Async Test Example

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    """Test async function."""
    result = await some_async_function()
    assert result is not None
```

### Mocked HTTP Test Example

```python
import respx
import httpx

@pytest.mark.asyncio
@respx.mock
async def test_with_mocked_http():
    """Test with mocked HTTP calls."""
    respx.get("http://example.com/api").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    # Your test code here
```

## Troubleshooting

### Issue: Import errors

**Solution**: Ensure src directory is in Python path. Tests automatically add it via:
```python
sys.path.insert(0, '/Users/roland/Library/Mobile Documents/...')
```

### Issue: Integration tests fail

**Solution**:
1. Verify Docker is running: `docker ps`
2. Start services: `docker-compose up -d`
3. Check service health: `docker-compose ps`
4. View logs: `docker-compose logs`

### Issue: Async tests not running

**Solution**: Ensure `pytest-asyncio` is installed:
```bash
pip install pytest-asyncio
```

### Issue: Coverage not reaching 80%

**Solution**:
1. View detailed coverage: `pytest --cov --cov-report=term-missing`
2. Identify uncovered lines
3. Add tests for missing coverage
4. Re-run coverage report

## Best Practices

1. **Test Isolation**: Each test should be independent
2. **Clear Names**: Test names should describe what they test
3. **Mock External Dependencies**: Unit tests should not hit real services
4. **Fast Feedback**: Unit tests should run in milliseconds
5. **Comprehensive Coverage**: Test edge cases and error conditions
6. **Documentation**: Add docstrings to complex tests

## Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/)
- [respx Documentation](https://lundberg.github.io/respx/)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)

## Support

For questions or issues with tests:
1. Check test output for error details
2. Review test docstrings for expected behavior
3. Verify fixtures in `conftest.py`
4. Check module implementation for changes
