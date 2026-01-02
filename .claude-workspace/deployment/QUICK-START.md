# MCP Memory Server - Quick Start

## 30-Second Start

```bash
cd .claude-workspace/deployment

# 1. Create secrets file
echo "OPENAI_API_KEY=sk-proj-your-key-here" > .env

# 2. Start production
./scripts/env-up.sh prod

# 3. Verify
./scripts/health-check.sh prod
```

## Configure Claude Code

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "memory": {
      "type": "http",
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

## Test It

Ask Claude:
> "Remember that I prefer Python over JavaScript"

Then later:
> "What do you recall about my preferences?"

## Common Commands

```bash
# Start/Stop
./scripts/env-up.sh prod
./scripts/env-down.sh prod

# Health check
./scripts/health-check.sh prod

# View logs
docker logs mcp-memory-prod-mcp-server-1 -f
```

## Environments

| Environment | MCP URL | Use Case |
|-------------|---------|----------|
| prod | http://localhost:3001/mcp/ | Daily use |
| staging | http://localhost:3101/mcp/ | Pre-release |
| test | http://localhost:3201/mcp/ | Testing |

## Troubleshooting

**Tools not appearing?**
1. Check URL has trailing slash
2. Verify `"type": "http"` in config
3. Run `claude /doctor`
4. Restart Claude

**Connection refused?**
```bash
./scripts/health-check.sh prod
```

## Full Documentation

- [CHEATSHEET.md](CHEATSHEET.md) - Quick reference
- [README.md](README.md) - Deployment guide
- [ENVIRONMENTS.md](ENVIRONMENTS.md) - Environment details
