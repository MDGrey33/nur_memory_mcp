---
name: architecture
description: Design system architecture, data models, API contracts, and create Architecture Decision Records (ADRs)
allowed-tools: Read, Write, Edit, Glob, Grep, WebSearch
---

# Architecture Skill

Design sound technical architecture that is scalable, maintainable, and secure.

## When to Use

- Designing new system components
- Creating database schemas
- Defining API contracts
- Making technology decisions
- Writing Architecture Decision Records

## Process

1. **Analyze Requirements** - Understand core technical challenges
2. **Design Components** - Define system architecture and interactions
3. **Model Data** - Create database schemas with relationships
4. **Design APIs** - Define RESTful endpoints and contracts
5. **Document Decisions** - Create ADRs for major choices

## ADR Template

```markdown
# ADR-[NUMBER]: [Title]

**Status**: Proposed | Accepted | Rejected
**Date**: [YYYY-MM-DD]

## Context
[Why this decision is needed]

## Decision
[What was decided]

## Consequences
- Positive: [Benefits]
- Negative: [Trade-offs]

## Alternatives Considered
[Other options and why not chosen]
```

## Data Model Template

```markdown
## Entity: [Name]

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | uuid | PK, not null | Unique identifier |

### Relationships
- has_many: [Entity]
- belongs_to: [Entity]

### Indexes
- [fields]: For [query pattern]
```

## API Endpoint Template

```markdown
## [METHOD] /api/v1/[path]

**Purpose**: [Description]
**Auth**: Required/Optional

### Request
- Headers: Authorization, Content-Type
- Body: { field: type }
- Validation: [Rules]

### Response
- 200: { data: {...} }
- 400: { error: {...} }
- 401/403/404/500: [Error formats]
```

## Quality Checklist

- [ ] Scalable design (horizontal scaling possible)
- [ ] Security considered (auth, validation, encryption)
- [ ] Performance targets defined
- [ ] Error handling strategy
- [ ] Follows project conventions
- [ ] ADRs for major decisions
