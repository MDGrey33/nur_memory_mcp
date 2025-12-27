# MCP Memory Server V3: Deployment Configuration

**Version:** 3.0
**Date:** 2025-12-27
**Status:** Production Ready

---

## Quick Start

### 1. Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- OpenAI API Key

### 2. Setup Environment

```bash
# Copy environment template
cp .env.example .env

# Edit with your OpenAI API key
nano .env
# Set: OPENAI_API_KEY=sk-proj-your-key-here
```

### 3. Start V3 Stack

```bash
# Production deployment
docker-compose -f docker-compose.v3.yml up -d

# Development deployment (with debug ports and hot reload)
docker-compose -f docker-compose.v3.yml -f docker-compose.v3.dev.yml up -d
```

### 4. Verify Deployment

```bash
# Check all services
docker-compose -f docker-compose.v3.yml ps

# Run health checks
docker-compose -f docker-compose.v3.yml exec mcp-server python healthcheck.py --service all

# View logs
docker-compose -f docker-compose.v3.yml logs -f
```

### 5. Configure MCP Client

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["@anthropic-ai/mcp-remote", "http://localhost:3000/mcp/"]
    }
  }
}
```

Restart Claude Desktop after configuration.

---

## Architecture Overview

V3 consists of **4 Docker containers**:

```
┌─────────────────────────────────────────────────────────────┐
│                    V3 DOCKER STACK                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  mcp-server  │  │   chroma     │  │  postgres    │      │
│  │  (FastMCP)   │  │  (Vectors)   │  │  (Events)    │      │
│  │  Port: 3000  │  │  Port: 8001  │  │  Port: 5432  │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │              │
│         └─────────────────┼─────────────────┘              │
│                           │                                │
│  ┌────────────────────────┼──────────────────┐             │
│  │     event-worker       │                  │             │
│  │     (Async Extract)    │                  │             │
│  │     No ports           │                  │             │
│  └────────────────────────┴──────────────────┘             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Service Details

| Service | Purpose | Dependencies | Ports |
|---------|---------|--------------|-------|
| **mcp-server** | FastMCP server with 17 tools | chroma, postgres | 3000 |
| **chroma** | Vector storage for embeddings | (none) | 8001:8000 |
| **postgres** | Relational DB for events/jobs | (none) | 5432:5432 |
| **event-worker** | Async event extraction worker | chroma, postgres | (none) |

---

## File Reference

### Configuration Files

| File | Description |
|------|-------------|
| **docker-compose.v3.yml** | Production V3 configuration |
| **docker-compose.v3.dev.yml** | Development overrides |
| **.env.example** | Environment variables template |
| **init.sql** | Database initialization script |
| **Dockerfile** | Multi-stage production Dockerfile |
| **healthcheck.py** | Health check script for containers |

### Documentation

| File | Description |
|------|-------------|
| **V3-README.md** | This file - quick reference |
| **deploy.md** | Comprehensive deployment guide |
| **monitoring.md** | Monitoring and observability guide |

---

## Common Commands

### Service Management

```bash
# Start all services
docker-compose -f docker-compose.v3.yml up -d

# Stop all services
docker-compose -f docker-compose.v3.yml stop

# Restart specific service
docker-compose -f docker-compose.v3.yml restart mcp-server

# View logs
docker-compose -f docker-compose.v3.yml logs -f [service]

# Check status
docker-compose -f docker-compose.v3.yml ps
```

### Health Checks

```bash
# Check all services
docker-compose -f docker-compose.v3.yml exec mcp-server python healthcheck.py --service all

# Check specific service
docker-compose -f docker-compose.v3.yml exec mcp-server python healthcheck.py --service mcp-server
docker-compose -f docker-compose.v3.yml exec mcp-server python healthcheck.py --service worker
docker-compose -f docker-compose.v3.yml exec mcp-server python healthcheck.py --service postgres
docker-compose -f docker-compose.v3.yml exec mcp-server python healthcheck.py --service chroma
```

### Database Operations

```bash
# Connect to Postgres
docker-compose -f docker-compose.v3.yml exec postgres psql -U events -d events

# Check tables
docker-compose -f docker-compose.v3.yml exec postgres psql -U events -d events -c "\dt"

# View job queue status
docker-compose -f docker-compose.v3.yml exec postgres psql -U events -d events -c \
  "SELECT status, COUNT(*) FROM event_jobs GROUP BY status;"

# View recent events
docker-compose -f docker-compose.v3.yml exec postgres psql -U events -d events -c \
  "SELECT event_id, category, narrative FROM semantic_event ORDER BY created_at DESC LIMIT 5;"
```

### Scaling Workers

```bash
# Run multiple workers
docker-compose -f docker-compose.v3.yml up -d --scale event-worker=3

# Note: Each worker needs a unique WORKER_ID
# Edit docker-compose.v3.yml to add worker-2, worker-3, etc.
```

### Backup & Restore

```bash
# Backup Postgres
docker-compose -f docker-compose.v3.yml exec postgres pg_dump -U events events > backup_$(date +%Y%m%d).sql

# Restore Postgres
docker-compose -f docker-compose.v3.yml exec -T postgres psql -U events events < backup.sql

# Backup volumes
docker run --rm -v mcp_memory_v3_postgres_data:/data -v $(pwd):/backup \
  ubuntu tar czf /backup/postgres_backup.tar.gz -C /data .

docker run --rm -v mcp_memory_v3_chroma_data:/data -v $(pwd):/backup \
  ubuntu tar czf /backup/chroma_backup.tar.gz -C /data .
```

### Clean Up

```bash
# Stop and remove containers
docker-compose -f docker-compose.v3.yml down

# Remove containers and volumes (WARNING: deletes all data!)
docker-compose -f docker-compose.v3.yml down -v

# Remove images
docker rmi mcp-memory-server:v3

# Full reset and rebuild
docker-compose -f docker-compose.v3.yml down -v
docker-compose -f docker-compose.v3.yml build --no-cache
docker-compose -f docker-compose.v3.yml up -d
```

---

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Your OpenAI API key (required) |

### Optional (with defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_EMBED_MODEL` | `text-embedding-3-large` | Embedding model |
| `OPENAI_EVENT_MODEL` | `gpt-4o-mini` | Event extraction model |
| `POSTGRES_DB` | `events` | PostgreSQL database name |
| `POSTGRES_USER` | `events` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `events` | PostgreSQL password |
| `EVENTS_DB_DSN` | `postgresql://...` | Full connection string |
| `MCP_PORT` | `3000` | MCP server port |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `WORKER_ID` | `worker-1` | Worker identifier |
| `POLL_INTERVAL_MS` | `1000` | Job polling interval (milliseconds) |
| `EVENT_MAX_ATTEMPTS` | `5` | Max retry attempts for jobs |

---

## Troubleshooting

### Service won't start

```bash
# Check logs
docker-compose -f docker-compose.v3.yml logs [service]

# Check if port is in use
lsof -i :3000
lsof -i :5432
lsof -i :8001

# Restart service
docker-compose -f docker-compose.v3.yml restart [service]
```

### Database connection failed

```bash
# Check Postgres is healthy
docker-compose -f docker-compose.v3.yml ps postgres

# Verify connection
docker-compose -f docker-compose.v3.yml exec postgres psql -U events -d events -c "SELECT 1;"

# Check environment variables
docker-compose -f docker-compose.v3.yml exec mcp-server env | grep DB_DSN
```

### Worker not processing jobs

```bash
# Check worker logs
docker-compose -f docker-compose.v3.yml logs event-worker --tail=50

# Check job queue
docker-compose -f docker-compose.v3.yml exec postgres psql -U events -d events -c \
  "SELECT job_id, status, attempts, last_error_message FROM event_jobs WHERE status='PENDING' LIMIT 10;"

# Restart worker
docker-compose -f docker-compose.v3.yml restart event-worker
```

### Out of memory

```bash
# Check resource usage
docker stats

# Increase memory limits in docker-compose.v3.yml:
# deploy:
#   resources:
#     limits:
#       memory: 4G  # Increase from 2G
```

---

## Development Mode

### Enable Debug Mode

```bash
# Start with development overrides
docker-compose -f docker-compose.v3.yml -f docker-compose.v3.dev.yml up -d

# Attach debugger to mcp-server (port 5678)
# Attach debugger to event-worker (port 5679)

# Access pgAdmin at http://localhost:5050
# Login: admin@mcp.local / admin
```

### Hot Reload

Development mode mounts source directories as read-only volumes, enabling hot reload without rebuilding containers.

### View All Logs

```bash
# Follow all logs
docker-compose -f docker-compose.v3.yml -f docker-compose.v3.dev.yml logs -f

# Filter for errors
docker-compose -f docker-compose.v3.yml logs --no-color | grep ERROR
```

---

## Deployment Checklist

### Before Production Deployment

- [ ] Set strong `POSTGRES_PASSWORD` in `.env`
- [ ] Update `EVENTS_DB_DSN` with new password
- [ ] Set `OPENAI_EVENT_MODEL=gpt-4o` for best quality (optional)
- [ ] Set `LOG_LEVEL=INFO`
- [ ] Review resource limits in `docker-compose.v3.yml`
- [ ] Set up backup strategy (see Backup section in deploy.md)
- [ ] Configure monitoring (see monitoring.md)
- [ ] Test health checks work
- [ ] Configure firewall rules
- [ ] Set up SSL/TLS if exposing publicly

### After Deployment

- [ ] Verify all services are healthy
- [ ] Test end-to-end functionality
- [ ] Configure MCP client (Claude Desktop, etc.)
- [ ] Set up automated backups
- [ ] Configure log aggregation
- [ ] Set up alerting
- [ ] Document any custom configuration

---

## Resource Requirements

### Minimum (Development)

- CPU: 2 cores
- RAM: 4GB
- Disk: 10GB

### Recommended (Production)

- CPU: 4 cores
- RAM: 8GB
- Disk: 50GB SSD

### Expected Growth

- ~10 GB/year for 1000 documents/day
- See architecture document for detailed projections

---

## Support

### Documentation

- **Full Deployment Guide**: `deploy.md`
- **Monitoring Guide**: `monitoring.md`
- **V3 Specification**: `../specs/v3-specification.md`
- **V3 Architecture**: `../architecture/v3-architecture.md`

### Health Endpoints

- MCP Server: `http://localhost:3000/health`
- ChromaDB: `http://localhost:8001/api/v2/heartbeat`
- PostgreSQL: `psql -U events -d events -c "SELECT 1;"`

### Common Issues

See **Troubleshooting** section in `deploy.md` for comprehensive troubleshooting guide.

---

**Last Updated**: 2025-12-27
**Version**: 3.0
**Maintainer**: MCP Memory Team
