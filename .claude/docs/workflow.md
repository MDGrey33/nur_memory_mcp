# Autonomous Development Workflow

This document details the 10-phase autonomous development cycle.

## Phase 0: Initialization

**Trigger**: User runs `/build [task description]`

**Actions**:
1. Parse user request
2. Create workspace structure
3. Initialize current-task.json
4. Validate request is actionable

**Output**: `.claude-workspace/` directory with task state

## Phase 1: Planning

**Agent**: Technical PM
**Input**: User request
**Output**: `specs/specification.md`

**The Technical PM**:
- Breaks down requirements into user stories
- Defines acceptance criteria
- Identifies edge cases
- Creates technical specification
- Estimates complexity

## Phase 2: Architecture

**Agent**: Senior Architect
**Input**: Specification
**Output**: `architecture/architecture.md`, `architecture/adr/`

**The Senior Architect**:
- Designs system architecture
- Creates data models
- Defines API contracts
- Documents decisions in ADRs
- Considers scalability and security

## Phase 3: Implementation

**Agents**: Lead Backend Engineer, Frontend Engineer
**Input**: Architecture
**Output**: `implementation/`

**Engineers**:
- Implement backend APIs and logic
- Build frontend components
- Follow architecture design
- Write clean, documented code
- Handle errors properly

## Phase 4: Testing

**Agent**: Test Automation Engineer, QA Lead
**Input**: Implementation
**Output**: `tests/`, test results

**QA Team**:
- Write unit tests (>80% coverage)
- Create integration tests
- Run E2E tests
- Validate edge cases
- Document test results

## Phase 5: Security

**Agent**: Security Engineer
**Input**: Implementation
**Output**: `security/security-audit.md`

**Security Engineer**:
- Audit for OWASP Top 10
- Check authentication/authorization
- Validate input handling
- Review data protection
- Document vulnerabilities and fixes

## Phase 6: Deployment Prep

**Agent**: DevOps Engineer
**Input**: Implementation
**Output**: `deployment/`

**DevOps Engineer**:
- Create deployment configuration
- Document environment variables
- Write health checks
- Plan rollback procedure
- Set up monitoring

## Phase 6.5: Real-World Integration Test (MANDATORY)

**Agent**: QA Lead
**Input**: Running services, deployment config
**Output**: `tests/integration/real_service_results.md`
**Type**: BLOCKING - Must pass before Phase 7

**WHY THIS EXISTS**: Unit tests with mocks pass but real deployments fail. This phase catches configuration mismatches, port errors, and integration issues.

**QA Lead MUST**:
1. Start all real services (not mocks)
2. Verify port configuration matches running infrastructure
3. Test health endpoints against REAL services
4. Execute at least ONE tool from each category with real services
5. Verify client configs (Cursor/Claude Desktop) have correct URLs
6. Check server logs for errors
7. Test with real API keys

**Mandatory Verification Script**:
```bash
# Must ALL pass before proceeding
./scripts/verify-real-integration.sh
```

**Checks**:
- [ ] `curl localhost:3001/health` returns 200
- [ ] `.env` ports match `docker-compose.yml` ports
- [ ] All expected tools exposed (count matches spec)
- [ ] Real tool execution succeeds (not mocked)
- [ ] Client config URLs are correct
- [ ] No errors in server startup logs

**FAILURE ACTION**: Do NOT proceed to Phase 7. Fix issues first.

## Phase 7: Internal Review

**Agent**: Chief of Staff
**Input**: All deliverables
**Output**: Review decision

**Chief of Staff**:
- Review all artifacts
- Check quality gates
- Validate completeness
- Apply learned patterns
- Decide: iterate or present to user

## Phase 7.5: Browser UI Testing (MANDATORY)

**Agent**: QA Lead
**Input**: Running MCP server, MCP Inspector
**Output**: `tests/ui/ui-test-results.json`, screenshots
**Type**: BLOCKING - Must pass before Phase 8 UAT

**WHY THIS EXISTS**: The user should NEVER be the first to test MCP tools in the browser. API tests can pass while browser interactions fail due to CORS, SSE handling, or UI issues.

**QA Lead MUST**:
1. Start MCP Inspector: `npx @modelcontextprotocol/inspector`
2. Run browser test: `python .claude-workspace/tests/ui/playwright_mcp_inspector.py --headed`
3. Verify ALL 17 tools are listed in MCP Inspector UI
4. Execute at least `embedding_health` tool and verify response shows `status: "healthy"`
5. Take screenshots as evidence
6. Save results to `tests/ui/ui-test-results.json`

**Mandatory Checks**:
- [ ] MCP Inspector connects successfully (green "Connected" status)
- [ ] Server shows "MCP Memory v3.0" with correct version
- [ ] All 17 tools visible in Tools list
- [ ] `embedding_health` tool returns healthy status
- [ ] No "Failed to fetch" errors in UI
- [ ] Screenshots captured for evidence

**FAILURE ACTION**: Do NOT proceed to UAT. Fix browser/UI issues first.

## Phase 8: UAT Presentation

**Agent**: Chief of Staff
**Trigger**: Internal review AND browser tests pass
**Output**: UAT package to user

**Pre-requisites** (MUST verify):
- [ ] Phase 6.5 real-world integration passed
- [ ] Phase 7.5 browser UI testing passed
- [ ] All screenshots captured

**Delivers**:
- Summary of work
- Key deliverables
- Test results (API + Browser)
- Demo instructions
- Request for approval or feedback

## Phase 9: User Decision

**User Action**: `/approve` or `/feedback [comments]`

### On Approval
- Archive completed work
- Log to learning system
- Reset workspace
- Ready for next task

### On Feedback
- Log feedback
- Categorize issues
- Route to appropriate phase
- Iterate until approved

## Task State Management

The `current-task.json` tracks:

```json
{
  "task_id": "task-YYYYMMDD-HHMMSS",
  "user_request": "...",
  "status": "planning|architecture|implementation|...|ready_for_uat|approved",
  "current_phase": "...",
  "phases": {
    "planning": { "status": "...", "started": "...", "completed": "..." }
  },
  "iterations": 0,
  "confidence": 0,
  "feedback_history": []
}
```

## Parallel Execution

Where possible, agents run in parallel:
- Backend + Frontend implementation
- Unit tests + Integration tests
- Security audit + Performance review

## Quality Gates

Each transition requires:
1. Previous phase complete
2. Artifacts validated
3. No blocking issues
4. Quality checks pass

## Failure Handling

If a phase fails:
1. Log the failure
2. Attempt remediation
3. If unrecoverable, escalate to user
4. Never proceed with broken state
