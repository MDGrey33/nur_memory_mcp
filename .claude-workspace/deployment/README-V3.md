# MCP Memory Server V3 - Deployment Package

**Version**: 3.0
**Date**: 2025-12-27
**Status**: ✓ Production Ready

---

## Quick Start (5 minutes)

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Set your OpenAI API key
nano .env
# Add: OPENAI_API_KEY=sk-proj-your-key-here

# 3. Start V3 stack
docker compose -f docker-compose.v3.yml up -d

# 4. Verify deployment
docker compose -f docker-compose.v3.yml exec mcp-server \
  python healthcheck.py --service all

# 5. Configure Claude Desktop
# Edit ~/Library/Application Support/Claude/claude_desktop_config.json
# Add MCP server: http://localhost:3001/mcp/
```

**That's it!** You now have a fully functional V3 deployment with semantic events.

---

## MCP Client Configuration Semantics (Do This Exactly)

This server speaks MCP over **Streamable HTTP** (implemented as a long-lived **SSE** stream).

- **Local (Cursor, dev tools)**:
  - Use: `http://localhost:3001/mcp/`
  - Keep the trailing slash.
- **Claude Desktop / Claude Connectors**:
  - Claude requires **HTTPS**. Use ngrok (or another HTTPS proxy) and configure:
    - `https://<your-domain>/mcp/`
  - Keep the trailing slash.

### `/mcp` vs `/mcp/`

Even if a client is configured with `/mcp/`, some clients may still send requests to `/mcp` (no trailing slash).
This deployment supports that by redirecting **relatively**:

- `POST /mcp` → `307 Location: /mcp/`

This avoids accidental `https → http` downgrades when running behind proxies.

---

## What's Included

### V3 Deployment Files

| File | Purpose |
|------|---------|
| **docker-compose.v3.yml** | Production configuration (4 services) |
| **docker-compose.v3.dev.yml** | Development mode (debugging, hot reload) |
| **.env.example** | Environment variables template |
| **init.sql** | Database initialization (auto-runs) |
| **Dockerfile** | Multi-stage production build |
| **healthcheck.py** | Service health validation |
| **validate-deployment.sh** | Pre-deployment validation |

### Documentation

| File | Read Time | Purpose |
|------|-----------|---------|
| **V3-INDEX.md** | 2 min | Navigate all deployment files |
| **V3-README.md** | 5 min | Quick reference & commands |
| **deploy.md** | 20 min | Comprehensive deployment guide |
| **monitoring.md** | 15 min | Monitoring & observability |
| **V3-DEPLOYMENT-SUMMARY.md** | 10 min | Executive summary |

---

## Architecture

### V3 Stack (4 Containers)

```
┌─────────────────────────────────────────────────────────┐
│                    V3 SERVICES                           │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  mcp-server ──┬──> chroma:8000      (vectors)           │
│   :3000       │                                          │
│               └──> postgres:5432    (events + jobs)     │
│                                                          │
│  event-worker ┬──> chroma:8000      (read artifacts)    │
│   (no ports)  ├──> postgres:5432    (write events)      │
│               └──> openai API       (LLM extraction)    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### What's New in V3

- **Events Database**: PostgreSQL for structured semantic events
- **Event Worker**: Async extraction with LLM (GPT-4o-mini/gpt-4o)
- **Job Queue**: Reliable async processing with retries
- **Immutable Revisions**: Track artifact changes over time
- **Evidence Traceability**: Every event links to exact source text

---

## Common Commands

```bash
# Start services
docker compose -f docker-compose.v3.yml up -d

# Check status
docker compose -f docker-compose.v3.yml ps

# View logs
docker compose -f docker-compose.v3.yml logs -f [service]

# Run health checks
docker compose -f docker-compose.v3.yml exec mcp-server \
  python healthcheck.py --service all

# Stop services
docker compose -f docker-compose.v3.yml down

# Restart specific service
docker compose -f docker-compose.v3.yml restart mcp-server

# Scale workers (for high load)
docker compose -f docker-compose.v3.yml up -d --scale event-worker=3

# Connect to database
docker compose -f docker-compose.v3.yml exec postgres \
  psql -U events -d events

# Backup database
docker compose -f docker-compose.v3.yml exec postgres \
  pg_dump -U events events > backup_$(date +%Y%m%d).sql
```

---

## Development Mode

```bash
# Start with dev overrides (hot reload, debug ports, pgAdmin)
docker compose -f docker-compose.v3.yml -f docker-compose.v3.dev.yml up -d

# Access pgAdmin: http://localhost:5050
#   User: admin@mcp.local
#   Pass: admin

# Attach debugger to:
#   MCP Server: localhost:5678
#   Event Worker: localhost:5679
```

---

## Pre-Deployment Validation

```bash
# Run validation script
./validate-deployment.sh

# Expected output:
# ✓ All checks passed! Ready for deployment.
```

---

## Troubleshooting

### Service won't start
```bash
docker compose -f docker-compose.v3.yml logs [service]
docker compose -f docker-compose.v3.yml restart [service]
```

### Health check fails
```bash
docker compose -f docker-compose.v3.yml ps
docker compose -f docker-compose.v3.yml exec mcp-server \
  python healthcheck.py --service [service-name]
```

### Worker not processing jobs
```bash
# Check worker logs
docker compose -f docker-compose.v3.yml logs event-worker

# Check job queue
docker compose -f docker-compose.v3.yml exec postgres psql -U events -d events -c \
  "SELECT status, COUNT(*) FROM event_jobs GROUP BY status;"
```

### Database connection issues
```bash
# Verify Postgres is running
docker compose -f docker-compose.v3.yml ps postgres

# Test connection
docker compose -f docker-compose.v3.yml exec postgres \
  psql -U events -d events -c "SELECT 1;"
```

**More troubleshooting**: See `deploy.md` comprehensive guide

---

## Documentation Guide

### For First-Time Setup
1. Read **V3-README.md** (5 min)
2. Run `./validate-deployment.sh`
3. Follow Quick Start above
4. Configure MCP client

### For Production Deployment
1. Read **deploy.md** (20 min)
2. Review **Production Checklist** in deploy.md
3. Set up monitoring (see **monitoring.md**)
4. Configure backups

### For Operations & Maintenance
- Daily: Check container health, review logs
- Weekly: Review job queue, run backups
- Monthly: Update images, review metrics
- Reference: **monitoring.md**, **deploy.md**

### For Troubleshooting
1. Check **Troubleshooting** section above
2. Review **deploy.md** troubleshooting section
3. Check service logs
4. Run health checks

---

## Requirements

- **Docker**: 20.10+ with Docker Compose
- **RAM**: 4GB minimum (8GB+ recommended)
- **CPU**: 2 cores minimum (4+ recommended)
- **Disk**: 20GB free space (SSD recommended)
- **OpenAI API Key**: Required

---

## Key Files Reference

| File | When to Use |
|------|-------------|
| **V3-INDEX.md** | Finding documentation |
| **V3-README.md** | Daily operations |
| **deploy.md** | Production deployment |
| **monitoring.md** | Setting up monitoring |
| **V3-DEPLOYMENT-SUMMARY.md** | Understanding deliverables |
| **validate-deployment.sh** | Pre-deployment checks |
| **.env.example** | Configuration template |

---

## Support

### Documentation
- **V3 Specification**: `../specs/v3-specification.md`
- **V3 Architecture**: `../architecture/v3-architecture.md`
- **Implementation**: `../implementation/mcp-server/`

### Health Endpoints
- MCP Server: http://localhost:3001/health
- ChromaDB: http://localhost:8001/api/v2/heartbeat
- PostgreSQL: `psql -U events -d events`

---

## Production Checklist

Before deploying to production:

- [ ] Set strong `POSTGRES_PASSWORD` in `.env`
- [ ] Set `OPENAI_EVENT_MODEL=gpt-4o` for best quality
- [ ] Run `./validate-deployment.sh`
- [ ] Review resource limits in `docker-compose.v3.yml`
- [ ] Set up monitoring (see `monitoring.md`)
- [ ] Configure backup strategy (see `deploy.md`)
- [ ] Test health checks
- [ ] Configure firewall rules
- [ ] Set up log aggregation
- [ ] Configure alerting

---

## Statistics

- **Configuration Files**: 7 files, ~1,000 lines
- **Documentation**: 5 files, ~55 pages
- **Total Package**: ~100 KB, 4,000+ lines
- **Services**: 4 Docker containers
- **Databases**: 4 PostgreSQL tables
- **Resource Usage**: ~7GB RAM, ~3.5 CPU cores (limits)

---

## Version History

### V3.0 (2025-12-27)
- Initial V3 deployment package
- 4-container architecture
- Production-ready configuration
- Comprehensive documentation
- Validation scripts
- Development mode support

---

**Ready to deploy?**

1. Run `./validate-deployment.sh`
2. Copy `.env.example` to `.env`
3. Set `OPENAI_API_KEY`
4. Run `docker compose -f docker-compose.v3.yml up -d`
5. Verify with health checks
6. Configure MCP client
7. Start using semantic events!

**Questions?** See [V3-INDEX.md](V3-INDEX.md) for documentation guide.

---

**Last Updated**: 2025-12-27
**Version**: 3.0
**Status**: ✓ Production Ready
**Maintainer**: MCP Memory DevOps Team
