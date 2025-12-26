---
name: code-review
description: Comprehensive code review checking for security, performance, maintainability, and best practices
allowed-tools: Read, Glob, Grep
---

# Code Review Skill

## Purpose

Perform thorough code reviews to ensure high-quality, secure, maintainable code before delivery. This skill is invoked automatically when code needs review.

## When to Use This Skill

- Reviewing pull requests or code changes
- Validating implementation against requirements
- Ensuring code follows project standards
- Identifying potential bugs or issues
- Checking for security vulnerabilities

## Review Process

### Step 1: Understand Context

Before reviewing code:
- Read the associated technical specification
- Understand what the code is supposed to do
- Review acceptance criteria
- Check related architecture decisions (ADRs)

### Step 2: Code Quality Review

#### Readability
- [ ] Code is well-formatted and consistent
- [ ] Variable and function names are descriptive
- [ ] Complex logic is commented
- [ ] No dead code or commented-out code
- [ ] Consistent indentation and style

#### Structure
- [ ] Functions are focused and do one thing
- [ ] Files are appropriately sized (<500 lines)
- [ ] Appropriate separation of concerns
- [ ] Clear module boundaries
- [ ] Proper use of abstraction

#### Error Handling
- [ ] All error cases handled
- [ ] Errors logged appropriately
- [ ] User-friendly error messages
- [ ] No silent failures
- [ ] Proper exception types used

### Step 3: Security Review

#### Input Validation
- [ ] All user inputs validated
- [ ] Validation happens server-side (not just client)
- [ ] SQL injection prevention (parameterized queries)
- [ ] XSS prevention (output encoding)
- [ ] CSRF protection where needed

#### Authentication & Authorization
- [ ] Authentication required for protected endpoints
- [ ] Authorization checks proper permissions
- [ ] No hardcoded credentials
- [ ] Secure password handling (hashing, not plaintext)
- [ ] Session management secure

#### Data Protection
- [ ] Sensitive data encrypted at rest
- [ ] Sensitive data encrypted in transit (HTTPS)
- [ ] No sensitive data in logs
- [ ] Proper data access controls
- [ ] No exposure of internal details in errors

#### Common Vulnerabilities
- [ ] No SQL injection vulnerabilities
- [ ] No XSS vulnerabilities
- [ ] No CSRF vulnerabilities
- [ ] No command injection
- [ ] No path traversal
- [ ] No insecure deserialization
- [ ] Rate limiting on public endpoints

### Step 4: Performance Review

#### Efficiency
- [ ] No N+1 query problems
- [ ] Appropriate database indexes used
- [ ] Caching used where appropriate
- [ ] No unnecessary computations in loops
- [ ] Efficient algorithms chosen

#### Scalability
- [ ] Can handle expected load
- [ ] No memory leaks
- [ ] Proper resource cleanup
- [ ] Asynchronous operations where appropriate
- [ ] Pagination for large datasets

#### Database Operations
- [ ] Queries optimized
- [ ] Proper use of transactions
- [ ] Connection pooling used
- [ ] No long-running transactions
- [ ] Appropriate batch operations

### Step 5: Testing Review

#### Test Coverage
- [ ] Unit tests exist for new code
- [ ] Critical paths have tests
- [ ] Edge cases tested
- [ ] Error cases tested
- [ ] >80% coverage on critical code

#### Test Quality
- [ ] Tests are clear and focused
- [ ] Tests are deterministic (not flaky)
- [ ] Tests are fast
- [ ] Test data is realistic
- [ ] Tests follow AAA pattern (Arrange, Act, Assert)

### Step 6: Maintainability Review

#### Documentation
- [ ] Public APIs documented
- [ ] Complex algorithms explained
- [ ] Assumptions documented
- [ ] TODOs tracked properly
- [ ] Breaking changes noted

#### Consistency
- [ ] Follows project coding standards
- [ ] Uses established patterns
- [ ] Naming conventions consistent
- [ ] No reinventing existing utilities
- [ ] Matches existing code style

#### Simplicity
- [ ] Solution is as simple as possible
- [ ] No premature optimization
- [ ] No unnecessary abstractions
- [ ] Clear and straightforward logic
- [ ] Easy to understand and modify

## Review Output Format

```markdown
# Code Review: [Feature/PR Name]

## Summary
[Brief overview of changes reviewed]

## Overall Assessment
✅ Approved | ⚠️ Approved with Comments | ❌ Changes Requested

## Critical Issues (Must Fix)
1. **[Issue Title]** - [file:line]
   - **Problem**: [Description]
   - **Impact**: [Why this is critical]
   - **Recommendation**: [How to fix]

2. [More critical issues...]

## High Priority Issues (Should Fix)
1. **[Issue Title]** - [file:line]
   - **Problem**: [Description]
   - **Recommendation**: [How to fix]

## Medium Priority Issues (Consider Fixing)
1. **[Issue Title]** - [file:line]
   - **Problem**: [Description]
   - **Recommendation**: [How to fix]

## Positive Aspects
- [Something done well]
- [Good practice observed]
- [Effective solution]

## Recommendations
- [General suggestion for improvement]
- [Pattern to consider]
- [Resource to check out]

## Security Assessment
✅ No security issues found | ⚠️ Minor concerns | ❌ Security issues present

[Details of any security concerns]

## Performance Assessment
✅ Performance acceptable | ⚠️ Minor concerns | ❌ Performance issues present

[Details of any performance concerns]

## Test Coverage Assessment
✅ Well tested (>80%) | ⚠️ Adequate testing (60-80%) | ❌ Insufficient testing (<60%)

[Details of test coverage]

---
**Reviewer**: [Agent name]
**Review Date**: [Date]
**Files Reviewed**: [Number] files, [Number] lines changed
```

## Common Issues to Look For

### Security Anti-Patterns

**Bad**:
```javascript
// SQL injection vulnerability
const query = `SELECT * FROM users WHERE id = ${userId}`;

// XSS vulnerability
element.innerHTML = userInput;

// Hardcoded credentials
const apiKey = "sk_live_12345";
```

**Good**:
```javascript
// Parameterized query
const query = 'SELECT * FROM users WHERE id = ?';
db.query(query, [userId]);

// Escaped output
element.textContent = userInput;

// Environment variable
const apiKey = process.env.API_KEY;
```

### Performance Anti-Patterns

**Bad**:
```javascript
// N+1 query problem
const users = await User.findAll();
for (const user of users) {
  const posts = await Post.findByUserId(user.id); // Query in loop!
}

// Unnecessary computation in loop
for (let i = 0; i < items.length; i++) {
  const total = calculateExpensiveTotal(); // Recalculated every iteration
}
```

**Good**:
```javascript
// Single query with join
const users = await User.findAll({
  include: [{ model: Post }]
});

// Compute once
const total = calculateExpensiveTotal();
for (let i = 0; i < items.length; i++) {
  // Use total
}
```

### Code Quality Anti-Patterns

**Bad**:
```javascript
// Function doing too much
function processOrder(order) {
  validateOrder(order);
  calculateTax(order);
  applyDiscount(order);
  processPayment(order);
  sendEmail(order);
  updateInventory(order);
  logTransaction(order);
  // ... 200 more lines
}

// Magic numbers
if (status === 3) {
  // What does 3 mean?
}
```

**Good**:
```javascript
// Single responsibility
function processOrder(order) {
  const validatedOrder = validateOrder(order);
  const pricedOrder = calculatePricing(validatedOrder);
  const paidOrder = processPayment(pricedOrder);
  await fulfillOrder(paidOrder);
  return paidOrder;
}

// Named constants
const STATUS_COMPLETED = 3;
if (status === STATUS_COMPLETED) {
  // Clear meaning
}
```

## Decision Criteria

### ✅ Approve
- No critical or high-priority issues
- Code meets quality standards
- Tests are comprehensive
- Security reviewed
- Performance acceptable

### ⚠️ Approve with Comments
- Minor issues noted
- Suggestions for improvement
- Non-blocking concerns
- Low-priority fixes

### ❌ Request Changes
- Critical bugs present
- Security vulnerabilities
- Performance issues
- Insufficient testing
- Doesn't meet requirements

## Tips for Effective Reviews

1. **Be specific**: Point to exact lines, provide examples
2. **Be constructive**: Explain why and how to improve
3. **Be balanced**: Note positive aspects, not just problems
4. **Be consistent**: Apply same standards to all code
5. **Be thorough**: Check every aspect systematically
6. **Be practical**: Focus on real issues, not nitpicks

## Remember

Good code review catches bugs before they reach production, maintains code quality, and helps the team learn and improve.

**Review as if you'll be maintaining this code** - because you might be!
