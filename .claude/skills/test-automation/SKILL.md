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

```bash
# Run all tests
npm test

# Run with coverage
npm test -- --coverage

# Run specific test file
npm test -- path/to/test.spec.js

# Run in watch mode
npm test -- --watch

# Generate coverage report
npm test -- --coverage --coverageReporters=html
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
