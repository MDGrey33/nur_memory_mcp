---
description: Approve the completed work and mark as production-ready
---

# Approve Command

User approves work for production.

## Prerequisites

Task must be in `ready_for_uat` status.

## Process

1. **Validate** - Check `.claude-workspace/current-task.json` exists and status is `ready_for_uat`
2. **Update Status** - Mark as approved in current-task.json
3. **Archive** - Copy `.claude-workspace/` to `archive/[task_id]/`
4. **Log Learning** - Update `.claude-workspace/patterns.json` with approval record
5. **Clean Up** - Reset `.claude-workspace/` for next task

## Confirmation

```markdown
## Task Approved

**Task ID**: [id]
**Archived**: archive/[id]/

### Deliverables
- Implementation: archive/[id]/implementation/
- Tests: archive/[id]/tests/
- Documentation: archive/[id]/deployment/

Ready for your next task!
Run: /build [new task]
```
