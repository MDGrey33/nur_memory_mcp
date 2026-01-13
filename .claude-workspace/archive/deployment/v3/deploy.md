# MCP Memory Server V3: Deployment Guide

**Version:** 3.0
**Date:** 2025-12-27
**Status:** Production Ready

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Detailed Setup](#detailed-setup)
4. [Configuration](#configuration)
5. [Deployment Verification](#deployment-verification)
6. [Scaling](#scaling)
7. [Backup & Restore](#backup--restore)
8. [Troubleshooting](#troubleshooting)
9. [Maintenance](#maintenance)
10. [Security Considerations](#security-considerations)

---

## Prerequisites

### Required Software

- **Docker**: Version 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- **Docker Compose**: Version 2.0+ (included with Docker Desktop)
- **OpenAI API Key**: [Get API Key](https://platform.openai.com/api-keys)

### Minimum System Requirements

- **CPU**: 2 cores (4+ recommended for production)
- **RAM**: 4GB (8GB+ recommended for production)
- **Disk**: 20GB free space (SSD recommended)
- **OS**: Linux, macOS, or Windows with WSL2

### Network Requirements

- **Ports**:
  - `3000`: MCP Server (HTTP)
  - `5432`: PostgreSQL (optional, for external access)
  - `8001`: ChromaDB (optional, for external access)

---

## Quick Start

### 1. Clone/Copy Deployment Files

```bash
cd /path/to/mcp_memory/.claude-workspace/deployment
```

### 2. Create Environment File

```bash
# Copy example environment file
cp .env.example .env

# Edit with your OpenAI API key
nano .env  # or vim, code, etc.
```

**Required:** Set `OPENAI_API_KEY` in `.env`:
```bash
OPENAI_API_KEY=sk-proj-your-actual-key-here
```

### 3. Start Services

```bash
# Build and start all services
docker-compose up -d

# Check logs
docker-compose logs -f
```

### 4. Verify Deployment

```bash
# Run health checks
docker-compose exec mcp-server python healthcheck.py --service all

# Check service status
docker-compose ps
```

### 5. Test MCP Connection

```bash
# Test basic connectivity
curl http://localhost:3001/health

# Configure Claude Desktop (see Configuration section below)
```

---

## Detailed Setup

### Step 1: Environment Configuration

1. **Copy `.env.example` to `.env`**:
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with your settings**:
   ```bash
   # Required
   OPENAI_API_KEY=sk-proj-your-key-here

   # Optional: Choose models
   OPENAI_EMBED_MODEL=text-embedding-3-large
   OPENAI_EVENT_MODEL=gpt-4o-mini  # or gpt-4o for production

   # Optional: Database credentials (change for production!)
   POSTGRES_PASSWORD=your-secure-password-here
   EVENTS_DB_DSN=postgresql://events:your-secure-password-here@postgres:5432/events
   ```

3. **Review configuration**:
   - See [Configuration](#configuration) section for all options
   - See `.env.example` for detailed descriptions

### Step 2: Build Images

```bash
# Build all images
docker-compose build

# Or build individually
docker-compose build mcp-server
docker-compose build event-worker
```

### Step 3: Initialize Database

The database is automatically initialized on first startup via `init.sql`.

To manually verify database:
```bash
# Connect to Postgres
docker-compose exec postgres psql -U events -d events

# Check tables
\dt

# Verify migrations
SELECT * FROM artifact_revision LIMIT 1;
SELECT * FROM event_jobs LIMIT 1;
SELECT * FROM semantic_event LIMIT 1;
SELECT * FROM event_evidence LIMIT 1;
```

### Step 4: Start Services

```bash
# Start all services in detached mode
docker-compose up -d

# Start with specific service order (recommended for first time)
docker-compose up -d chroma postgres
sleep 10  # Wait for health checks
docker-compose up -d mcp-server event-worker
```

### Step 5: Verify Services

```bash
# Check container status
docker-compose ps

# All containers should show "healthy" or "running"

# Check logs
docker-compose logs mcp-server
docker-compose logs event-worker
docker-compose logs postgres
docker-compose logs chroma

# Run health checks
docker-compose exec mcp-server python healthcheck.py --service all
```

---

## Configuration

### MCP Client Configuration

#### Claude Desktop / Claude.ai

Claude Desktop and Claude.ai require HTTPS. Use ngrok to expose your local server:

```bash
ngrok http 3001
```

Then configure via the UI:

1. Open **Claude Desktop** or **Claude.ai** (web)
2. Go to **Settings** → **Connectors**
3. Click **Add Custom Connector**
4. Enter:
   - **Name**: `memory`
   - **URL**: `https://your-ngrok-url.ngrok-free.app/mcp/`

> **Important**: Always include the trailing slash in the URL!

#### Cursor IDE

Add to Cursor settings:
```json
{
  "mcp.servers": {
    "memory": {
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

### Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *Required* | OpenAI API key |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-large` | Embedding model |
| `OPENAI_EVENT_MODEL` | `gpt-4o-mini` | Event extraction model |
| `POSTGRES_DB` | `events` | PostgreSQL database name |
| `POSTGRES_USER` | `events` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `events` | PostgreSQL password |
| `EVENTS_DB_DSN` | `postgresql://...` | Full connection string |
| `CHROMA_HOST` | `chroma` | ChromaDB hostname |
| `CHROMA_PORT` | `8000` | ChromaDB port |
| `MCP_PORT` | `3000` | MCP server port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `WORKER_ID` | `worker-1` | Worker identifier |
| `POLL_INTERVAL_MS` | `1000` | Job polling interval |
| `EVENT_MAX_ATTEMPTS` | `5` | Max retry attempts |

### Resource Limits

Edit `docker-compose.yml` to adjust resource limits:

```yaml
services:
  mcp-server:
    deploy:
      resources:
        limits:
          memory: 2G  # Increase for larger workloads
          cpus: '1.0'
        reservations:
          memory: 512M
          cpus: '0.25'
```

---

## Deployment Verification

### Health Check Script

```bash
# Check all services
docker-compose exec mcp-server python healthcheck.py --service all

# Check individual services
docker-compose exec mcp-server python healthcheck.py --service mcp-server
docker-compose exec mcp-server python healthcheck.py --service worker
docker-compose exec mcp-server python healthcheck.py --service postgres
docker-compose exec mcp-server python healthcheck.py --service chroma
```

### Manual Verification

#### 1. Test MCP Server
```bash
# HTTP endpoint should respond
curl http://localhost:3001/health

# Or use httpie
http GET http://localhost:3001/health
```

#### 2. Test ChromaDB
```bash
curl http://localhost:8001/api/v2/heartbeat
```

#### 3. Test PostgreSQL
```bash
docker-compose exec postgres psql -U events -d events -c "SELECT version();"
```

#### 4. Test Event Worker
```bash
# Check worker logs for polling activity
docker-compose logs event-worker --tail=20

# Should see: "Polling for jobs..." every POLL_INTERVAL_MS
```

#### 5. End-to-End Test

Use Claude Desktop or CLI to test:
```
# In Claude Desktop, try:
Store this in memory: "Team decided to adopt microservices architecture"

# Wait a few seconds, then:
Search for decisions about architecture
```

---

## Scaling

### Horizontal Scaling: Multiple Workers

Edit `docker-compose.yml` to add more workers:

```yaml
services:
  event-worker-1:
    <<: *worker-config  # Use YAML anchor
    container_name: mcp-event-worker-1
    environment:
      - WORKER_ID=worker-1
      # ... other env vars

  event-worker-2:
    <<: *worker-config
    container_name: mcp-event-worker-2
    environment:
      - WORKER_ID=worker-2
      # ... other env vars

  event-worker-3:
    <<: *worker-config
    container_name: mcp-event-worker-3
    environment:
      - WORKER_ID=worker-3
      # ... other env vars
```

Then restart:
```bash
docker-compose up -d --scale event-worker=3
```

**Note**: Workers use `FOR UPDATE SKIP LOCKED` to avoid processing same job.

### Vertical Scaling: More Resources

Increase memory/CPU limits in `docker-compose.yml`:

```yaml
services:
  mcp-server:
    deploy:
      resources:
        limits:
          memory: 4G  # Increased from 2G
          cpus: '2.0'  # Increased from 1.0
```

### Database Scaling

For production, consider:

1. **External PostgreSQL**: Use managed PostgreSQL (AWS RDS, Google Cloud SQL)
2. **Connection Pooling**: Use PgBouncer for connection pooling
3. **Read Replicas**: For read-heavy workloads

---

## Backup & Restore

### Automated Backups

#### 1. PostgreSQL Backup

```bash
# Backup script (save as backup.sh)
#!/bin/bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker-compose exec -T postgres pg_dump -U events events | gzip > "backup_postgres_${TIMESTAMP}.sql.gz"
```

#### 2. ChromaDB Backup

```bash
# Backup ChromaDB volume
docker run --rm -v mcp-chroma-data:/data -v $(pwd):/backup \
  ubuntu tar czf /backup/backup_chroma_${TIMESTAMP}.tar.gz -C /data .
```

#### 3. Scheduled Backups (Cron)

```bash
# Add to crontab (crontab -e)
# Daily backup at 2 AM
0 2 * * * /path/to/mcp_memory/deployment/backup.sh

# Weekly full backup on Sundays at 3 AM
0 3 * * 0 /path/to/mcp_memory/deployment/backup_full.sh
```

### Manual Backup

```bash
# Stop services (optional, for consistent backup)
docker-compose stop

# Backup Postgres
docker-compose exec postgres pg_dump -U events events > backup_postgres.sql

# Backup volumes
docker run --rm \
  -v deployment_postgres_data:/data \
  -v $(pwd):/backup \
  ubuntu tar czf /backup/backup_postgres_data.tar.gz -C /data .

docker run --rm \
  -v deployment_chroma_data:/data \
  -v $(pwd):/backup \
  ubuntu tar czf /backup/backup_chroma_data.tar.gz -C /data .

# Restart services
docker-compose start
```

### Restore Procedure

#### Restore PostgreSQL

```bash
# Stop services
docker-compose stop

# Restore database
docker-compose exec -T postgres psql -U events events < backup_postgres.sql

# Or restore from volume backup
docker run --rm \
  -v deployment_postgres_data:/data \
  -v $(pwd):/backup \
  ubuntu tar xzf /backup/backup_postgres_data.tar.gz -C /data

# Start services
docker-compose start
```

#### Restore ChromaDB

```bash
# Stop services
docker-compose stop

# Restore volume
docker run --rm \
  -v deployment_chroma_data:/data \
  -v $(pwd):/backup \
  ubuntu tar xzf /backup/backup_chroma_data.tar.gz -C /data

# Start services
docker-compose start
```

---

## Troubleshooting

### Common Issues

#### 1. "OPENAI_API_KEY is required" Error

**Problem**: Missing or invalid OpenAI API key.

**Solution**:
```bash
# Check .env file
cat .env | grep OPENAI_API_KEY

# Ensure key starts with sk-
# Restart services
docker-compose restart
```

#### 2. PostgreSQL Connection Failed

**Problem**: Cannot connect to Postgres.

**Symptoms**:
```
psycopg2.OperationalError: could not connect to server
```

**Solution**:
```bash
# Check Postgres is healthy
docker-compose ps postgres

# Check logs
docker-compose logs postgres

# Restart Postgres
docker-compose restart postgres

# Wait for health check
sleep 10

# Verify connection
docker-compose exec postgres psql -U events -d events -c "SELECT 1;"
```

#### 3. ChromaDB Not Responding

**Problem**: ChromaDB heartbeat fails.

**Solution**:
```bash
# Check ChromaDB health
docker-compose ps chroma

# Check logs
docker-compose logs chroma

# Test heartbeat
curl http://localhost:8001/api/v2/heartbeat

# Restart ChromaDB
docker-compose restart chroma
```

#### 4. Worker Not Processing Jobs

**Problem**: Jobs stuck in PENDING state.

**Solution**:
```bash
# Check worker logs
docker-compose logs event-worker --tail=100

# Verify worker is polling
# Should see "Polling for jobs..." messages

# Check job status in database
docker-compose exec postgres psql -U events -d events -c \
  "SELECT job_id, status, attempts, last_error_message FROM event_jobs WHERE status='PENDING' LIMIT 10;"

# Restart worker
docker-compose restart event-worker
```

#### 5. Out of Memory Errors

**Problem**: Container killed due to OOM.

**Symptoms**:
```
Container exited with code 137
```

**Solution**:
```bash
# Check Docker resource limits
docker stats

# Increase memory limits in docker-compose.yml
# Then restart
docker-compose up -d
```

#### 6. Port Already in Use

**Problem**: Port 3000, 5432, or 8001 already bound.

**Solution**:
```bash
# Find process using port
lsof -i :3000

# Kill process or change port in docker-compose.yml
# Edit docker-compose.yml:
ports:
  - "3001:3000"  # Changed external port

# Restart
docker-compose up -d
```

### Debug Mode

Enable debug logging:

```bash
# Edit .env
LOG_LEVEL=DEBUG

# Restart services
docker-compose restart

# View detailed logs
docker-compose logs -f mcp-server
docker-compose logs -f event-worker
```

### Reset Everything

If all else fails, complete reset:

```bash
# Stop and remove everything
docker-compose down -v

# Remove images
docker-compose rm -f
docker rmi mcp-memory-server:v3

# Rebuild and restart
docker-compose build --no-cache
docker-compose up -d
```

---

## Maintenance

### Regular Tasks

#### Daily
- [ ] Check container health: `docker-compose ps`
- [ ] Review error logs: `docker-compose logs --tail=100 | grep ERROR`

#### Weekly
- [ ] Review job failures: Check `event_jobs` table for FAILED status
- [ ] Check disk usage: `docker system df`
- [ ] Review resource usage: `docker stats`
- [ ] Backup databases (see Backup section)

#### Monthly
- [ ] Update Docker images: `docker-compose pull`
- [ ] Clean old data (if retention policies implemented)
- [ ] Review and rotate logs
- [ ] Update OpenAI models if new versions available

### Log Management

```bash
# View logs
docker-compose logs -f [service]

# Limit log size
docker-compose logs --tail=100 [service]

# Follow specific service
docker-compose logs -f mcp-server

# Export logs
docker-compose logs --no-color > logs_$(date +%Y%m%d).txt

# Clean old logs
docker-compose logs --since 24h > recent_logs.txt
```

### Database Maintenance

```bash
# Vacuum Postgres (reclaim space)
docker-compose exec postgres psql -U events -d events -c "VACUUM ANALYZE;"

# Check database size
docker-compose exec postgres psql -U events -d events -c \
  "SELECT pg_size_pretty(pg_database_size('events'));"

# Check table sizes
docker-compose exec postgres psql -U events -d events -c \
  "SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
   FROM pg_catalog.pg_statio_user_tables
   ORDER BY pg_total_relation_size(relid) DESC;"
```

### Updating to New Version

```bash
# Pull latest code
git pull origin main

# Rebuild images
docker-compose build

# Stop services
docker-compose stop

# Run migrations (if any)
# Migrations run automatically on postgres startup

# Start services
docker-compose up -d

# Verify health
docker-compose exec mcp-server python healthcheck.py --service all
```

---

## Security Considerations

### Production Checklist

- [ ] **Change default passwords**: Update `POSTGRES_PASSWORD` in `.env`
- [ ] **Use strong API keys**: Rotate OpenAI API keys regularly
- [ ] **Enable SSL**: For Postgres if exposing port publicly
- [ ] **Firewall rules**: Restrict access to ports 3000, 5432, 8001
- [ ] **Non-root user**: Dockerfile uses non-root user (already configured)
- [ ] **Secrets management**: Use Docker secrets or environment variable injection
- [ ] **Regular updates**: Keep Docker images and dependencies updated
- [ ] **Audit logs**: Enable audit logging for Postgres
- [ ] **Backup encryption**: Encrypt backup files
- [ ] **Network isolation**: Use Docker networks (already configured)

### SSL/TLS for MCP Server

Use reverse proxy (nginx/Caddy) with SSL:

```nginx
server {
    listen 443 ssl;
    server_name mcp.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

### API Key Rotation

```bash
# Update .env with new key
nano .env

# Restart services to pick up new key
docker-compose restart mcp-server event-worker
```

---

## Support & Resources

### Documentation
- **V3 Specification**: `.claude-workspace/specs/v3-specification.md`
- **Architecture**: `.claude-workspace/architecture/v3-architecture.md`
- **Monitoring Guide**: `monitoring.md`

### Logs Location
- **Container logs**: `docker-compose logs [service]`
- **Postgres logs**: Inside container at `/var/log/postgresql/`
- **Application logs**: Stdout/stderr captured by Docker

### Health Endpoints
- **MCP Server**: `http://localhost:3001/health`
- **ChromaDB**: `http://localhost:8001/api/v2/heartbeat`
- **PostgreSQL**: Connect via `psql` or health check script

---

**Last Updated**: 2025-12-27
**Version**: 3.0
**Maintainer**: MCP Memory Team
