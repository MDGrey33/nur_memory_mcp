# V5 Rollback Procedure

This document describes how to safely rollback from MCP Memory Server V5 to V4 if issues arise.

## Version Compatibility Matrix

| Version | Tools | Collections | Database Schema |
|---------|-------|-------------|-----------------|
| V5 | remember, recall, forget, status + all V4 | content, chunks + V4 | Same as V4 (migrations 001-009) |
| V4 | artifact_ingest, hybrid_search, event_* | artifacts, artifact_chunks | migrations 001-009 |
| V3 | artifact_ingest, event_* | artifacts, artifact_chunks | migrations 001-007 |

## Quick Rollback (< 5 min)

If V5 causes immediate issues, follow this procedure:

### 1. Stop V5 Services

```bash
cd .claude-workspace/deployment
docker compose stop mcp-server event-worker
```

### 2. Deploy Previous V4 Container

```bash
# Pull/build V4 image
docker build -t mcp-memory-server:v4 \
  --build-arg VERSION=4.x.x \
  ../implementation/mcp-server

# Update docker-compose to use v4 image
sed -i 's/mcp-memory-server:v5/mcp-memory-server:v4/g' docker-compose.yml

# Restart services
docker compose up -d mcp-server event-worker
```

### 3. Verify V4 is Running

```bash
./scripts/health-check.sh --json | jq '.version'
# Should show 4.x.x
```

## Data Considerations

### V5 Data Architecture

V5 introduces new unified collections while maintaining V4 compatibility:

| Collection | Purpose | Created by |
|------------|---------|------------|
| `content` | V5 unified content storage | V5 remember() |
| `chunks` | V5 chunk storage | V5 remember() |
| `artifacts` | V4 artifact storage | V4 artifact_ingest() |
| `artifact_chunks` | V4 chunk storage | V4 artifact_ingest() |

### Backward Compatibility

- **V5 can read V4 data**: The V4 collections (artifacts, artifact_chunks) remain functional
- **V4 cannot use V5 data**: V4 tools don't know about V5 collections (content, chunks)
- **No data migration**: V5 creates new collections, doesn't modify V4 data

### Data Flow During Rollback

```
V5 Running:
  - remember() -> content, chunks collections
  - recall() -> searches content + artifacts
  - artifact_ingest() -> artifacts collection (V4 compat)

After Rollback to V4:
  - artifact_ingest() -> artifacts collection
  - hybrid_search() -> searches artifacts only
  - V5 collections (content, chunks) exist but unused
```

## Clean Rollback (Optional)

If you want to completely remove V5 data:

### Option 1: Delete V5 ChromaDB Collections Only

```bash
# Create reset script
cat > scripts/reset_v5.py << 'EOF'
#!/usr/bin/env python3
"""Delete V5 ChromaDB collections without affecting V4 data."""
import chromadb
import sys

def reset_v5_collections(confirm: bool = False):
    client = chromadb.HttpClient(host="localhost", port=8001)

    v5_collections = ["content", "chunks"]

    for name in v5_collections:
        try:
            collection = client.get_collection(name)
            count = collection.count()

            if confirm:
                client.delete_collection(name)
                print(f"Deleted collection '{name}' ({count} items)")
            else:
                print(f"Would delete collection '{name}' ({count} items)")
        except Exception as e:
            print(f"Collection '{name}' not found or error: {e}")

    if not confirm:
        print("\nRun with --confirm to actually delete")

if __name__ == "__main__":
    confirm = "--confirm" in sys.argv
    reset_v5_collections(confirm)
EOF

# Preview what will be deleted
python scripts/reset_v5.py

# Actually delete (requires --confirm flag)
python scripts/reset_v5.py --confirm
```

### Option 2: Full Data Reset

**WARNING: This deletes ALL data including V4!**

```bash
# Stop all services
docker compose down

# Remove volumes
docker volume rm mcp-memory-v5_chroma_data mcp-memory-v5_postgres_data

# Restart with fresh data
docker compose up -d
```

## PostgreSQL Considerations

### Schema Compatibility

V5 uses the same database schema as V4:
- Migrations 001-009 are shared
- No new V5-specific tables
- Event extraction works the same way

### No Schema Rollback Needed

Since V5 doesn't add new database tables, there's no need to rollback PostgreSQL schema when reverting to V4.

## Rollback Verification Checklist

After rolling back to V4, verify:

- [ ] Health check passes: `./scripts/health-check.sh`
- [ ] Version is V4: `curl -s localhost:3000/health | jq .version`
- [ ] V4 tools work: Test `artifact_ingest` and `hybrid_search`
- [ ] Existing data accessible: Query artifacts created before V5
- [ ] Event worker running: `docker compose logs event-worker`
- [ ] No errors in logs: `docker compose logs mcp-server`

## Emergency Contacts

If rollback doesn't resolve the issue:

1. Check logs: `docker compose logs --tail=100`
2. Review recent changes: `git log --oneline -10`
3. Consult deployment documentation: See `ENVIRONMENTS.md`

## Recovery Timeline

| Action | Time | Impact |
|--------|------|--------|
| Stop V5 | 30s | Services unavailable |
| Deploy V4 | 2-3 min | Building/pulling image |
| Verify health | 30s | Services available |
| **Total** | **< 5 min** | Brief downtime |

## Prevention

To minimize rollback risk:

1. **Test in staging first**: Deploy V5 to staging environment
2. **Monitor closely**: Watch logs for first 24 hours
3. **Keep V4 image**: Don't remove `mcp-memory-server:v4` image
4. **Backup before upgrade**: `./scripts/backup.sh` before V5 deploy

## Version History

| Date | Version | Notes |
|------|---------|-------|
| 2025-01-XX | 5.0.0-alpha | Initial V5 release with remember/recall/forget/status |
| 2024-XX-XX | 4.x.x | Graph expansion, entity resolution |
| 2024-XX-XX | 3.x.x | Semantic event extraction |
