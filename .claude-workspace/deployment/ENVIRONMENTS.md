# MCP Memory - Environments Guide

This document describes all available environments, their configurations, and how to manage them.

## Environment Overview

| Environment | Purpose | MCP Port | PostgreSQL | ChromaDB | Status |
|-------------|---------|----------|------------|----------|--------|
| **Production** | Live data, Claude Code integration | 3001 | 5433 | 8001 | Active |
| **Staging** | Pre-production testing | 3101 | 5532 | 8101 | Not deployed |
| **Test** | E2E testing, CI/CD | 3201 | 5632 | 8201 | Active |

### Port Offset Strategy
- **Production**: Base ports
- **Staging**: +100 offset
- **Test**: +200 offset

---

## Production Environment

### URLs
```
HTTP:  http://localhost:3001/mcp/
```

### Services

| Service | Container | Port (External) | Port (Internal) |
|---------|-----------|-----------------|-----------------|
| MCP Server | mcp-server-prod | 3001 | 3000 |
| Event Worker | mcp-event-worker-prod | - | - |
| PostgreSQL | postgres-v4 | 5433 | 5432 |
| ChromaDB | chromadb | 8001 | 8000 |

### Database Configuration
```
PostgreSQL DSN: postgresql://events:events@localhost:5433/events
ChromaDB URL:   http://localhost:8001
Graph Name:     nur
```

### Start Production
```bash
# Databases should already be running (postgres-v4, chromadb)
# Start MCP server and worker:

OPENAI_KEY=$(docker exec mcp-server-v4-test printenv OPENAI_API_KEY)

# MCP Server
docker run -d \
  --name mcp-server-prod \
  --network host \
  -e "OPENAI_API_KEY=${OPENAI_KEY}" \
  -e CHROMA_HOST=localhost \
  -e CHROMA_PORT=8001 \
  -e "EVENTS_DB_DSN=postgresql://events:events@localhost:5433/events" \
  -e MCP_PORT=3001 \
  -e LOG_LEVEL=INFO \
  -e V4_GRAPH_ENABLED=true \
  -e V4_GRAPH_NAME=nur \
  mcp-memory-server:v4

# Event Worker
docker run -d \
  --name mcp-event-worker-prod \
  --network host \
  -e "OPENAI_API_KEY=${OPENAI_KEY}" \
  -e CHROMA_HOST=localhost \
  -e CHROMA_PORT=8001 \
  -e "EVENTS_DB_DSN=postgresql://events:events@localhost:5433/events" \
  -e LOG_LEVEL=INFO \
  -e V4_GRAPH_ENABLED=true \
  -e V4_GRAPH_NAME=nur \
  -e V4_WORKER_GRAPH_UPSERT=true \
  -e WORKER_ID=worker-prod-1 \
  mcp-memory-server:v4 \
  python -m src.worker
```

### Stop Production
```bash
docker stop mcp-server-prod mcp-event-worker-prod
docker rm mcp-server-prod mcp-event-worker-prod
```

### Clear Production Data
```bash
# Clear ChromaDB
for collection in memory artifacts history artifact_chunks; do
    curl -X DELETE "http://localhost:8001/api/v2/tenants/default_tenant/databases/default_database/collections/${collection}"
done

# Clear PostgreSQL
docker exec postgres-v4 psql -U events -d events -c "
TRUNCATE TABLE event_evidence, event_actor, event_subject, semantic_event,
               entity_mention, entity_alias, entity, event_jobs, artifact_revision CASCADE;
"
```

### Claude Code Configuration
Production is configured in `.mcp.json`:
```json
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

---

## Test Environment

### URLs
```
HTTP:   http://localhost:3201/mcp/
HTTPS:  https://<ngrok-subdomain>.ngrok-free.app/mcp/  (when tunnel active)
```

### Services

| Service | Container | Port (External) | Port (Internal) |
|---------|-----------|-----------------|-----------------|
| MCP Server | mcp-server-v4-test | 3201 | 3000 |
| Event Worker | mcp-event-worker-v4-test | - | 3000 |
| PostgreSQL | mcp-postgres-v4-test | 5632 | 5432 |
| ChromaDB | mcp-chroma-v4-test | 8201 | 8000 |

### Database Configuration
```
PostgreSQL DSN: postgresql://events:test_secret_changeme@localhost:5632/events_test
ChromaDB URL:   http://localhost:8201
Graph Name:     nur_test
```

### Start Test Environment
```bash
cd .claude-workspace/deployment

# Using docker-compose
docker compose -f docker-compose.test.yml --env-file .env.test up -d

# Or using the script
./scripts/env-up.sh test
```

### Stop Test Environment
```bash
docker compose -f docker-compose.test.yml --env-file .env.test down

# Or using the script
./scripts/env-down.sh test
```

### Run E2E Tests
```bash
cd .claude-workspace/tests/e2e-playwright
python -m pytest api/ -v

# Expected: 224 passed, 3 skipped
```

### Start ngrok Tunnel (for HTTPS)
```bash
ngrok http 3201
```

---

## Staging Environment

### URLs
```
HTTP:  http://localhost:3101/mcp/
```

### Services

| Service | Container | Port (External) | Port (Internal) |
|---------|-----------|-----------------|-----------------|
| MCP Server | mcp-server-staging | 3101 | 3000 |
| Event Worker | mcp-event-worker-staging | - | 3000 |
| PostgreSQL | mcp-postgres-staging | 5532 | 5432 |
| ChromaDB | mcp-chroma-staging | 8101 | 8000 |

### Database Configuration
```
PostgreSQL DSN: postgresql://events:staging_secret_changeme@localhost:5532/events_staging
ChromaDB URL:   http://localhost:8101
Graph Name:     nur_staging
```

### Start Staging Environment
```bash
cd .claude-workspace/deployment
docker compose -f docker-compose.test.yml --env-file .env.staging up -d
```

---

## Environment Files

| File | Environment | Location |
|------|-------------|----------|
| `.env.test` | Test | `.claude-workspace/deployment/.env.test` |
| `.env.staging` | Staging | `.claude-workspace/deployment/.env.staging` |
| `.env.prod` | Production | (not committed - use env vars) |

### Key Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `MCP_PORT` | MCP server port | `3001` |
| `EVENTS_DB_DSN` | PostgreSQL connection | `postgresql://...` |
| `CHROMA_HOST` | ChromaDB hostname | `localhost` |
| `CHROMA_PORT` | ChromaDB port | `8001` |
| `V4_GRAPH_ENABLED` | Enable graph features | `true` |
| `V4_GRAPH_NAME` | Apache AGE graph name | `nur` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

---

## Docker Volumes

### Production
| Volume | Purpose |
|--------|---------|
| `mcp_memory_v4_postgres_data` | PostgreSQL data |
| `mcp_memory_v4_chroma_data` | ChromaDB vectors |

### Test
| Volume | Purpose |
|--------|---------|
| `mcp_memory_v4_postgres_data_test` | Test PostgreSQL data |
| `mcp_memory_v4_chroma_data_test` | Test ChromaDB vectors |

---

## Quick Reference

### Check Running Containers
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(mcp|chroma|postgres)"
```

### View Logs
```bash
# Production
docker logs -f mcp-server-prod
docker logs -f mcp-event-worker-prod

# Test
docker logs -f mcp-server-v4-test
docker logs -f mcp-event-worker-v4-test
```

### Health Check
```bash
# Production
curl -s http://localhost:3001/health

# Test
curl -s http://localhost:3201/health
```

### Count Data
```bash
# ChromaDB collections (production)
curl -s "http://localhost:8001/api/v2/tenants/default_tenant/databases/default_database/collections"

# PostgreSQL (production)
docker exec postgres-v4 psql -U events -d events -c "SELECT COUNT(*) FROM artifact_revision;"
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Memory V4 Architecture                    │
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
│  │  - memory_store/search/list/delete                       │  │
│  │  - artifact_ingest/get                                   │  │
│  │  - hybrid_search (V4 graph expansion)                    │  │
│  │  - event_search/get/list_for_artifact                    │  │
│  │  - history_append/tail                                   │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│         ┌─────────────────┼─────────────────┐                  │
│         ▼                 ▼                 ▼                  │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐           │
│  │  ChromaDB  │    │ PostgreSQL │    │   Event    │           │
│  │  (Vectors) │    │ + AGE Graph│    │   Worker   │           │
│  │            │    │            │    │            │           │
│  │ :8001 prod │    │ :5433 prod │    │ (async     │           │
│  │ :8201 test │    │ :5632 test │    │  extraction│           │
│  └────────────┘    └────────────┘    │  + graph)  │           │
│                                       └────────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### MCP Server Won't Start
```bash
# Check logs
docker logs mcp-server-prod

# Common issues:
# - OPENAI_API_KEY not set
# - Database connection failed
# - Port already in use
```

### Database Connection Failed
```bash
# Test PostgreSQL
docker exec postgres-v4 pg_isready -U events

# Test ChromaDB
curl http://localhost:8001/api/v2/heartbeat
```

### Event Worker Not Processing
```bash
# Check worker logs
docker logs -f mcp-event-worker-prod

# Check job queue
docker exec postgres-v4 psql -U events -d events -c "SELECT status, COUNT(*) FROM event_jobs GROUP BY status;"
```

---

**Last Updated:** 2024-12-31
**Version:** 4.0
