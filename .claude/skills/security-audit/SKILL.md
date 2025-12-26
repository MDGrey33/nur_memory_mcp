---
name: security-audit
description: Perform comprehensive security audits checking for OWASP Top 10 vulnerabilities and security best practices
allowed-tools: Read, Glob, Grep, Bash
---

# Security Audit Skill

Identify and remediate security vulnerabilities before production deployment.

## When to Use

- Reviewing code for security issues
- Auditing APIs for vulnerabilities
- Checking authentication/authorization
- Validating input handling
- Pre-deployment security review

## OWASP Top 10 Checklist

### A01: Broken Access Control
- [ ] Authorization checks on all protected endpoints
- [ ] Principle of least privilege applied
- [ ] CORS properly configured
- [ ] Directory traversal prevented

### A02: Cryptographic Failures
- [ ] Sensitive data encrypted at rest
- [ ] HTTPS enforced (no HTTP)
- [ ] Strong encryption algorithms used
- [ ] No secrets in code/logs

### A03: Injection
- [ ] Parameterized queries (no SQL concatenation)
- [ ] Input validated and sanitized
- [ ] Output encoded for context
- [ ] Command injection prevented

### A04: Insecure Design
- [ ] Threat modeling performed
- [ ] Security requirements defined
- [ ] Secure defaults used
- [ ] Rate limiting implemented

### A05: Security Misconfiguration
- [ ] Security headers set (CSP, HSTS, etc.)
- [ ] Default credentials removed
- [ ] Error messages don't leak info
- [ ] Unnecessary features disabled

### A06: Vulnerable Components
- [ ] Dependencies up to date
- [ ] Known vulnerabilities checked
- [ ] Unused dependencies removed

### A07: Authentication Failures
- [ ] Strong password requirements
- [ ] Brute force protection
- [ ] Secure session management
- [ ] MFA available

### A08: Software/Data Integrity
- [ ] Dependencies verified (checksums)
- [ ] CI/CD pipeline secured
- [ ] Unsigned code rejected

### A09: Logging Failures
- [ ] Security events logged
- [ ] Logs don't contain sensitive data
- [ ] Monitoring and alerting configured

### A10: SSRF
- [ ] External requests validated
- [ ] Allowlists for external services
- [ ] Internal networks protected

## Common Vulnerability Patterns

**Bad - SQL Injection**:
```javascript
const query = `SELECT * FROM users WHERE id = ${userId}`;
```

**Good - Parameterized**:
```javascript
const query = 'SELECT * FROM users WHERE id = ?';
db.query(query, [userId]);
```

**Bad - XSS**:
```javascript
element.innerHTML = userInput;
```

**Good - Escaped**:
```javascript
element.textContent = userInput;
```

## Audit Report Format

```markdown
# Security Audit Report

**Date**: [Date]
**Scope**: [What was audited]

## Summary
[Overall assessment]

## Critical Issues
1. **[Issue]** - [Location]
   - Impact: [Severity]
   - Fix: [Remediation]

## High Priority Issues
[Same format]

## Recommendations
[General improvements]

## Compliance Status
- OWASP Top 10: [X/10 passed]
```
