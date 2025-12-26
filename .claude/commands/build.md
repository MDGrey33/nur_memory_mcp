---
description: Start autonomous development cycle with full team coordination
---

# Build Command

Start the autonomous development cycle for: **$ARGUMENTS**

## Your Mission

You are the Chief of Staff. Orchestrate the development team through all phases to deliver production-ready software.

## Detailed Workflow

@import ../docs/workflow.md

## Step 1: Initialize Workspace

```bash
mkdir -p .claude-workspace/{specs,architecture,implementation,tests,security,deployment,deliverables}

TASK_ID="task-$(date +%Y%m%d-%H%M%S)"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat > .claude-workspace/current-task.json << EOF
{
  "task_id": "$TASK_ID",
  "user_request": "$ARGUMENTS",
  "status": "planning",
  "created_at": "$TIMESTAMP",
  "iterations": 0,
  "confidence": 0
}
EOF
```

## Step 2: Execute Phases

Use Task tool to invoke agents sequentially:

### Phase 1: Planning
```
subagent_type: technical-pm
prompt: Create specification from the user request. Write to .claude-workspace/specs/
```

### Phase 2: Architecture
```
subagent_type: senior-architect
prompt: Design architecture based on specification. Write to .claude-workspace/architecture/
```

### Phase 3: Implementation

**Implementation Standards:**
- All API URLs must be configurable via environment variables
- Default to `http://localhost:3000` for development
- Create `.env.example` with all required environment variables
- Never hardcode URLs, ports, or secrets in source code

Run in parallel:
```
subagent_type: lead-backend-engineer
prompt: |
  Implement backend. Write to .claude-workspace/implementation/backend/

  REQUIRED: Make all API URLs configurable:
  - Use environment variables (e.g., API_BASE_URL, PORT)
  - Default PORT to 3000 for development
  - Create .env.example documenting all env vars
  - Include sample values (not real secrets)

subagent_type: frontend-engineer (if needed)
prompt: |
  Implement frontend. Write to .claude-workspace/implementation/frontend/

  REQUIRED: Make all API URLs configurable:
  - Use environment variables (e.g., REACT_APP_API_URL, VITE_API_URL)
  - Default to http://localhost:3000 for development
  - Create .env.example documenting all env vars
```

### Phase 4: Testing
```
subagent_type: test-automation-engineer
prompt: Write and run tests. Require >80% coverage. Write to .claude-workspace/tests/
```

### Phase 5: Security
```
subagent_type: security-engineer
prompt: Security audit. Write to .claude-workspace/security/
```

### Phase 6: Deployment
```
subagent_type: devops-engineer
prompt: Create deployment config. Write to .claude-workspace/deployment/
```

### Phase 7: Review
As Chief of Staff, review all deliverables against quality gates.

@import ../docs/quality-gates.md

## Step 3: Present UAT

When confidence >= 90%, present to user:

```markdown
## Ready for UAT

**Task**: [description]
**Confidence**: [X]%

### Deliverables
- Specification: .claude-workspace/specs/
- Implementation: .claude-workspace/implementation/
- Tests: .claude-workspace/tests/
- Security Audit: .claude-workspace/security/

### Next Steps
- `/approve` - Approve for production
- `/feedback [comments]` - Request changes
```

## Error Handling

If any phase fails, log the error and attempt remediation. Escalate to user only for true blockers.
