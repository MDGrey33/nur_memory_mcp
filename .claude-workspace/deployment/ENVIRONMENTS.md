# MCP Memory V6.2 - Environments Guide

This document describes all available environments, their configurations, and how to manage them.

## V6 Tools (4 total)

| Tool | Description |
|------|-------------|
| `remember` | Store content with automatic chunking and event extraction |
| `recall` | Search/retrieve with semantic search and graph expansion |
| `forget` | Delete with cascade (chunks, events, entities) |
| `status` | Health check and job status |

## Environment Overview

| Environment | Purpose | MCP Port | PostgreSQL | ChromaDB | Compose File |
|-------------|---------|----------|------------|----------|--------------|
| **Default/Prod** | Production | 3000 | 5432 | 8001 | `docker-compose.yml` |
| **Local Dev** | Development | 3001 | 5432 | 8001 | `docker-compose.local.yml` |
| **Test** | E2E testing, CI/CD | 3201 | 5632 | 8201 | `docker-compose.test.yml` |

### Port Configuration (Source of Truth)

*All port configurations are defined in the compose files above.*

| Environment | MCP External | MCP Internal | Config Reference |
|-------------|--------------|--------------|------------------|
| Default/Prod | 3000 | 3000 | `${MCP_PORT:-3000}` |
| Local Dev | 3001 | 3000 | `${MCP_EXTERNAL_PORT:-3001}` |
| Test | 3201 | 3000 | `${MCP_PORT:-3201}` |

---

## Local Development Environment (Recommended)

### URLs
```
HTTP:  http://localhost:3001/mcp/
```

### Start Local Dev
```bash
cd .claude-workspace/deployment
docker compose -f docker-compose.local.yml up -d
```

### Stop Local Dev
```bash
docker compose -f docker-compose.local.yml down
```

### Claude Code Configuration
Configure in `.mcp.json`:
```json
{
  "mcpServers": {
    "memory": {
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

---

## Default/Production Environment

### URLs
```
HTTP:  http://localhost:3000/mcp/
```

### Start Production
```bash
cd .claude-workspace/deployment
docker compose up -d
```

### Stop Production
```bash
docker compose down
```

---

## Test Environment

### URLs
```
HTTP:   http://localhost:3201/mcp/
HTTPS:  https://<ngrok-subdomain>.ngrok-free.app/mcp/  (when tunnel active)
```

### Start Test Environment
```bash
cd .claude-workspace/deployment
docker compose -f docker-compose.test.yml --env-file .env.test up -d
```

### Stop Test Environment
```bash
docker compose -f docker-compose.test.yml --env-file .env.test down
```

### Run E2E Tests
```bash
cd .claude-workspace/implementation/mcp-server
MCP_URL="http://localhost:3201/mcp/" PYTHONPATH=src pytest ../../tests/v6/e2e/ --run-e2e -v
```

### Start ngrok Tunnel (for HTTPS)
```bash
ngrok http 3201
```

---

## Environment Files

| File | Environment | Location |
|------|-------------|----------|
| `.env.example` | Template | `.claude-workspace/deployment/.env.example` |
| `.env.test` | Test | `.claude-workspace/deployment/.env.test` |
| `.env` | Local (not committed) | `.claude-workspace/deployment/.env` |

### Key Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | (required) |
| `MCP_PORT` | MCP server port | `3000` |
| `EVENTS_DB_DSN` | PostgreSQL connection | (required) |
| `CHROMA_HOST` | ChromaDB hostname | `localhost` |
| `CHROMA_PORT` | ChromaDB port | `8001` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

---

## Quick Reference

### Check Running Containers
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(mcp|chroma|postgres)"
```

### View Logs
```bash
# Local Dev
docker compose -f docker-compose.local.yml logs -f mcp-server

# Test
docker compose -f docker-compose.test.yml logs -f mcp-server
```

### Health Check
```bash
# Local Dev
curl -s http://localhost:3001/health

# Default
curl -s http://localhost:3000/health

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
│                    MCP Memory V6.2 Architecture                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │   Claude     │     │   Claude     │     │    E2E       │    │
│  │    Code      │     │   Desktop    │     │   Tests      │    │
│  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘    │
│         │                    │                     │            │
│         │ HTTP :3001         │ HTTPS (ngrok)       │ HTTP :3201 │
│         ▼                    ▼                     ▼            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                     MCP Server (FastMCP)                  │  │
│  │  V6 Tools:                                                │  │
│  │  - remember (store content)                               │  │
│  │  - recall (search with graph expansion)                   │  │
│  │  - forget (cascade delete)                                │  │
│  │  - status (health check)                                  │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│         ┌─────────────────┼─────────────────┐                  │
│         ▼                 ▼                 ▼                  │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐           │
│  │  ChromaDB  │    │ PostgreSQL │    │   Event    │           │
│  │  (Vectors) │    │  (Events,  │    │   Worker   │           │
│  │            │    │  Entities) │    │            │           │
│  │ :8001 prod │    │ :5432 prod │    │ (async     │           │
│  │ :8201 test │    │ :5632 test │    │  extraction│           │
│  └────────────┘    └────────────┘    └────────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### MCP Server Won't Start
```bash
# Check logs
docker compose logs mcp-server

# Common issues:
# - OPENAI_API_KEY not set
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
2. Verify server is running: `curl http://localhost:3001/health`
3. Restart Claude completely

---

**Last Updated:** 2026-01-01
**Version:** 6.2.0
