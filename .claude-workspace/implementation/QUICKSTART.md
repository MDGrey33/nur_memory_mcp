# Chroma MCP Memory V1 - Quick Start Guide

Get the system running in under 5 minutes.

---

## Prerequisites

- Docker (v20+)
- Docker Compose (v2+)
- 2GB free disk space
- Internet connection (to pull images)

---

## Step 1: Navigate to Implementation Directory

```bash
cd "/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation"
```

Or if using the alternate location:

```bash
cd "/Users/roland/code/mcp_memory/.claude-workspace/implementation"
```

---

## Step 2: Verify Files

Check that all required files exist:

```bash
ls -la
```

Expected output:
```
docker-compose.yml
agent-app/
  ├── Dockerfile
  ├── requirements.txt
  ├── .env.example
  ├── README.md
  └── src/
      ├── __init__.py
      ├── app.py
      ├── config.py
      ├── memory_gateway.py
      ├── context_builder.py
      ├── memory_policy.py
      ├── models.py
      ├── exceptions.py
      └── utils.py
```

---

## Step 3: Start the Stack

```bash
docker compose up -d
```

This will:
1. Pull ChromaDB image (~500MB)
2. Pull chroma-mcp image (~200MB)
3. Build agent-app image (~200MB)
4. Start all 3 services
5. Wait for health checks

**Expected time:** 2-5 minutes (first run with image pulls)

---

## Step 4: Verify Services Started

Check service status:

```bash
docker compose ps
```

Expected output:
```
NAME        IMAGE                                    STATUS
chroma      chromadb/chroma:latest                   Up (healthy)
chroma-mcp  ghcr.io/chroma-core/chroma-mcp:latest   Up
agent-app   implementation-agent-app                 Up
```

All services should show "Up" status.

---

## Step 5: View Agent Logs

Watch the agent-app demonstrate the core flows:

```bash
docker compose logs -f agent-app
```

You should see JSON-formatted logs showing:
- Application initialization
- Bootstrap (collection creation)
- Flow 1: Append History (2 messages)
- Flow 2: Write Memory (2 memories)
- Flow 3: Context Build (with retrieved history + memories)
- Flow 4: Rate Limiting Test (5 memory attempts, 3 accepted, 2 rejected)

**Press Ctrl+C to stop following logs**

---

## Step 6: Verify Collections Created

Check that ChromaDB has the collections:

```bash
curl http://localhost:8000/api/v1/collections
```

Expected output:
```json
["history", "memory"]
```

---

## Step 7: Test Persistence

### Restart containers (data should persist):

```bash
docker compose restart
sleep 10
docker compose logs agent-app | tail -20
```

You should see the demonstration run again with existing collections.

### Full teardown and restart:

```bash
docker compose down
docker compose up -d
sleep 15
docker compose logs agent-app | tail -20
```

Data still persists because the `chroma_data` volume is preserved.

---

## Step 8: Inspect the Volume

Check that data is stored in the volume:

```bash
docker volume inspect chroma_data
```

Shows the mount point and creation date.

To see the actual files:

```bash
docker exec chroma ls -la /chroma/chroma
```

Expected output:
```
chroma.sqlite3     # Metadata database
index/             # Vector indices
```

---

## Common Commands

### View all logs
```bash
docker compose logs
```

### View specific service logs
```bash
docker compose logs chroma
docker compose logs chroma-mcp
docker compose logs agent-app
```

### Stop all services
```bash
docker compose down
```

### Stop and remove volume (delete all data)
```bash
docker compose down -v
```

### Rebuild agent-app after code changes
```bash
docker compose up -d --build agent-app
```

### Get into agent-app container
```bash
docker compose exec agent-app bash
```

### Run Python REPL in agent-app
```bash
docker compose exec agent-app python
```

---

## Troubleshooting

### Problem: "Cannot connect to Docker daemon"
**Solution:** Start Docker Desktop or Docker daemon

### Problem: "Port 8000 already in use"
**Solution:** Stop other services using port 8000, or change port in docker-compose.yml

### Problem: "chroma service unhealthy"
**Solution:**
```bash
docker compose logs chroma
docker compose restart chroma
```

### Problem: "agent-app exits immediately"
**Solution:**
```bash
docker compose logs agent-app
```
Check for errors in configuration or Python syntax.

### Problem: "Collections not created"
**Solution:**
```bash
# Check ChromaDB is accessible
curl http://localhost:8000/api/v1/heartbeat

# Restart agent-app
docker compose restart agent-app
```

---

## Customizing Configuration

### Change environment variables:

Edit `docker-compose.yml` under `agent-app` service:

```yaml
environment:
  - MEMORY_CONFIDENCE_MIN=0.8  # Require higher confidence
  - HISTORY_TAIL_N=32          # Retrieve more history
  - MEMORY_TOP_K=16            # Retrieve more memories
  - LOG_LEVEL=DEBUG            # More verbose logging
```

Then restart:

```bash
docker compose up -d agent-app
```

---

## Accessing ChromaDB Directly

### HTTP API

ChromaDB HTTP API is exposed on port 8000:

```bash
# Health check
curl http://localhost:8000/api/v1/heartbeat

# List collections
curl http://localhost:8000/api/v1/collections

# Get documents from history
curl -X POST http://localhost:8000/api/v1/collections/history/get \
  -H "Content-Type: application/json" \
  -d '{"limit": 10}'

# Query memories
curl -X POST http://localhost:8000/api/v1/collections/memory/query \
  -H "Content-Type: application/json" \
  -d '{
    "query_texts": ["Docker memory system"],
    "n_results": 5
  }'
```

---

## Cleanup

### Stop services but keep data
```bash
docker compose down
```

### Stop services and delete all data
```bash
docker compose down -v
```

### Remove built images
```bash
docker rmi implementation-agent-app
docker rmi chromadb/chroma:latest
docker rmi ghcr.io/chroma-core/chroma-mcp:latest
```

---

## Next Steps

1. **Read the README**: `agent-app/README.md` for detailed documentation
2. **Review the code**: Start with `src/app.py` to understand the flows
3. **Modify the demo**: Edit `app.py` `_demonstrate_flows()` to test your scenarios
4. **Add tests**: Implement unit tests in `tests/unit/`
5. **Integration test**: Implement end-to-end tests in `tests/integration/`

---

## Performance Monitoring

### Watch resource usage
```bash
docker stats
```

### Check ChromaDB collection sizes
```bash
curl http://localhost:8000/api/v1/collections/history | jq
curl http://localhost:8000/api/v1/collections/memory | jq
```

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `docker compose up -d` | Start all services |
| `docker compose down` | Stop all services |
| `docker compose logs -f agent-app` | Follow agent logs |
| `docker compose ps` | Check service status |
| `docker compose restart agent-app` | Restart agent only |
| `curl http://localhost:8000/api/v1/collections` | List collections |

---

## Success Indicators

✅ All 3 services show "Up" in `docker compose ps`
✅ ChromaDB health check passes
✅ Agent-app logs show "Application ready"
✅ Collections ["history", "memory"] exist
✅ Demonstration flows complete without errors
✅ Data persists after `docker compose restart`

If all indicators are ✅, the system is working correctly!

---

**Need help?** Check the troubleshooting section or review logs:
```bash
docker compose logs
```
