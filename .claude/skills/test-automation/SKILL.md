---
name: test-automation
description: Create and execute automated test suites with comprehensive coverage for unit, integration, and E2E testing
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Test Automation Skill

Create comprehensive automated tests ensuring code quality and reliability.

## When to Use

- Writing unit tests for new code
- Creating integration tests
- Setting up E2E test suites
- Measuring code coverage
- Validating bug fixes

## Test Types

### Unit Tests
- Test individual functions/methods
- Mock external dependencies
- Fast execution (<1ms per test)
- High coverage (>80%)

### Integration Tests
- Test component interactions
- Use real dependencies (database, APIs)
- Validate data flow
- Test error scenarios

### E2E Tests
- Test complete user flows
- Browser automation
- API workflow testing
- Performance validation

## Pre-flight Version Check

Before running integration, E2E, or live benchmark tests, verify the deployed server matches local code:

```bash
cd .claude-workspace/deployment
./scripts/version-check.sh test    # For test environment
./scripts/version-check.sh staging # For staging environment
```

**What it does**:
1. Reads `__version__` from `src/server.py`
2. Fetches version from `/health` endpoint on target environment
3. If versions mismatch:
   - Rebuilds mcp-server and event-worker containers (`--no-cache`)
   - Restarts the services
   - Waits for healthy (up to 120s)

**When to use**:

| Test Type | Version Check Required |
|-----------|----------------------|
| Unit tests | No (uses mocks) |
| Integration tests | Yes |
| E2E tests | Yes |
| Benchmarks (live) | Yes |
| Benchmarks (replay) | No (uses fixtures) |

**Skip version check**: Set `SKIP_VERSION_CHECK=1` or use `--skip` flag.

## Test Structure (AAA Pattern)

```javascript
describe('Feature', () => {
  it('should do expected behavior', () => {
    // Arrange - Set up test data
    const input = { ... };

    // Act - Execute the code
    const result = functionUnderTest(input);

    // Assert - Verify outcome
    expect(result).toEqual(expected);
  });
});
```

## Coverage Requirements

| Type | Minimum | Target |
|------|---------|--------|
| Statements | 70% | 85% |
| Branches | 65% | 80% |
| Functions | 75% | 90% |
| Lines | 70% | 85% |

## Test Commands

### Unit Tests (Python/pytest)

```bash
cd .claude-workspace/implementation/mcp-server

# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/services/test_retrieval_service.py -v

# Run with coverage
pytest tests/unit/ --cov=src --cov-report=html
```

### Quality Benchmarks

```bash
# For live mode, first check version
cd .claude-workspace/deployment
./scripts/version-check.sh test

# Then run benchmarks
cd ../benchmarks

# Full benchmark suite (live mode - requires running services)
MCP_URL=http://localhost:3201 python tests/benchmark_runner.py --mode=live

# Replay mode (no API calls, uses fixtures) - no version check needed
python tests/benchmark_runner.py --mode=replay

# Quick outcome test (~$0.006/run)
python outcome_eval.py
```

### Benchmark Thresholds

| Component | Metric | Threshold |
|-----------|--------|-----------|
| Event Extraction | F1 | 0.70 |
| Entity Extraction | F1 | 0.70 |
| Retrieval | MRR | 0.60 |
| Retrieval | NDCG | 0.65 |
| Graph Expansion | F1 | 0.60 |

### E2E Tests

```bash
cd .claude-workspace/deployment

# Check version and rebuild if needed
./scripts/version-check.sh test

# Start services (if not already running)
./scripts/env-up.sh test

# Run E2E tests
python ../tests/e2e/full_user_simulation.py
```

## Best Practices

1. **Test behavior, not implementation** - Focus on what, not how
2. **One assertion per test** - Keep tests focused
3. **Descriptive test names** - "should return X when Y"
4. **Independent tests** - No shared state between tests
5. **Fast tests** - Slow tests don't get run
6. **Deterministic** - Same input = same output

## Edge Cases to Test

- Empty inputs
- Null/undefined values
- Boundary values (0, -1, MAX_INT)
- Invalid data types
- Large datasets
- Concurrent operations
- Network failures
- Timeout scenarios

## Test Report Format

```markdown
# Test Results

**Total**: X tests
**Passed**: Y
**Failed**: Z
**Coverage**: X%

## Failed Tests
1. [Test name] - [Reason]

## Coverage Gaps
- [File]: [Lines not covered]

## Recommendations
- [Suggested additional tests]
```
