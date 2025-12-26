---
description: Check the progress of the current development task
---

# Status Command

Check current development task status.

## Process

1. Read `.claude-workspace/current-task.json`
2. Check phase completion (`.done` files)
3. Present status report

## If No Task

```markdown
No active development task.

Start one with: /build [describe what you want]
```

## Status Format

```markdown
## Development Status

**Task ID**: [id]
**Status**: [status]
**Phase**: [current_phase]
**Iterations**: [count]

### Progress
| Phase | Status |
|-------|--------|
| Planning | [status] |
| Architecture | [status] |
| Implementation | [status] |
| Testing | [status] |
| Security | [status] |
| Deployment | [status] |

### Commands
- `/status` - Refresh
- `/approve` - Approve (if ready)
- `/feedback [text]` - Request changes
```
