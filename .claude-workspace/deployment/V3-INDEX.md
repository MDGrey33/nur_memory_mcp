# MCP Memory Server V3: Deployment Files Index

**Version:** 3.0
**Date:** 2025-12-27
**Status:** Production Ready

---

## Quick Navigation

| If you want to... | Read this file |
|-------------------|----------------|
| **Get started quickly** | [V3-README.md](V3-README.md) |
| **Deploy to production** | [deploy.md](deploy.md) |
| **Set up monitoring** | [monitoring.md](monitoring.md) |
| **Understand what was delivered** | [V3-DEPLOYMENT-SUMMARY.md](V3-DEPLOYMENT-SUMMARY.md) |
| **Validate your setup** | Run `./validate-deployment.sh` |

---

## Configuration Files

### docker-compose.v3.yml
**Purpose**: Production Docker Compose configuration for V3
**When to use**: Production deployments
**Services**: mcp-server, chroma, postgres, event-worker
**Command**:
```bash
docker compose -f docker-compose.v3.yml up -d
```

### docker-compose.v3.dev.yml
**Purpose**: Development overrides with debugging support
**When to use**: Local development, debugging
**Features**: Hot reload, debug ports, pgAdmin
**Command**:
```bash
docker compose -f docker-compose.v3.yml -f docker-compose.v3.dev.yml up -d
```

### .env.example
**Purpose**: Environment variables template
**Action required**: Copy to `.env` and set `OPENAI_API_KEY`
**Command**:
```bash
cp .env.example .env
nano .env  # Set OPENAI_API_KEY
```

### init.sql
**Purpose**: Database initialization script
**Usage**: Automatically runs on first Postgres startup
**Tables created**: artifact_revision, event_jobs, semantic_event, event_evidence
**Features**: Idempotent (can run multiple times safely)

### Dockerfile
**Purpose**: Multi-stage production Dockerfile
**Stages**: base, development, production
**Base image**: python:3.11-slim
**Security**: Non-root user (mcp:mcp)

### healthcheck.py
**Purpose**: Container health check script
**Usage**: Validates service health
**Command**:
```bash
docker compose -f docker-compose.v3.yml exec mcp-server \
  python healthcheck.py --service all
```

---

## Documentation Files

### V3-README.md (Quick Reference)
**Length**: ~10 pages
**Content**:
- Quick start guide
- Architecture overview
- Common commands
- Environment variables reference
- Troubleshooting quick tips

**When to use**: First time setup, daily operations

### deploy.md (Comprehensive Guide)
**Length**: ~25 pages
**Content**:
- Prerequisites
- Detailed setup instructions
- Configuration options
- Deployment verification
- Scaling strategies
- Backup & restore procedures
- Comprehensive troubleshooting
- Maintenance tasks
- Security considerations

**When to use**: Production deployment, detailed reference

### monitoring.md (Observability Guide)
**Length**: ~20 pages
**Content**:
- Key metrics to track
- Alerting thresholds
- Log aggregation setup
- Monitoring stack setup (Prometheus, Grafana, ELK)
- Dashboard examples
- Performance tuning
- Custom monitoring scripts

**When to use**: Setting up production monitoring, performance optimization

### V3-DEPLOYMENT-SUMMARY.md (Executive Summary)
**Length**: ~8 pages
**Content**:
- What was delivered
- Architecture overview
- Configuration details
- Database schema
- Deployment workflows
- Testing procedures
- Migration from V2

**When to use**: Understanding the complete deployment package

### V3-INDEX.md (This File)
**Purpose**: Navigation guide for all deployment files
**When to use**: Finding the right documentation

---

## Scripts

### validate-deployment.sh
**Purpose**: Validate deployment setup
**Checks**:
- All required files present
- File content validation
- Docker installed
- Docker Compose syntax
- Dockerfile structure
- Database schema completeness

**Usage**:
```bash
chmod +x validate-deployment.sh
./validate-deployment.sh
```

**Exit codes**:
- 0: All checks passed
- 1: Some checks failed

---

## Architecture Reference

### V3 Container Stack

```
┌──────────────────────────────────────────────────────────────┐
│                   V3 DOCKER COMPOSE STACK                     │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  mcp-server  │  │    chroma    │  │   postgres   │       │
│  │  Port: 3000  │  │  Port: 8001  │  │  Port: 5432  │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                 │               │
│         └─────────────────┼─────────────────┘               │
│                           │                                 │
│  ┌────────────────────────┼──────────────────┐              │
│  │     event-worker       │                  │              │
│  │     (Async Extract)    │                  │              │
│  └────────────────────────┴──────────────────┘              │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### File Dependencies

```
docker-compose.v3.yml
├── Requires: .env (for environment variables)
├── Uses: Dockerfile (to build images)
├── Mounts: init.sql (for database initialization)
└── Mounts: healthcheck.py (for health checks)

docker-compose.v3.dev.yml
├── Extends: docker-compose.v3.yml
├── Mounts: src/ directory (hot reload)
└── Adds: pgAdmin service
```

---

## Deployment Workflow

### 1. Pre-Deployment

```bash
# Validate setup
./validate-deployment.sh

# Review configuration
cat .env.example
cat docker-compose.v3.yml
```

### 2. Initial Deployment

```bash
# Copy environment template
cp .env.example .env

# Set OPENAI_API_KEY
nano .env

# Start services
docker compose -f docker-compose.v3.yml up -d

# Verify health
docker compose -f docker-compose.v3.yml exec mcp-server \
  python healthcheck.py --service all
```

### 3. Post-Deployment

```bash
# Check logs
docker compose -f docker-compose.v3.yml logs -f

# Test connectivity
curl http://localhost:3000/health

# Configure MCP client (see V3-README.md)
```

---

## File Statistics

| File | Lines | Size | Description |
|------|-------|------|-------------|
| docker-compose.v3.yml | 188 | 5.0 KB | Production config |
| docker-compose.v3.dev.yml | 85 | 2.3 KB | Dev overrides |
| .env.example | 146 | 4.7 KB | Env template |
| init.sql | 278 | 8.6 KB | DB init |
| Dockerfile | 84 | 2.3 KB | Multi-stage build |
| healthcheck.py | 217 | 6.3 KB | Health checks |
| validate-deployment.sh | 212 | 6.9 KB | Validation script |
| V3-README.md | 551 | 12 KB | Quick reference |
| deploy.md | 727 | 16 KB | Full guide |
| monitoring.md | 737 | 17 KB | Monitoring guide |
| V3-DEPLOYMENT-SUMMARY.md | 792 | 19 KB | Summary |
| V3-INDEX.md | 238 | 6.8 KB | This file |

**Total**: 4,255 lines, ~107 KB

---

## Getting Help

### Documentation Hierarchy

1. **Quick Start**: V3-README.md (5 min read)
2. **Detailed Setup**: deploy.md (20 min read)
3. **Monitoring**: monitoring.md (15 min read)
4. **Technical Details**: V3-DEPLOYMENT-SUMMARY.md (10 min read)

### Common Tasks

| Task | Command | Documentation |
|------|---------|---------------|
| Start services | `docker compose -f docker-compose.v3.yml up -d` | V3-README.md |
| Check health | `python healthcheck.py --service all` | V3-README.md |
| View logs | `docker compose logs -f` | V3-README.md |
| Backup DB | `pg_dump -U events events > backup.sql` | deploy.md |
| Scale workers | `docker compose up -d --scale event-worker=3` | deploy.md |
| Monitor metrics | See monitoring.md | monitoring.md |
| Troubleshoot | See troubleshooting section | deploy.md |

### Support Resources

- **V3 Specification**: `../specs/v3-specification.md`
- **V3 Architecture**: `../architecture/v3-architecture.md`
- **Implementation**: `../implementation/mcp-server/`

---

## Version History

### V3.0 (2025-12-27)
- Initial V3 deployment configuration
- 4 container architecture (mcp-server, chroma, postgres, event-worker)
- Production-ready with security hardening
- Comprehensive documentation
- Validation script
- Development mode with debugging

---

## Checklist

### Pre-Deployment
- [ ] Read V3-README.md
- [ ] Run `./validate-deployment.sh`
- [ ] Copy `.env.example` to `.env`
- [ ] Set `OPENAI_API_KEY` in `.env`
- [ ] Review `docker-compose.v3.yml`
- [ ] Change `POSTGRES_PASSWORD` for production

### Deployment
- [ ] Run `docker compose -f docker-compose.v3.yml up -d`
- [ ] Wait for health checks (30 seconds)
- [ ] Run health check script
- [ ] Check logs for errors
- [ ] Test MCP endpoint (`curl http://localhost:3000/health`)

### Post-Deployment
- [ ] Configure MCP client (Claude Desktop, etc.)
- [ ] Test document ingestion
- [ ] Verify event extraction
- [ ] Set up monitoring (see monitoring.md)
- [ ] Schedule backups (see deploy.md)
- [ ] Document custom configuration

### Production Hardening
- [ ] Change default Postgres password
- [ ] Enable SSL/TLS for external access
- [ ] Configure firewall rules
- [ ] Set up log aggregation
- [ ] Configure alerting
- [ ] Test backup & restore
- [ ] Create runbooks

---

**Last Updated**: 2025-12-27
**Version**: 3.0
**Maintainer**: MCP Memory Team
