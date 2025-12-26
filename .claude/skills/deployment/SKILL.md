---
name: deployment
description: Prepare deployment configuration, environment setup, health checks, and rollback procedures
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Deployment Skill

Prepare production-ready deployment configurations.

## When to Use

- Creating deployment configurations
- Setting up CI/CD pipelines
- Configuring environment variables
- Writing health checks
- Planning rollback procedures

## Deployment Checklist

### Pre-Deployment
- [ ] All tests passing
- [ ] Security audit complete
- [ ] Environment variables documented
- [ ] Database migrations ready
- [ ] Rollback plan documented

### Deployment
- [ ] Database backup taken
- [ ] Deploy to staging first
- [ ] Smoke tests pass
- [ ] Deploy to production
- [ ] Health checks pass

### Post-Deployment
- [ ] Verify functionality
- [ ] Check error rates
- [ ] Monitor performance

## Environment Variables Template

```bash
# Application
NODE_ENV=production
PORT=3000

# Database
DATABASE_URL=postgres://...

# Auth
JWT_SECRET=<secret>

# External Services
REDIS_URL=redis://...
```

## Health Check Endpoint

```javascript
// GET /health
{
  "status": "healthy",
  "version": "1.0.0",
  "checks": {
    "database": "connected",
    "redis": "connected"
  }
}
```

## Rollback Procedure

1. Detect issue via monitoring
2. Execute rollback command
3. Verify health checks pass
4. Investigate root cause
5. Fix and redeploy
