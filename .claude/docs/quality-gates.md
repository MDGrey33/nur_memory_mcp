# Quality Gates

Quality gates ensure every delivery meets high standards before reaching the user.

## Gate 1: Specification Review

**After**: Planning phase
**Reviewer**: Senior Architect

**Checks**:
- [ ] Requirements are clear and complete
- [ ] Acceptance criteria are testable
- [ ] Edge cases identified
- [ ] Scope is reasonable
- [ ] No ambiguities

**Pass Criteria**: All checks satisfied

## Gate 2: Architecture Review

**After**: Architecture phase
**Reviewer**: Security Engineer, Performance Engineer

**Checks**:
- [ ] Design is scalable
- [ ] Security considered
- [ ] Performance targets defined
- [ ] Follows project patterns
- [ ] ADRs document decisions

**Pass Criteria**: No critical issues

## Gate 3: Code Review

**After**: Implementation phase
**Reviewer**: Code Reviewer

**Checks**:
- [ ] Code is readable and maintainable
- [ ] No security vulnerabilities
- [ ] Error handling complete
- [ ] No hardcoded secrets
- [ ] Follows coding standards

**Pass Criteria**: No critical or high issues

## Gate 4: Test Coverage

**After**: Testing phase
**Reviewer**: QA Lead

**Checks**:
- [ ] Unit test coverage > 80%
- [ ] All critical paths tested
- [ ] Edge cases covered
- [ ] No flaky tests
- [ ] Tests are maintainable

**Pass Criteria**: Coverage threshold met, all tests pass

## Gate 5: Security Audit

**After**: Security phase
**Reviewer**: Security Engineer

**Checks**:
- [ ] OWASP Top 10 reviewed
- [ ] No SQL injection
- [ ] No XSS vulnerabilities
- [ ] Authentication secure
- [ ] Authorization checked
- [ ] Input validated

**Pass Criteria**: No critical vulnerabilities

## Gate 6: Deployment Readiness

**After**: Deployment prep phase
**Reviewer**: DevOps Engineer

**Checks**:
- [ ] Deployment config complete
- [ ] Environment vars documented
- [ ] Health checks defined
- [ ] Rollback procedure written
- [ ] Monitoring planned

**Pass Criteria**: Production-ready

## Gate 7: Real-World Integration Test (MANDATORY)

**After**: Deployment prep phase
**Reviewer**: QA Lead + Chief of Staff
**Type**: BLOCKING - Cannot proceed without pass

**WHY THIS EXISTS**: Mocked unit tests pass but real services fail. This gate catches configuration mismatches, port errors, and integration issues that only appear with real services.

**Pre-Requisites**:
- All services must be running (not mocked)
- Real API keys configured
- Actual database connections

**Checks**:
- [ ] Health endpoints return 200 from REAL services
- [ ] Port configuration matches running infrastructure
- [ ] All expected tools are exposed (count verified)
- [ ] At least ONE tool from each category executed successfully with real services
- [ ] Client config (Cursor/Claude Desktop) has correct URLs
- [ ] Server logs show no errors on startup
- [ ] Real API call succeeds (e.g., embedding generation)

**Verification Commands** (must all succeed):
```bash
# 1. Health check
curl http://localhost:3001/health | grep '"status":"ok"'

# 2. Port consistency
grep CHROMA_PORT .env  # Must match docker-compose

# 3. Tool count (v2 = 12 tools)
curl -X POST http://localhost:3001/mcp/ \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# 4. Real tool execution
# Execute memory_store, artifact_ingest, hybrid_search with REAL services
```

**Pass Criteria**: ALL checks pass with REAL services (no mocks)

**Failure Action**: Do NOT proceed to Executive Review. Fix issues first.

---

## Gate 8: Executive Review

**After**: Real-World Integration Test passes
**Reviewer**: Chief of Staff

**Checks**:
- [ ] All previous gates passed (including Gate 7)
- [ ] Quality meets user standards
- [ ] Learned patterns applied
- [ ] No known issues
- [ ] Documentation complete
- [ ] **Gate 7 verification log reviewed**

**Pass Criteria**: Confidence > 80% AND Gate 7 passed

## Gate Failure Handling

### Critical Failure
- Block progression
- Fix immediately
- Re-run gate

### High Priority
- Should fix before UAT
- Document if deferred

### Medium Priority
- Track for future
- Document in delivery

### Low Priority
- Note for consideration
- Don't block delivery

## Confidence Calculation

Chief of Staff confidence is based on:

| Factor | Weight |
|--------|--------|
| Test coverage | 20% |
| Security audit pass | 20% |
| Code review clean | 15% |
| All gates passed | 15% |
| Matches learned patterns | 15% |
| Documentation complete | 10% |
| No open issues | 5% |

**Thresholds**:
- > 90%: High confidence, present to user
- 70-90%: Moderate, may need iteration
- < 70%: Low, iterate internally

## Automated Checks

Run automatically via hooks:

```bash
# Pre-commit
npm run lint
npm run test

# Pre-deployment
npm run build
npm run test:e2e
```

## Manual Review Triggers

Require human review when:
- Security-sensitive changes
- Database schema changes
- API breaking changes
- New external dependencies
- Performance-critical code
