# MCP Memory Server - Deployment

This directory contains deployment configuration for the MCP Memory Server V7.

## Quick Start

```bash
# Start production environment
./scripts/env-up.sh prod

# Check health
./scripts/health-check.sh prod

# Stop
./scripts/env-down.sh prod
```

See [CHEATSHEET.md](CHEATSHEET.md) for quick reference.

## Directory Structure

```
deployment/
├── CHEATSHEET.md           # Quick reference (ports, commands)
├── ENVIRONMENTS.md         # Detailed environment guide
├── docker-compose.yml      # Single compose file for all environments
├── .env                    # Secrets (OPENAI_API_KEY) - not in git
├── .env.prod               # Production config
├── .env.staging            # Staging config
├── .env.test               # Test config
├── .env.example            # Template for .env
├── init.sql                # Database initialization
├── healthcheck.py          # Container health check script
└── scripts/
    ├── env-up.sh           # Start environment
    ├── env-down.sh         # Stop environment
    ├── env-reset.sh        # Reset environment (wipe data)
    └── health-check.sh     # Check service health
```

## Environments

| Environment | MCP Port | ChromaDB | PostgreSQL | Purpose |
|-------------|----------|----------|------------|---------|
| **prod**    | 3001     | 8001     | 5432       | Production use |
| **staging** | 3101     | 8101     | 5532       | Pre-release testing |
| **test**    | 3201     | 8201     | 5632       | CI/CD, E2E tests |

All environments can run simultaneously.

## Configuration

### Secrets (`.env`)

Create `.env` with your API key:

```bash
OPENAI_API_KEY=sk-proj-your-key-here
```

This file is loaded by all environments and should never be committed.

### Environment Config

Each environment has its own config file (`.env.prod`, `.env.staging`, `.env.test`) with:
- Port mappings
- Database credentials
- Logging levels
- Feature flags

## Scripts

### env-up.sh

Start an environment and wait for healthy:

```bash
./scripts/env-up.sh prod      # Start production
./scripts/env-up.sh staging   # Start staging
./scripts/env-up.sh test      # Start test
```

### env-down.sh

Stop an environment:

```bash
./scripts/env-down.sh prod           # Stop, keep data
./scripts/env-down.sh staging -v     # Stop and remove volumes
```

### env-reset.sh

Reset environment (wipe all data):

```bash
./scripts/env-reset.sh test          # Reset test
./scripts/env-reset.sh staging       # Reset staging
./scripts/env-reset.sh prod --force  # Reset prod (requires --force)
```

### health-check.sh

Check service health:

```bash
./scripts/health-check.sh prod       # Check production
./scripts/health-check.sh staging    # Check staging
./scripts/health-check.sh test       # Check test
```

## Services

### MCP Server
- FastMCP-based HTTP server
- Provides 4 tools: `remember`, `recall`, `forget`, `status`
- Internal port 3000, mapped to environment-specific external port

### Event Worker
- Background worker for async event extraction
- Polls job queue and processes with OpenAI
- Updates entity graph

### ChromaDB
- Vector database for embeddings
- Stores content and chunks
- Internal port 8000

### PostgreSQL
- Events, entities, and job queue
- pgvector extension for vector search
- Internal port 5432

## Docker Commands

```bash
# View running containers
docker ps --filter "name=mcp-memory"

# View logs for production
docker logs mcp-memory-prod-mcp-server-1 -f

# Enter container shell
docker exec -it mcp-memory-prod-mcp-server-1 /bin/bash

# Clean up all environments
docker compose -p mcp-memory-prod down
docker compose -p mcp-memory-staging down
docker compose -p mcp-memory-test down
```

## Troubleshooting

### Services won't start

```bash
# Check for port conflicts
lsof -i :3001
lsof -i :8001

# View logs
docker logs mcp-memory-prod-mcp-server-1
```

### Health check failing

```bash
# Manual health check
curl http://localhost:3001/health
curl http://localhost:8001/api/v2/heartbeat
```

### Database issues

```bash
# Connect to postgres
docker exec -it mcp-memory-prod-postgres-1 psql -U events -d events
```

## Documentation

- [CHEATSHEET.md](CHEATSHEET.md) - Quick reference
- [ENVIRONMENTS.md](ENVIRONMENTS.md) - Detailed environment guide
- [Main README](../../README.md) - Project overview

---

**Version:** 7.0
**Last Updated:** 2026-01-02
