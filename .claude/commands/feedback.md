---
description: Provide feedback on UAT results to request changes or improvements
---

# Feedback Command

User feedback: **$ARGUMENTS**

## Process

1. **Validate** - Check active task exists
2. **Acknowledge** - Confirm receipt
3. **Categorize** - Determine type (requirements, quality, ux, security)
4. **Route** - Send to appropriate phase/agent
5. **Log** - Record in learning system
6. **Iterate** - Re-invoke agent with feedback

## Categories & Routing

| Category | Phase | Agent |
|----------|-------|-------|
| requirements | Planning | Technical PM |
| quality/bugs | Implementation | Backend Engineer |
| ux | Implementation | Frontend Engineer |
| security | Security | Security Engineer |

## Confirmation

```markdown
## Iteration Started

**Feedback**: $ARGUMENTS
**Category**: [detected]
**Returning to**: [phase]

The team is addressing your feedback.

Check progress: /status
```

## Learning

Record feedback in `.claude-workspace/patterns.json` to improve future deliveries.
