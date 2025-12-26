# MCP Memory V1 - Quick Start Card

## 30-Second Start (Development)

```bash
cd .claude-workspace/deployment
make dev
```

That's it! Services are running.

## Verify Everything Works

```bash
make health
```

## Common Commands

```bash
make logs          # View logs
make backup        # Backup data
make restore       # Restore data
make stop          # Stop services
```

## Production Deployment

```bash
# 1. Configure
cp .env.production.example .env.production
nano .env.production

# 2. Start
make prod

# 3. Verify
make health

# 4. Automated backups
crontab -e
# Add: 0 2 * * * cd /opt/mcp-memory/deployment && make backup
```

## Troubleshooting

```bash
# Services won't start?
make logs

# Check configuration
docker-compose -f docker-compose.prod.yml config

# Clean everything
make clean
```

## Access Services (Development)

- **ChromaDB:** http://localhost:8000
- **Health:** http://localhost:8000/api/v1/heartbeat

## Production Notes

- No ports exposed (internal only)
- Access via: `docker exec chroma-prod curl http://localhost:8000/api/v1/heartbeat`

## Full Documentation

- **Quick Ref:** [README.md](README.md)
- **Complete Guide:** [deployment-guide.md](deployment-guide.md)
- **Summary:** [DEPLOYMENT-SUMMARY.md](DEPLOYMENT-SUMMARY.md)

## Help

```bash
make help
```

---

**TIP:** Run `make health` regularly to ensure services are healthy.

**TIP:** Setup automated backups on day one: `make backup` + cron

**TIP:** Review [deployment-guide.md](deployment-guide.md) before production deployment.
