# MCP Memory - Deployment Configuration

This directory contains all deployment configuration for the MCP Memory system.

## Quick Start

### Development
```bash
make dev
```

### Production
```bash
# 1. Configure environment
cp .env.production.example .env.production
nano .env.production

# 2. Start services
make prod

# 3. Verify
make health
```

## Directory Structure

```
deployment/
├── README.md                        # This file
├── deployment-guide.md              # Complete deployment documentation
├── docker-compose.prod.yml          # Production configuration
├── docker-compose.dev.yml           # Development configuration
├── .env.production.example          # Example production environment
├── .env.production                  # Production environment (not in git)
├── .env.development                 # Development environment
├── Makefile                         # Common operations
├── scripts/
│   ├── backup.sh                    # Backup ChromaDB data
│   ├── restore.sh                   # Restore from backup
│   └── health-check.sh              # Health check all services
├── monitoring/
│   ├── README.md                    # Monitoring documentation
│   └── prometheus.yml               # Prometheus config (future)
└── secrets/                         # Secrets (not in git, create manually)
    ├── api_key.txt
    ├── chroma_credentials.txt
    └── certs/
        ├── chroma-cert.pem
        └── chroma-key.pem
```

## Available Commands

Run `make help` to see all available commands:

```bash
make help          # Show all commands
make dev           # Start development environment
make prod          # Start production environment
make stop          # Stop all services
make logs          # View logs
make backup        # Backup data
make restore       # Restore from backup
make health        # Check service health
make clean         # Clean up everything
```

## Documentation

- **[Deployment Guide](deployment-guide.md)** - Complete deployment instructions
- **[Monitoring README](monitoring/README.md)** - Monitoring and observability

## Configuration Files

### docker-compose.prod.yml

Production-ready Docker Compose configuration with:
- Resource limits (CPU, memory)
- Security hardening (non-root, read-only, capabilities)
- Health checks on all services
- Restart policies
- Logging configuration
- Named volumes for persistence

### docker-compose.dev.yml

Development-optimized configuration with:
- Hot reload support (volume mounts)
- Debug logging
- Exposed ports for debugging
- Python debugger support (debugpy)

### .env.production.example

Template for production environment variables with:
- Memory policy configuration
- Logging settings
- Security options
- Rate limiting
- Backup configuration
- Comprehensive documentation

### Makefile

Common operations for:
- Starting/stopping environments
- Building images
- Viewing logs
- Running tests
- Backup/restore
- Health checks
- Resource monitoring

## Services

### ChromaDB
- **Purpose:** Vector database for persistent memory storage
- **Image:** `chromadb/chroma:latest`
- **Port:** 8000 (internal only in production)
- **Volume:** `mcp_memory_chroma_data_prod`

### chroma-mcp
- **Purpose:** MCP gateway to ChromaDB
- **Image:** `ghcr.io/chroma-core/chroma-mcp:latest`
- **Dependencies:** ChromaDB (healthy)

### agent-app
- **Purpose:** LLM agent application
- **Build:** `../implementation/agent-app/Dockerfile`
- **Dependencies:** ChromaDB (healthy), chroma-mcp (started)
- **Configuration:** `.env.production` or `.env.development`

## Security

### Default Security Features (V1)

- ✅ Non-root user (uid/gid 1000)
- ✅ Read-only root filesystem
- ✅ No new privileges
- ✅ Dropped capabilities
- ✅ AppArmor/SELinux profiles
- ✅ Resource limits
- ✅ No exposed ports in production
- ✅ Log rotation

### Optional Security Features (V2)

- ⏳ TLS/HTTPS encryption
- ⏳ Service authentication
- ⏳ Encryption at rest
- ⏳ Rate limiting
- ⏳ Input validation
- ⏳ Security event logging

See [Security Recommendations](../security/security-recommendations.md) for implementation details.

## Backup and Recovery

### Manual Backup
```bash
make backup
```

### Automated Backup
```bash
# Add to crontab
crontab -e

# Daily backup at 2 AM
0 2 * * * cd /opt/mcp-memory/deployment && make backup >> /var/log/mcp-backup.log 2>&1
```

### Restore
```bash
make restore
```

### Backup Location

Default: `/tmp/mcp-memory-backups`

Override with:
```bash
export BACKUP_DIR=/data/backups/mcp-memory
make backup
```

## Monitoring

### Health Checks
```bash
# Automated health check
make health

# Or directly
./scripts/health-check.sh
```

### Logs
```bash
# All services
make logs

# Specific service
make logs-chroma
make logs-agent
```

### Resources
```bash
make resources
```

### Future: Prometheus + Grafana

See [monitoring/README.md](monitoring/README.md) for planned observability stack.

## Troubleshooting

### Services Won't Start
```bash
# Check logs
make logs

# Check configuration
docker-compose -f docker-compose.prod.yml config

# Check resource availability
docker system df
```

### Health Check Failing
```bash
# Check specific service
docker logs chroma-prod

# Test endpoint
docker exec chroma-prod curl http://localhost:8000/api/v1/heartbeat
```

### Performance Issues
```bash
# Check resource usage
make resources

# Increase resource limits in docker-compose.prod.yml
```

See [Deployment Guide](deployment-guide.md) for detailed troubleshooting.

## Architecture

### Network Topology

```
┌─────────────────────────────────────────┐
│         mcp-memory-network              │
│              (bridge)                   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │       ChromaDB Service          │   │
│  │  - Vector database              │   │
│  │  - Port: 8000 (internal)        │   │
│  │  - Volume: chroma_data          │   │
│  └──────────┬──────────────────────┘   │
│             │                           │
│  ┌──────────▼──────────────────────┐   │
│  │      chroma-mcp Service         │   │
│  │  - MCP gateway                  │   │
│  │  - Depends on: chroma           │   │
│  └──────────┬──────────────────────┘   │
│             │                           │
│  ┌──────────▼──────────────────────┐   │
│  │      agent-app Service          │   │
│  │  - LLM agent                    │   │
│  │  - Depends on: chroma, mcp      │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

### Data Flow

```
1. Agent App → Memory Gateway → HTTP Request → ChromaDB
2. ChromaDB → Vector Search → Results → Agent App
3. Agent App → Build Context → Present to LLM
```

## Environment Comparison

| Feature | Development | Production |
|---------|------------|------------|
| Ports exposed | Yes (8000) | No |
| Hot reload | Yes | No |
| Debug logging | Yes | No |
| Resource limits | No | Yes |
| Security hardening | Minimal | Full |
| Volume mounts | Code dirs | Data only |
| Restart policy | unless-stopped | unless-stopped |
| Rate limiting | Disabled | Enabled |

## Deployment Checklist

Before production deployment:

- [ ] Server meets requirements (CPU, RAM, disk)
- [ ] Docker and Docker Compose installed
- [ ] `.env.production` configured
- [ ] Secrets created (if using auth)
- [ ] TLS certificates ready (if using HTTPS)
- [ ] Firewall configured
- [ ] Backups scheduled
- [ ] Monitoring configured
- [ ] Health checks working
- [ ] Documentation reviewed
- [ ] Team trained on operations

## Support

For detailed documentation, see:
- [Deployment Guide](deployment-guide.md)
- [Security Recommendations](../security/security-recommendations.md)
- [Monitoring README](monitoring/README.md)

For help:
```bash
make help
```

---

**Version:** 1.0.0
**Last Updated:** 2025-12-25
