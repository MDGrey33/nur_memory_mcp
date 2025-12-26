# MCP Memory - Deployment Guide

**Version:** 1.0.0
**Date:** 2025-12-25
**Environment:** Docker Compose on Single Host

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Local Development Setup](#local-development-setup)
4. [Production Deployment](#production-deployment)
5. [Configuration](#configuration)
6. [Monitoring and Maintenance](#monitoring-and-maintenance)
7. [Backup and Recovery](#backup-and-recovery)
8. [Troubleshooting](#troubleshooting)
9. [Security Hardening](#security-hardening)
10. [Rollback Procedures](#rollback-procedures)

---

## Prerequisites

### System Requirements

**Minimum:**
- CPU: 2 cores
- RAM: 4 GB
- Disk: 20 GB available
- OS: Linux, macOS, or Windows with WSL2

**Recommended (Production):**
- CPU: 4 cores
- RAM: 8 GB
- Disk: 50 GB available (more for large memory storage)
- OS: Linux (Ubuntu 22.04 LTS or similar)

### Software Requirements

1. **Docker Engine** (20.10+)
   ```bash
   docker --version
   # Should output: Docker version 20.10.0 or higher
   ```

2. **Docker Compose** (2.0+)
   ```bash
   docker-compose --version
   # Should output: Docker Compose version 2.0.0 or higher
   ```

3. **Make** (optional but recommended)
   ```bash
   make --version
   ```

4. **Git** (for cloning repository)
   ```bash
   git --version
   ```

### Installation Guides

**Ubuntu/Debian:**
```bash
# Update package index
sudo apt-get update

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt-get install docker-compose-plugin

# Install Make
sudo apt-get install make

# Log out and back in for group changes to take effect
```

**macOS:**
```bash
# Install Docker Desktop
# Download from: https://www.docker.com/products/docker-desktop

# Install Make (via Xcode Command Line Tools)
xcode-select --install
```

**Windows (WSL2):**
```powershell
# Install WSL2
wsl --install

# Install Docker Desktop for Windows
# Download from: https://www.docker.com/products/docker-desktop

# Make sure "Use the WSL 2 based engine" is enabled in Docker Desktop settings
```

---

## Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd mcp_memory/.claude-workspace/deployment
```

### 2. Start Development Environment

```bash
# Using Makefile (recommended)
make dev

# Or using docker-compose directly
docker-compose -f docker-compose.dev.yml up -d
```

### 3. Verify Services

```bash
# Check service status
make status

# Run health checks
make health

# View logs
make logs
```

### 4. Access Services

- **ChromaDB API:** http://localhost:8000 (development only)
- **ChromaDB Heartbeat:** http://localhost:8000/api/v1/heartbeat

---

## Local Development Setup

### Step 1: Environment Configuration

The development environment comes with sensible defaults. If you need to customize:

```bash
# Copy example environment file
cp .env.production.example .env.development

# Edit configuration
nano .env.development
```

Key development settings:
```bash
LOG_LEVEL=DEBUG
RATE_LIMITING_ENABLED=false
ENABLE_EXPERIMENTAL_FEATURES=true
```

### Step 2: Build Images (Optional)

For local development with code changes:

```bash
# Build fresh images
make build

# Or with docker-compose
docker-compose -f docker-compose.dev.yml build --no-cache
```

### Step 3: Start Services

```bash
# Start all services
make dev

# Services will start in this order:
# 1. ChromaDB (waits for health check)
# 2. chroma-mcp (depends on ChromaDB)
# 3. agent-app (depends on both)
```

### Step 4: Development Workflow

**View Logs:**
```bash
# All services
make logs

# Specific service
make logs-chroma
make logs-agent
```

**Hot Reload:**

The development environment supports hot reload for the agent-app:

1. Edit files in `../implementation/agent-app/src/`
2. Changes are automatically reflected (if volume mount is enabled)

To enable live editing, uncomment in `docker-compose.dev.yml`:
```yaml
volumes:
  - ../implementation/agent-app/src:/app/src  # Remove :ro flag
```

**Debugging:**

Python debugger support (debugpy):

1. Uncomment the debugpy port in `docker-compose.dev.yml`:
   ```yaml
   ports:
     - "5678:5678"
   ```

2. Uncomment the debug command:
   ```yaml
   command: python -m debugpy --listen 0.0.0.0:5678 --wait-for-client -m src.app
   ```

3. Attach your IDE debugger to `localhost:5678`

**Run Tests:**
```bash
make test
```

**Access Container Shell:**
```bash
# ChromaDB container
make shell-chroma

# Agent app container
make shell-agent
```

### Step 5: Stop Development Environment

```bash
# Stop services (preserves volumes)
make stop

# Stop and remove everything including data
make clean
```

---

## Production Deployment

### Step 1: Pre-Deployment Checklist

- [ ] Server meets minimum requirements
- [ ] Docker and Docker Compose installed
- [ ] Firewall configured (only necessary ports open)
- [ ] SSL certificates ready (if using HTTPS)
- [ ] Backup storage configured
- [ ] Monitoring tools ready

### Step 2: Initial Configuration

```bash
# Navigate to deployment directory
cd /opt/mcp-memory/deployment

# Copy and configure production environment
cp .env.production.example .env.production
chmod 600 .env.production

# Edit configuration
nano .env.production
```

**Critical Production Settings:**

```bash
# Logging (production level)
LOG_LEVEL=INFO
LOG_FORMAT=json

# Security
RATE_LIMITING_ENABLED=true

# Performance
MEMORY_CONFIDENCE_MIN=0.7
HISTORY_TAIL_N=16

# Environment
ENVIRONMENT=production
```

### Step 3: Security Setup (Optional but Recommended)

**Create secrets directory:**
```bash
mkdir -p secrets/certs
chmod 700 secrets
```

**Generate API keys:**
```bash
# Generate service API key
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/api_key.txt
chmod 600 secrets/api_key.txt
```

**Generate TLS certificates:**
```bash
# Self-signed certificate (development/testing)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout secrets/certs/chroma-key.pem \
  -out secrets/certs/chroma-cert.pem \
  -subj "/CN=chroma/O=MCPMemory"

# Production: Use Let's Encrypt or your certificate provider
```

**Enable authentication in docker-compose.prod.yml:**

Uncomment the following sections:
```yaml
services:
  chroma:
    environment:
      - CHROMA_SERVER_AUTHN_ENABLED=true
      - CHROMA_SERVER_AUTHN_CREDENTIALS_FILE=/run/secrets/chroma_credentials
    secrets:
      - chroma_credentials

  agent-app:
    secrets:
      - api_key

secrets:
  api_key:
    file: ./secrets/api_key.txt
  chroma_credentials:
    file: ./secrets/chroma_credentials.txt
```

### Step 4: Build Production Images

```bash
# Build optimized production images
make build-prod
```

### Step 5: Start Production Services

```bash
# Start production environment
make prod

# Verify all services are healthy
make health

# Check logs for any errors
make logs
```

### Step 6: Verify Deployment

```bash
# Run health check script
./scripts/health-check.sh

# Test ChromaDB connection (from inside container)
docker exec chroma-prod curl -s http://localhost:8000/api/v1/heartbeat

# Expected output: {"nanosecond heartbeat": <timestamp>}
```

### Step 7: Configure Monitoring

See [Monitoring and Maintenance](#monitoring-and-maintenance) section.

### Step 8: Setup Automated Backups

```bash
# Test backup manually
make backup

# Configure cron job for automated backups
crontab -e

# Add this line for daily backups at 2 AM
0 2 * * * cd /opt/mcp-memory/deployment && make backup >> /var/log/mcp-backup.log 2>&1
```

---

## Configuration

### Environment Variables

All configuration is managed through environment variables in `.env.production` or `.env.development`.

#### Service Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_ENDPOINT` | `chroma` | ChromaDB service hostname |
| `VERSION` | `latest` | Docker image version tag |

#### Memory Policy

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_CONFIDENCE_MIN` | `0.7` | Minimum confidence for recalled memories (0.0-1.0) |
| `HISTORY_TAIL_N` | `16` | Number of recent messages in context |
| `MEMORY_TOP_K` | `8` | Number of memories to retrieve |
| `MEMORY_MAX_PER_WINDOW` | `3` | Max memories per context window |

#### Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `LOG_FORMAT` | `json` | Log format (json or text) |
| `LOG_OUTPUT` | `stdout` | Log destination |

#### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMITING_ENABLED` | `true` | Enable rate limiting |
| `RATE_LIMIT_APPEND_HISTORY` | `100` | Max append_history requests per minute |
| `RATE_LIMIT_WRITE_MEMORY` | `10` | Max write_memory requests per minute |
| `RATE_LIMIT_RECALL_MEMORY` | `50` | Max recall_memory requests per minute |

#### Backup

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_DIR` | `/tmp/mcp-memory-backups` | Backup storage location |
| `BACKUP_RETENTION_DAYS` | `30` | Days to keep backups |

### Docker Compose Configuration

#### Resource Limits

Edit `docker-compose.prod.yml` to adjust resource limits:

```yaml
services:
  chroma:
    deploy:
      resources:
        limits:
          cpus: '2.0'      # Maximum CPU cores
          memory: 2G       # Maximum RAM
        reservations:
          cpus: '1.0'      # Guaranteed CPU cores
          memory: 1G       # Guaranteed RAM
```

#### Network Configuration

By default, services use a private bridge network. No ports are exposed in production.

To expose ports for debugging (NOT RECOMMENDED FOR PRODUCTION):
```yaml
services:
  chroma:
    ports:
      - "127.0.0.1:8000:8000"  # Bind to localhost only
```

---

## Monitoring and Maintenance

### Health Checks

**Automated Health Checks:**

Docker Compose includes built-in health checks:

```yaml
healthcheck:
  test: ["CMD", "wget", "-qO-", "http://localhost:8000/api/v1/heartbeat"]
  interval: 30s
  timeout: 10s
  retries: 5
  start_period: 10s
```

**Manual Health Checks:**

```bash
# Run full health check
make health

# Or directly
./scripts/health-check.sh
```

### Viewing Logs

**Real-time Logs:**
```bash
# All services
make logs

# Specific service
docker logs -f chroma-prod
docker logs -f agent-app-prod
```

**Search Logs:**
```bash
# Find errors in last 24 hours
docker logs --since 24h chroma-prod 2>&1 | grep -i error

# Find specific pattern
docker logs chroma-prod 2>&1 | grep "memory write"
```

**Export Logs:**
```bash
# Export to file
docker logs chroma-prod > chroma-logs-$(date +%Y%m%d).log
```

### Resource Monitoring

**Container Resource Usage:**
```bash
# Real-time stats
make resources

# Or directly
docker stats chroma-prod agent-app-prod chroma-mcp-prod
```

**Volume Usage:**
```bash
# Check volume size
docker run --rm -v mcp_memory_chroma_data_prod:/data alpine du -sh /data
```

**Disk Space:**
```bash
# Check Docker disk usage
docker system df

# Detailed view
docker system df -v
```

### Log Rotation

Docker Compose includes log rotation configuration:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"    # Maximum size of each log file
    max-file: "3"      # Keep 3 log files
```

**Manual Log Cleanup:**
```bash
# Truncate logs
truncate -s 0 $(docker inspect --format='{{.LogPath}}' chroma-prod)
```

### Maintenance Tasks

**Weekly:**
- Review logs for errors
- Check disk space
- Verify backups are running

**Monthly:**
- Update Docker images
- Review resource usage
- Clean up old backups

**Quarterly:**
- Security audit
- Performance review
- Update documentation

---

## Backup and Recovery

### Backup Strategy

**What is Backed Up:**
- ChromaDB data volume (contains all conversation history and memories)

**What is NOT Backed Up:**
- Application code (in version control)
- Configuration files (in version control)
- Docker images (rebuillable)

### Creating Backups

**Manual Backup:**
```bash
# Using Makefile
make backup

# Or directly
./scripts/backup.sh
```

**Automated Backups:**

Add to crontab:
```bash
# Edit crontab
crontab -e

# Daily backup at 2 AM
0 2 * * * cd /opt/mcp-memory/deployment && make backup >> /var/log/mcp-backup.log 2>&1

# Weekly backup on Sunday at 3 AM
0 3 * * 0 cd /opt/mcp-memory/deployment && make backup >> /var/log/mcp-backup.log 2>&1
```

**Backup Location:**

Default: `/tmp/mcp-memory-backups`

Change by setting environment variable:
```bash
export BACKUP_DIR=/data/backups/mcp-memory
make backup
```

**Backup Retention:**

Default: 30 days

Change by setting environment variable:
```bash
export BACKUP_RETENTION_DAYS=60
make backup
```

### Restoring from Backup

**Interactive Restore:**
```bash
# Using Makefile
make restore

# Or directly
./scripts/restore.sh
```

The script will:
1. Show available backups
2. Ask which backup to restore
3. Ask which environment to restore to (dev/prod)
4. Confirm before proceeding
5. Stop services, restore data, restart services

**Automated Restore:**
```bash
# For automation, use the restore script with parameters
export BACKUP_FILE=/tmp/mcp-memory-backups/chroma_backup_production_20250101_020000.tar.gz
./scripts/restore.sh <<EOF
1
prod
yes
EOF
```

### Disaster Recovery

**Complete System Failure:**

1. **Provision new server** (meet minimum requirements)

2. **Install prerequisites:**
   ```bash
   # Docker, Docker Compose, etc.
   ```

3. **Clone repository:**
   ```bash
   git clone <repository-url>
   cd mcp_memory/.claude-workspace/deployment
   ```

4. **Copy backup files** to new server:
   ```bash
   scp -r /tmp/mcp-memory-backups user@new-server:/tmp/
   ```

5. **Restore configuration:**
   ```bash
   # Recreate .env.production from documentation or backup
   cp .env.production.example .env.production
   nano .env.production
   ```

6. **Restore data:**
   ```bash
   make restore
   ```

7. **Verify services:**
   ```bash
   make health
   ```

**Recovery Time Objective (RTO):** 30 minutes to 2 hours (depending on data size)

**Recovery Point Objective (RPO):** 24 hours (with daily backups)

---

## Troubleshooting

### Common Issues

#### 1. Services Won't Start

**Symptom:** `docker-compose up` fails or containers exit immediately

**Diagnosis:**
```bash
# Check logs
make logs

# Check specific container
docker logs chroma-prod

# Check container status
docker ps -a
```

**Common Causes:**
- Port already in use
- Insufficient resources
- Volume permission issues
- Configuration errors

**Solutions:**
```bash
# Stop conflicting services
sudo lsof -i :8000  # Find what's using port 8000
sudo kill <PID>

# Increase Docker resources (Docker Desktop: Settings > Resources)

# Fix volume permissions
docker run --rm -v mcp_memory_chroma_data_prod:/data alpine chown -R 1000:1000 /data

# Validate configuration
docker-compose -f docker-compose.prod.yml config
```

#### 2. ChromaDB Health Check Failing

**Symptom:** Container starts but health check fails

**Diagnosis:**
```bash
# Check ChromaDB logs
docker logs chroma-prod

# Test endpoint manually
docker exec chroma-prod curl http://localhost:8000/api/v1/heartbeat
```

**Common Causes:**
- ChromaDB still initializing
- Database corruption
- Out of memory

**Solutions:**
```bash
# Wait longer (increase start_period in health check)
# Edit docker-compose.prod.yml:
healthcheck:
  start_period: 30s  # Increase from 10s

# Check memory usage
docker stats chroma-prod

# Restore from backup if corrupted
make restore
```

#### 3. Agent App Can't Connect to ChromaDB

**Symptom:** Agent app logs show connection errors

**Diagnosis:**
```bash
# Check network connectivity
docker exec agent-app-prod ping chroma

# Verify ChromaDB is accessible
docker exec agent-app-prod curl http://chroma:8000/api/v1/heartbeat

# Check DNS resolution
docker exec agent-app-prod nslookup chroma
```

**Common Causes:**
- Services not on same network
- ChromaDB not started yet
- Wrong endpoint configuration

**Solutions:**
```bash
# Verify network configuration
docker network inspect mcp-memory-prod-network

# Ensure depends_on is configured correctly
# Edit docker-compose.prod.yml to ensure:
depends_on:
  chroma:
    condition: service_healthy

# Check MCP_ENDPOINT in .env.production
echo $MCP_ENDPOINT  # Should be "chroma"
```

#### 4. Out of Disk Space

**Symptom:** Errors about "no space left on device"

**Diagnosis:**
```bash
# Check disk usage
df -h

# Check Docker usage
docker system df

# Check volume size
docker run --rm -v mcp_memory_chroma_data_prod:/data alpine du -sh /data
```

**Solutions:**
```bash
# Clean up Docker resources
docker system prune -a

# Remove old images
docker image prune -a

# Move volume to larger disk (see data migration below)

# Increase disk size on host
```

#### 5. Slow Performance

**Symptom:** Queries taking too long, high latency

**Diagnosis:**
```bash
# Check resource usage
docker stats

# Check ChromaDB logs for slow queries
docker logs chroma-prod | grep -i "slow"

# Check memory configuration
docker inspect chroma-prod | grep -i memory
```

**Solutions:**
```bash
# Increase resource limits in docker-compose.prod.yml
deploy:
  resources:
    limits:
      cpus: '4.0'
      memory: 4G

# Tune memory policy in .env.production
MEMORY_TOP_K=5  # Reduce from 8
MEMORY_CONFIDENCE_MIN=0.8  # Increase from 0.7

# Restart services
make restart
```

### Advanced Troubleshooting

#### Enable Debug Logging

```bash
# Edit .env.production
LOG_LEVEL=DEBUG

# Restart services
make restart

# View detailed logs
make logs
```

#### Container Shell Access

```bash
# ChromaDB container
docker exec -it chroma-prod /bin/sh

# Agent app container
docker exec -it agent-app-prod /bin/bash

# Run diagnostic commands
ps aux
netstat -tuln
df -h
```

#### Network Diagnostics

```bash
# Inspect network
docker network inspect mcp-memory-prod-network

# Check connectivity between containers
docker exec agent-app-prod ping chroma
docker exec agent-app-prod curl http://chroma:8000/api/v1/heartbeat
```

#### Data Recovery

If data is corrupted:

```bash
# 1. Stop services
make stop

# 2. Backup current (possibly corrupted) data
docker run --rm -v mcp_memory_chroma_data_prod:/data -v /tmp:/backup alpine tar czf /backup/corrupted-data.tar.gz -C /data .

# 3. Restore from known good backup
make restore

# 4. If no backup available, try to repair
# (ChromaDB doesn't have built-in repair tools, contact support)
```

---

## Security Hardening

### Immediate Actions (Before Production)

#### 1. Remove Exposed Ports

In `docker-compose.prod.yml`, ensure no ports are exposed:

```yaml
services:
  chroma:
    # ports:  # COMMENTED OUT
    #   - "8000:8000"
```

#### 2. Use Non-Root User

Already configured in `docker-compose.prod.yml`:

```yaml
services:
  chroma:
    user: "1000:1000"
```

#### 3. Enable Security Options

Already configured:

```yaml
security_opt:
  - no-new-privileges:true
  - apparmor:docker-default
cap_drop:
  - ALL
```

#### 4. Set Resource Limits

Already configured:

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 2G
```

### Additional Security Measures

#### Enable TLS/HTTPS

**Generate Certificates:**
```bash
# Self-signed (development/testing)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout secrets/certs/chroma-key.pem \
  -out secrets/certs/chroma-cert.pem \
  -subj "/CN=chroma/O=MCPMemory"

# Production: Use Let's Encrypt
certbot certonly --standalone -d your-domain.com
cp /etc/letsencrypt/live/your-domain.com/fullchain.pem secrets/certs/chroma-cert.pem
cp /etc/letsencrypt/live/your-domain.com/privkey.pem secrets/certs/chroma-key.pem
```

**Enable in docker-compose.prod.yml:**
```yaml
services:
  chroma:
    environment:
      - CHROMA_SERVER_SSL_ENABLED=true
      - CHROMA_SERVER_SSL_CERTFILE=/secrets/certs/chroma-cert.pem
      - CHROMA_SERVER_SSL_KEYFILE=/secrets/certs/chroma-key.pem
    volumes:
      - ./secrets/certs:/secrets/certs:ro
```

**Update agent-app:**
```bash
# In .env.production
CHROMA_HTTP_PROTOCOL=https
```

#### Enable Authentication

**Create credentials:**
```bash
# Generate API key
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/api_key.txt

# Create ChromaDB credentials file
cat > secrets/chroma_credentials.txt <<EOF
admin:$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
EOF

chmod 600 secrets/*.txt
```

**Enable in docker-compose.prod.yml:**

Uncomment authentication sections (already prepared in the file).

#### Firewall Configuration

```bash
# Ubuntu/Debian with ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw enable

# Only open ports if absolutely necessary (NOT RECOMMENDED)
# sudo ufw allow 8000/tcp  # ChromaDB (DON'T DO THIS)
```

#### Regular Security Updates

```bash
# Update Docker images regularly
docker-compose -f docker-compose.prod.yml pull
make restart

# Update host system
sudo apt-get update && sudo apt-get upgrade
```

### Security Checklist

Before going to production:

- [ ] No ports exposed publicly
- [ ] TLS/HTTPS enabled
- [ ] Authentication enabled
- [ ] Non-root user configured
- [ ] Security options enabled
- [ ] Resource limits set
- [ ] Firewall configured
- [ ] Secrets stored securely (not in git)
- [ ] Regular backups scheduled
- [ ] Monitoring configured
- [ ] Log rotation enabled
- [ ] Docker images up to date

---

## Rollback Procedures

### Rollback Scenarios

#### 1. Bad Configuration Change

**Symptom:** Services fail after configuration update

**Rollback:**
```bash
# Restore previous .env.production from backup
cp .env.production.backup .env.production

# Restart services
make restart

# Verify
make health
```

#### 2. Failed Docker Image Update

**Symptom:** New image version causes failures

**Rollback:**
```bash
# Stop current version
make stop

# Edit docker-compose.prod.yml to use previous version
# Change: image: mcp-memory-agent:1.1.0
# To:     image: mcp-memory-agent:1.0.0

# Or set VERSION in .env.production
VERSION=1.0.0

# Restart
make prod

# Verify
make health
```

#### 3. Data Corruption

**Symptom:** Database errors, crashes, or incorrect data

**Rollback:**
```bash
# Stop services
make stop

# Restore from last known good backup
make restore

# Select appropriate backup when prompted

# Verify
make health
```

#### 4. Complete System Failure

See [Disaster Recovery](#disaster-recovery) section above.

### Rollback Testing

Test rollback procedures in development:

```bash
# 1. Create a known good state
make backup

# 2. Make changes
# ... modify configuration, update images, etc.

# 3. Test rollback
make restore

# 4. Verify everything works
make health
```

### Rollback Checklist

Before any production change:

- [ ] Create backup
- [ ] Document current state
- [ ] Have rollback plan ready
- [ ] Test in development first
- [ ] Schedule maintenance window
- [ ] Have team available
- [ ] Monitor after deployment

---

## Appendix

### A. Makefile Commands Reference

| Command | Description |
|---------|-------------|
| `make help` | Show all available commands |
| `make dev` | Start development environment |
| `make prod` | Start production environment |
| `make build` | Build development images |
| `make build-prod` | Build production images |
| `make stop` | Stop all services |
| `make restart` | Restart services |
| `make logs` | View all logs |
| `make logs-chroma` | View ChromaDB logs |
| `make logs-agent` | View agent-app logs |
| `make test` | Run tests |
| `make backup` | Create data backup |
| `make restore` | Restore from backup |
| `make clean` | Remove all containers and volumes |
| `make status` | Show service status |
| `make health` | Run health checks |
| `make shell-chroma` | Open shell in ChromaDB |
| `make shell-agent` | Open shell in agent-app |
| `make resources` | Show resource usage |
| `make prune` | Clean up Docker resources |

### B. Environment Variables Reference

See [Configuration](#configuration) section.

### C. Port Reference

**Development:**
- 8000: ChromaDB HTTP API
- 8080: Agent app HTTP API (if enabled)
- 5678: Python debugger (if enabled)

**Production:**
- No ports exposed externally

### D. Volume Reference

**Development:**
- `mcp_memory_chroma_data_dev`: ChromaDB data

**Production:**
- `mcp_memory_chroma_data_prod`: ChromaDB data

### E. Network Reference

**Development:**
- `mcp-memory-dev-network`: Bridge network for all services

**Production:**
- `mcp-memory-prod-network`: Bridge network for all services

### F. File Structure

```
deployment/
├── docker-compose.prod.yml          # Production compose file
├── docker-compose.dev.yml           # Development compose file
├── .env.production.example          # Example production config
├── .env.production                  # Production config (not in git)
├── .env.development                 # Development config
├── Makefile                         # Common operations
├── deployment-guide.md              # This file
├── secrets/                         # Secrets directory (not in git)
│   ├── api_key.txt
│   ├── chroma_credentials.txt
│   └── certs/
│       ├── chroma-cert.pem
│       └── chroma-key.pem
├── scripts/
│   ├── backup.sh                    # Backup script
│   ├── restore.sh                   # Restore script
│   └── health-check.sh              # Health check script
└── monitoring/
    └── prometheus.yml               # Prometheus config (future)
```

### G. Additional Resources

- **Docker Documentation:** https://docs.docker.com/
- **Docker Compose:** https://docs.docker.com/compose/
- **ChromaDB Documentation:** https://docs.trychroma.com/
- **MCP Protocol:** https://modelcontextprotocol.io/

---

## Support and Contact

For issues and questions:

1. Check this deployment guide
2. Review logs: `make logs`
3. Run health checks: `make health`
4. Check troubleshooting section
5. Contact development team

---

**Document Version:** 1.0.0
**Last Updated:** 2025-12-25
**Next Review:** 2026-01-25
