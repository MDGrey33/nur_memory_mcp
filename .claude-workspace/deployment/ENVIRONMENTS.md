# MCP Memory V7 - Environments Guide

This document describes all available environments, their configurations, and how to manage them.

## V6+ Tools (4 total)

| Tool | Description |
|------|-------------|
| `remember` | Store content with automatic chunking and event extraction |
| `recall` | Search/retrieve with semantic search and graph expansion |
| `forget` | Delete with cascade (chunks, events, entities) |
| `status` | Health check and job status |

## Environment Overview (per ADR-005)

| Environment | Purpose | MCP Port | PostgreSQL | ChromaDB |
|-------------|---------|----------|------------|----------|
| **prod** | Production | 3001 | 5432 | 8001 |
| **staging** | Pre-production testing | 3101 | 5532 | 8101 |
| **test** | CI/CD, E2E testing | 3201 | 5632 | 8201 |

*Port pattern: staging = prod + 100, test = prod + 200*

---

## Production Environment

### URLs
```
HTTP:  http://localhost:3001/mcp/
```

### Start Production
```bash
cd .claude-workspace/deployment
./scripts/env-up.sh prod
# Or manually:
docker compose --env-file .env.prod up -d
```

### Stop Production
```bash
./scripts/env-down.sh prod
```

### Claude Code Configuration
Configure in `.mcp.json`:
```json
{
  "mcpServers": {
    "memory": {
      "type": "http",
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

---

## Staging Environment

### URLs
```
HTTP:  http://localhost:3101/mcp/
```

### Start Staging
```bash
cd .claude-workspace/deployment
./scripts/env-up.sh staging
```

### Stop Staging
```bash
./scripts/env-down.sh staging
```

### Reset Staging (clears data)
```bash
./scripts/env-reset.sh staging
```

---

## Test Environment

### URLs
```
HTTP:  http://localhost:3201/mcp/
```

### Start Test Environment
```bash
cd .claude-workspace/deployment
./scripts/env-up.sh test
```

### Stop Test Environment
```bash
./scripts/env-down.sh test
```

### Reset Test Environment (clears data)
```bash
./scripts/env-reset.sh test
```

### Run E2E Tests
```bash
cd .claude-workspace/implementation/mcp-server
MCP_URL="http://localhost:3201/mcp/" PYTHONPATH=src pytest ../../tests/v6/e2e/ --run-e2e -v
```

---

## Environment Files

| File | Environment | Purpose |
|------|-------------|---------|
| `.env` | (all) | Secrets only (OPENAI_API_KEY), not committed |
| `.env.prod` | Production | Production config, port 3001 |
| `.env.staging` | Staging | Staging config, port 3101 |
| `.env.test` | Test | Test config, port 3201 |

### Key Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | (required) |
| `MCP_PORT` | MCP server external port | varies by env |
| `CHROMA_EXTERNAL_PORT` | ChromaDB external port | varies by env |
| `POSTGRES_EXTERNAL_PORT` | PostgreSQL external port | varies by env |
| `EVENTS_DB_DSN` | PostgreSQL connection | (required) |
| `LOG_LEVEL` | Logging verbosity | INFO |

---

## Scripts Reference

| Script | Description |
|--------|-------------|
| `./scripts/env-up.sh <env>` | Start environment, wait for healthy |
| `./scripts/env-down.sh <env> [-v]` | Stop environment, optionally remove volumes |
| `./scripts/env-reset.sh <env>` | Full reset (refuses prod for safety) |
| `./scripts/health-check.sh <env>` | Comprehensive health verification |

### Examples
```bash
# Start production
./scripts/env-up.sh prod

# Check staging health with JSON output
./scripts/health-check.sh staging --json

# Reset test environment (deletes data)
./scripts/env-reset.sh test

# Stop staging and remove volumes
./scripts/env-down.sh staging -v
```

---

## Quick Reference

### Check Running Containers
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(mcp|chroma|postgres)"
```

### View Logs
```bash
# Production
docker compose --env-file .env.prod logs -f mcp-server

# Staging
docker compose --env-file .env.staging -p mcp-memory-staging logs -f mcp-server

# Test
docker compose --env-file .env.test -p mcp-memory-test logs -f mcp-server
```

### Health Check
```bash
# Production
curl -s http://localhost:3001/health

# Staging
curl -s http://localhost:3101/health

# Test
curl -s http://localhost:3201/health
```

### List Tools
```bash
curl -X POST http://localhost:3001/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
# Expected: remember, recall, forget, status
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Memory V7 Architecture                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │   Claude     │     │   Claude     │     │    E2E       │    │
│  │    Code      │     │   Desktop    │     │   Tests      │    │
│  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘    │
│         │                    │                     │            │
│         │ HTTP :3001         │ HTTP :3101          │ HTTP :3201 │
│         │ (prod)             │ (staging)           │ (test)     │
│         ▼                    ▼                     ▼            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                     MCP Server (FastMCP)                  │  │
│  │  Tools: remember, recall, forget, status                  │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│         ┌─────────────────┼─────────────────┐                  │
│         ▼                 ▼                 ▼                  │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐           │
│  │  ChromaDB  │    │ PostgreSQL │    │   Event    │           │
│  │  (Vectors) │    │  (Events,  │    │   Worker   │           │
│  │            │    │  Entities) │    │            │           │
│  │ :8001 prod │    │ :5432 prod │    │ (async     │           │
│  │ :8101 stg  │    │ :5532 stg  │    │  extraction│           │
│  │ :8201 test │    │ :5632 test │    │  & upsert) │           │
│  └────────────┘    └────────────┘    └────────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### MCP Server Won't Start
```bash
# Check logs
docker compose --env-file .env.prod logs mcp-server

# Common issues:
# - OPENAI_API_KEY not set in .env
# - Database connection failed
# - Port already in use
```

### Database Connection Failed
```bash
# Test PostgreSQL
docker exec mcp-postgres pg_isready -U events

# Test ChromaDB
curl http://localhost:8001/api/v2/heartbeat
```

### Tools Not Appearing
1. Check URL has trailing slash: `http://localhost:3001/mcp/`
2. Add `"type": "http"` to .mcp.json
3. Verify server is running: `curl http://localhost:3001/health`
4. Restart Claude completely

---

**Last Updated:** 2026-01-02
**Version:** 7.0
