# ADR-005: Testing Infrastructure

## Status
Accepted

## Date
2025-12-30

## Context

MCP Memory Server V4 requires a comprehensive testing strategy that:
1. Validates API endpoints and MCP protocol compliance
2. Tests browser-based interactions via MCP Inspector
3. Assesses quality of AI-driven features (event extraction, entity resolution)
4. Runs in CI/CD without manual intervention
5. Supports multiple isolated environments running concurrently

### Problem
- Tests failed when production services were running (port conflicts)
- Schema misalignment between test and production databases
- Flaky tests due to insufficient health check timing
- No CI/CD pipeline for automated validation

## Decision

### 1. Multi-Environment Isolation via Port Offset

Each environment uses a distinct port range with +100 offset pattern:

| Environment | MCP Server | ChromaDB | PostgreSQL | Project Name |
|-------------|------------|----------|------------|--------------|
| **prod** | 3001 | 8001 | 5432 | mcp-memory-prod |
| **staging** | 3101 | 8101 | 5532 | mcp-memory-staging |
| **test** | 3201 | 8201 | 5632 | mcp-memory-test |

**Rationale:** Port isolation enables concurrent execution of all environments. The offset pattern makes it easy to identify environment from port number.

### 2. Test Framework: Pytest + Playwright

**Pytest** for API and integration tests:
- Mature ecosystem with excellent async support
- Native fixtures for setup/teardown
- JUnit XML output for CI integration

**Playwright** for browser tests:
- MCP Inspector UI validation
- Cross-browser support (Chromium for CI)
- Built-in tracing and screenshot capture on failure

**Rationale:** Industry-standard tools with strong CI/CD integration and debugging capabilities.

### 3. Three-Tier Test Pipeline

```
┌─────────────────────────────────────────────────────────┐
│                    Quality Tests                        │
│        (AI assessment, main branch only, 20min)         │
├─────────────────────────────────────────────────────────┤
│                    Browser Tests                        │
│           (Playwright UI flows, 10min)                  │
├─────────────────────────────────────────────────────────┤
│                     API Tests                           │
│        (Pytest endpoint validation, 15min)              │
└─────────────────────────────────────────────────────────┘
```

**Execution:**
- API tests run on every push/PR
- Browser tests run after API tests pass
- Quality tests run only on main branch pushes

**Rationale:** Tiered execution provides fast feedback for common changes while ensuring comprehensive coverage for releases.

### 4. Health Check Protocol

All environments use standardized health verification:

| Service | Endpoint | Success Criteria |
|---------|----------|------------------|
| MCP Server | `GET /health` | HTTP 200 |
| ChromaDB | `GET /api/v2/heartbeat` | HTTP 200 |
| PostgreSQL | `pg_isready` | Exit 0 |

**Polling:** 3-second intervals, 120-second timeout

**Rationale:** Consistent health checks prevent flaky tests due to service startup timing.

### 5. Environment Management Scripts

| Script | Purpose |
|--------|---------|
| `env-up.sh <env>` | Start environment, wait for healthy |
| `env-down.sh <env> [--volumes]` | Stop environment, optionally remove data |
| `env-reset.sh <env>` | Full reset (refuses prod for safety) |
| `health-check.sh <env>` | Comprehensive health verification |

**Rationale:** Scriptable environment management enables reproducible test runs and CI automation.

### 6. GitHub Actions CI Pipeline

```yaml
jobs:
  api-tests:      # Service containers (ChromaDB, Postgres)
    timeout: 15min

  browser-tests:  # Docker Compose full stack
    needs: api-tests
    timeout: 10min

  quality-tests:  # AI assessment (main only)
    needs: [api-tests, browser-tests]
    if: github.ref == 'refs/heads/main'
    timeout: 20min
```

**Rationale:** GitHub Actions provides free CI for open source, with excellent Docker and service container support.

## Consequences

### Positive
- All environments can run concurrently without conflicts
- Fast feedback (< 5 min for smoke tests)
- Comprehensive coverage for releases
- Reproducible test runs via scripts
- CI/CD automation reduces manual validation

### Negative
- Multiple Docker Compose files to maintain (test, staging, prod)
- Port allocation requires documentation
- Quality tests add CI time on main branch (~20 min)

### Risks Mitigated
- **Port conflicts:** Strict port allocation per environment
- **Flaky tests:** Health checks ensure services ready before tests
- **Schema drift:** Test environment uses same migrations as prod
- **Slow feedback:** Tiered execution prioritizes fast tests

## Implementation

### Files Created

**Scripts** (`.claude-workspace/deployment/scripts/`):
- `env-up.sh` - Start environment with health wait
- `env-down.sh` - Stop environment
- `env-reset.sh` - Full reset (blocks prod)
- `health-check.sh` - Comprehensive health check (with --wait, --json options)
- `verify-real-integration.sh` - Pre-UAT validation

**Configuration**:
- `docker-compose.test.yml` - Test environment (port offset +200)
- `.github/workflows/test.yml` - CI pipeline

### Usage

```bash
# Start test environment
./scripts/env-up.sh test

# Run tests
cd .claude-workspace/tests/e2e-playwright
pytest api/ -v

# Check health
./scripts/health-check-env.sh test

# Reset (clears data)
./scripts/env-reset.sh test

# Stop
./scripts/env-down.sh test
```

## References

- [Pytest Documentation](https://docs.pytest.org/)
- [Playwright Python](https://playwright.dev/python/)
- [GitHub Actions](https://docs.github.com/en/actions)
- [Docker Compose](https://docs.docker.com/compose/)
