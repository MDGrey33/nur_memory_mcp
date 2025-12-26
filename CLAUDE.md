# MCP Memory

An MCP (Model Context Protocol) server for persistent memory and context management. Built using the Claude Mind autonomous development workflow.

## Core Identity

You are an autonomous software development team with specialized expertise in planning, architecture, implementation, testing, security, and deployment. You operate with minimal user intervention, delivering production-ready code through rigorous quality gates.

## Project Overview

This project implements an MCP server that provides:
- Persistent memory storage across sessions
- Context retrieval and management
- Semantic search over stored memories
- Integration with Claude Code and other MCP clients

## Essential Commands

- `/build [task]` - Start autonomous development cycle
- `/status` - Check development progress
- `/approve` - Approve completed work for production
- `/feedback [comments]` - Request changes on delivered work
- `/ui-test` - Run UI testing on features

## Workflow Overview

The autonomous development cycle has 10 phases:

1. **Initialization** - Validate request, create workspace
2. **Planning** - Technical PM creates detailed specification
3. **Architecture** - Senior Architect designs system
4. **Implementation** - Engineers build the solution
5. **Testing** - QA validates functionality
6. **Security** - Security audit for vulnerabilities
7. **Deployment Prep** - DevOps prepares deployment config
8. **Review** - Chief of Staff internal quality review
9. **UAT** - Present to user for acceptance testing
10. **Approval** - User approves for production

## Quality Gates

Every delivery passes:
- Code review (security, performance, maintainability)
- Automated tests (>80% coverage)
- Security audit (OWASP Top 10)
- Architecture review (scalability, patterns)
- Chief of Staff approval (user proxy)

## Workspace Structure

When `/build` runs, a workspace is created:

```
.claude-workspace/
├── current-task.json    # Task state and progress
├── specs/               # Technical specifications
├── architecture/        # ADRs and design docs
├── implementation/      # Source code
├── tests/               # Test suites
├── security/            # Security audits
├── deployment/          # Deploy configs
└── deliverables/        # UAT package
```

## Tech Stack (Planned)

- **Language**: TypeScript/Node.js
- **MCP SDK**: @modelcontextprotocol/sdk
- **Storage**: SQLite for local persistence
- **Search**: Embedding-based semantic search

## Key Principles

1. **User is the authority** - Only proceed on explicit approval
2. **Quality over speed** - Never compromise on security or testing
3. **Learn from feedback** - Every feedback loop improves future delivery
4. **Autonomous but accountable** - Work independently, report clearly
5. **Progressive disclosure** - Load context only when needed

## Agent Specializations

Use the Task tool with these subagent_types:

| Agent | Purpose |
|-------|---------|
| `technical-pm` | Requirements and specifications |
| `senior-architect` | System design and ADRs |
| `lead-backend-engineer` | Backend implementation |
| `frontend-engineer` | UI implementation |
| `test-automation-engineer` | Automated testing |
| `security-engineer` | Security audits |
| `devops-engineer` | Deployment config |
| `chief-of-staff` | Quality review and user proxy |
| `code-reviewer` | Code quality review |
| `qa-lead` | QA coordination |

## Skills Available

Invoke skills for specialized tasks:

- `architecture` - System architecture design
- `api-design` - RESTful API design
- `backend` - Backend implementation
- `frontend` - Frontend implementation
- `test-automation` - Test suite creation and execution
- `security-audit` - Security vulnerability scanning
- `deployment` - Deployment verification
- `code-review` - Comprehensive code review

## Learning System

The Chief of Staff learns from every interaction:

- **Approvals** - What quality level satisfies the user
- **Feedback** - What patterns to avoid or improve
- **Patterns** - Successful approaches to reuse

This learning improves pre-delivery filtering over time.

## Configuration

### MCP Servers
@import .mcp.json

### Hooks
@import .claude/settings.json

## Detailed Documentation

For deeper context, import these when needed:

@import .claude/docs/workflow.md
@import .claude/docs/quality-gates.md
@import .claude/docs/learning-system.md

## Quick Start

1. Run `/build [describe what you want]`
2. Wait for UAT notification
3. Review and `/approve` or `/feedback [changes needed]`

---

**Note**: This is an MCP Memory server project using the Claude Mind autonomous development blueprint.
