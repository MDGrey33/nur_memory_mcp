# MCP Memory Server - Quick Reference

## Environments & Ports

| Environment | MCP Server | ChromaDB | PostgreSQL |
|-------------|------------|----------|------------|
| **prod**    | 3001       | 8001     | 5432       |
| **staging** | 3101       | 8101     | 5532       |
| **test**    | 3201       | 8201     | 5632       |

## Commands

```bash
# Start environment
./scripts/env-up.sh prod
./scripts/env-up.sh staging
./scripts/env-up.sh test

# Stop environment
./scripts/env-down.sh prod
./scripts/env-down.sh staging
./scripts/env-down.sh test

# Stop and remove data
./scripts/env-down.sh test -v

# Health check
./scripts/health-check.sh prod
./scripts/health-check.sh staging
./scripts/health-check.sh test

# Reset (wipe data and restart)
./scripts/env-reset.sh test
./scripts/env-reset.sh staging
./scripts/env-reset.sh prod --force  # requires --force
```

## URLs (when running)

```
# Production
http://localhost:3001/health
http://localhost:3001/mcp/

# Staging
http://localhost:3101/health
http://localhost:3101/mcp/

# Test
http://localhost:3201/health
http://localhost:3201/mcp/
```

## Docker Commands

```bash
# View running containers
docker ps --filter "name=mcp-memory"

# View logs
docker logs mcp-memory-prod-mcp-server-1 -f
docker logs mcp-memory-prod-event-worker-1 -f

# Enter container shell
docker exec -it mcp-memory-prod-mcp-server-1 /bin/bash
```

## Config Files

| File | Purpose |
|------|---------|
| `.env` | Secrets (OPENAI_API_KEY) |
| `.env.prod` | Production config |
| `.env.staging` | Staging config |
| `.env.test` | Test config |
| `docker-compose.yml` | Service definitions |
