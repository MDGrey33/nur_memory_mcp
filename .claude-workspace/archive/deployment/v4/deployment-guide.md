# MCP Memory Server V4 Deployment Guide

**Version:** 4.0.0
**Date:** 2025-12-28
**Author:** DevOps Engineer (Claude Mind Autonomous Development)

---

## Overview

V4 introduces graph-backed context expansion using Apache AGE (PostgreSQL graph extension). This guide covers the deployment configuration, migration strategy, and operational procedures for V4.

### Key Changes from V3

| Component | V3 | V4 |
|-----------|-----|-----|
| PostgreSQL | 16-alpine | 16-alpine + AGE extension |
| Graph Database | None | Apache AGE (in-Postgres) |
| New Tables | 4 tables | + 5 entity/event tables |
| New Services | None | graph_upsert worker (optional) |
| Hybrid Search | Basic RRF | + Graph expansion |

### Architecture Overview

```
                    +------------------+
                    |   Claude Code    |
                    |  (MCP Client)    |
                    +--------+---------+
                             |
                    +--------v---------+
                    |   MCP Server     |
                    |   (FastMCP)      |
                    +--------+---------+
                             |
          +------------------+------------------+
          |                  |                  |
+---------v------+  +--------v--------+  +-----v-----------+
|   ChromaDB     |  |   PostgreSQL    |  |  Event Worker   |
| (Vector Store) |  | + pgvector      |  | + Entity Res.   |
|                |  | + Apache AGE    |  | + Graph Upsert  |
+----------------+  +-----------------+  +-----------------+
```

---

## Prerequisites

### Required Infrastructure

1. **PostgreSQL 16+** with extensions:
   - `pgvector` (vector similarity search)
   - `age` (Apache AGE graph extension)

2. **Docker** (if using containers):
   - Docker Engine 20.10+
   - Docker Compose V2+

3. **OpenAI API Key** with access to:
   - `text-embedding-3-large` (embeddings)
   - `gpt-4o-mini` (entity deduplication)

### Pre-flight Checks

Run these checks before starting V4 deployment:

```bash
# Check Docker version
docker --version  # Requires 20.10+

# Check Docker Compose version
docker compose version  # Requires v2.0+

# Check PostgreSQL extensions availability (if using custom image)
docker run --rm apache/age:PG16-latest psql -U postgres -c "SELECT * FROM pg_available_extensions WHERE name IN ('vector', 'age');"
```

---

## Deployment Options

### Option A: Docker Compose (Recommended)

Full stack deployment with AGE-enabled PostgreSQL.

```bash
# Navigate to deployment directory
cd .claude-workspace/deployment/v4/docker

# Copy environment template
cp ../env.v4.example .env

# Edit .env with your configuration
# CRITICAL: Set OPENAI_API_KEY and POSTGRES_PASSWORD

# Start services
docker compose -f docker-compose.v4.yml up -d

# Run migrations
docker compose -f docker-compose.v4.yml exec postgres psql -U events -d events -f /migrations/008_v4_entity_tables.sql
docker compose -f docker-compose.v4.yml exec postgres psql -U events -d events -f /migrations/009_v4_age_setup.sql
```

### Option B: Existing PostgreSQL with Manual AGE Installation

If you have an existing PostgreSQL instance:

1. **Install Apache AGE extension**:
   ```sql
   -- Requires PostgreSQL 16 with AGE compiled
   -- See: https://age.apache.org/age-manual/master/intro/setup.html
   CREATE EXTENSION IF NOT EXISTS age;
   ```

2. **Install pgvector** (if not already installed):
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

3. **Run V4 migrations** (see Migration Scripts section)

### Option C: Managed PostgreSQL (AWS RDS, Azure, GCP)

Currently not recommended for V4 due to:
- Apache AGE may not be available as a managed extension
- Consider using Option D (relational fallback) instead

### Option D: V4 Without Graph (Relational Fallback)

If Apache AGE is unavailable, V4 can operate with reduced graph functionality:
- Entity resolution still works (uses PostgreSQL tables)
- Graph expansion disabled (returns empty `related_context`)
- `hybrid_search(graph_expand=true)` gracefully degrades

Set in environment:
```bash
V4_GRAPH_ENABLED=false
```

---

## Migration Scripts

### Migration Order

Migrations must be run in order:

1. **008_v4_entity_tables.sql** - Entity resolution tables
2. **009_v4_age_setup.sql** - Apache AGE graph setup

### Pre-Migration Checklist

```bash
# 1. Backup current database
pg_dump -h localhost -U events -d events > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Check pgvector extension
psql -U events -d events -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
# Expected: vector | 0.5.1 (or higher)

# 3. Check PostgreSQL version
psql -U events -d events -c "SELECT version();"
# Expected: PostgreSQL 16.x

# 4. Check AGE availability (for 009 migration)
psql -U events -d events -c "SELECT name FROM pg_available_extensions WHERE name = 'age';"
# Expected: age (if installed in system)
```

### Running Migrations

#### Migration 008: Entity Tables

```bash
# From deployment directory
psql -h localhost -U events -d events -f ./v4/migrations/008_v4_entity_tables.sql

# Verify
psql -h localhost -U events -d events -c "SELECT tablename FROM pg_tables WHERE tablename LIKE 'entity%' OR tablename LIKE 'event_actor%' OR tablename LIKE 'event_subject%';"
```

Expected tables:
- `entity`
- `entity_alias`
- `entity_mention`
- `event_actor`
- `event_subject`

#### Migration 009: AGE Graph Setup

```bash
# From deployment directory
psql -h localhost -U events -d events -f ./v4/migrations/009_v4_age_setup.sql

# Verify AGE setup
psql -h localhost -U events -d events -c "SELECT * FROM ag_catalog.ag_graph WHERE name = 'nur';"
```

### Rollback Scripts

#### Rollback 009 (AGE Graph)

```sql
-- WARNING: This will delete all graph data
BEGIN;

-- Drop the graph
SELECT * FROM ag_catalog.drop_graph('nur', true);

-- Drop helper function
DROP FUNCTION IF EXISTS execute_cypher(TEXT, TEXT);

-- Optionally drop AGE extension (only if not needed elsewhere)
-- DROP EXTENSION IF EXISTS age;

COMMIT;
```

#### Rollback 008 (Entity Tables)

```sql
-- WARNING: This will delete all entity resolution data
BEGIN;

-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS event_subject CASCADE;
DROP TABLE IF EXISTS event_actor CASCADE;
DROP TABLE IF EXISTS entity_mention CASCADE;
DROP TABLE IF EXISTS entity_alias CASCADE;
DROP TABLE IF EXISTS entity CASCADE;

COMMIT;
```

---

## Environment Configuration

### V4 Environment Variables

Create `.env` file from `env.v4.example`:

```bash
# ============================================================================
# V4 REQUIRED CONFIGURATION
# ============================================================================

# OpenAI API Key (REQUIRED)
OPENAI_API_KEY=sk-proj-your-key-here

# PostgreSQL Password (REQUIRED - CHANGE THIS!)
POSTGRES_PASSWORD=your-secure-password-here

# Database DSN (REQUIRED - update with your password)
EVENTS_DB_DSN=postgresql://events:your-secure-password-here@postgres:5432/events

# ============================================================================
# V4 NEW CONFIGURATION OPTIONS
# ============================================================================

# Entity Resolution Settings
# Similarity threshold for embedding-based candidate matching (0.0-1.0)
ENTITY_SIMILARITY_THRESHOLD=0.85

# Maximum candidates to consider for LLM confirmation
ENTITY_MAX_CANDIDATES=5

# LLM model for entity deduplication (cost vs quality tradeoff)
ENTITY_DEDUP_MODEL=gpt-4o-mini

# Graph Configuration
# Enable/disable graph features (set false if AGE unavailable)
V4_GRAPH_ENABLED=true

# Graph name in Apache AGE
V4_GRAPH_NAME=nur

# Graph query timeout in milliseconds
V4_GRAPH_QUERY_TIMEOUT_MS=500

# Hybrid Search V4 Defaults
# Default budget for graph expansion results
V4_GRAPH_BUDGET_DEFAULT=10

# Maximum allowed graph budget (security limit)
# Note: `hybrid_search` validates `graph_budget` in range 0–50.
V4_GRAPH_BUDGET_MAX=50

# Default seed limit (how many primary results to expand from)
# Note: V4 default is tuned for quality: anchor expansion on the top hit.
V4_GRAPH_SEED_LIMIT_DEFAULT=1

# Maximum allowed seed limit
V4_GRAPH_SEED_LIMIT_MAX=20

# ============================================================================
# EXISTING V3 CONFIGURATION (unchanged)
# ============================================================================

# PostgreSQL
POSTGRES_DB=events
POSTGRES_USER=events

# ChromaDB
CHROMA_HOST=chroma
CHROMA_PORT=8000

# MCP Server
MCP_PORT=3000
LOG_LEVEL=INFO

# Event Worker
WORKER_ID=worker-1
POLL_INTERVAL_MS=1000
EVENT_MAX_ATTEMPTS=5

# OpenAI Models
OPENAI_EMBED_MODEL=text-embedding-3-large
OPENAI_EVENT_MODEL=gpt-4o-mini
```

### Security Considerations

1. **Never commit `.env` to version control**
2. **Use strong passwords** - generate with:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. **Rotate API keys** regularly
4. **PII in entity tables** - consider field-level encryption for `email` field

---

## Docker Configuration

### PostgreSQL with AGE

V4 requires a PostgreSQL image with Apache AGE installed. We provide a custom Dockerfile:

```dockerfile
# docker/Dockerfile.postgres-age
FROM postgres:16-alpine

# Install build dependencies
RUN apk add --no-cache \
    git \
    build-base \
    clang15 \
    llvm15 \
    bison \
    flex \
    readline-dev

# Install AGE from source
WORKDIR /tmp
RUN git clone --depth 1 --branch PG16/v1.5.0 https://github.com/apache/age.git \
    && cd age \
    && make install \
    && cd .. \
    && rm -rf age

# Install pgvector
RUN git clone --depth 1 --branch v0.5.1 https://github.com/pgvector/pgvector.git \
    && cd pgvector \
    && make install \
    && cd .. \
    && rm -rf pgvector

# Clean up build dependencies
RUN apk del git build-base clang15 llvm15 bison flex readline-dev

# Configure AGE to load on startup
RUN echo "shared_preload_libraries = 'age'" >> /usr/local/share/postgresql/postgresql.conf.sample

WORKDIR /
```

Alternatively, use a pre-built image:
```yaml
# In docker-compose.v4.yml
postgres:
  image: apache/age:PG16-latest
  # ... rest of configuration
```

### Docker Compose V4

See `docker-compose.v4.yml` for the complete configuration.

---

## Health Checks

### Graph Health Check Endpoint

V4 adds a graph health check endpoint:

```python
# GET /health/graph
# Response:
{
    "status": "healthy",
    "age_enabled": true,
    "graph_exists": true,
    "entity_node_count": 150,
    "event_node_count": 1200,
    "acted_in_edge_count": 2500,
    "about_edge_count": 1800,
    "possibly_same_edge_count": 25
}
```

### Entity Resolution Service Check

```python
# GET /health/entity-resolution
# Response:
{
    "status": "healthy",
    "embedding_service": "ok",
    "pg_connection": "ok",
    "openai_connection": "ok",
    "entity_count": 150,
    "pending_review_count": 5
}
```

### Health Check Script

Use the updated `healthcheck.py`:

```bash
# Check all V4 services
python healthcheck.py --service all --v4

# Check specific service
python healthcheck.py --service graph
python healthcheck.py --service entity-resolution
```

### Docker Health Check Configuration

```yaml
healthcheck:
  test: ["CMD", "python", "/app/healthcheck.py", "--service", "mcp-server", "--v4"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 45s  # Increased for AGE initialization
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Review security audit findings (see `v4-security-audit.md`)
- [ ] Backup existing V3 database
- [ ] Test migrations on staging environment
- [ ] Verify AGE extension availability
- [ ] Update `.env` with V4 configuration
- [ ] Review resource limits for containers

### Migration

- [ ] Stop event-worker service
- [ ] Run migration 008 (entity tables)
- [ ] Verify entity tables created
- [ ] Run migration 009 (AGE setup)
- [ ] Verify graph `nur` exists
- [ ] Test `hybrid_search(graph_expand=false)` works (V3 compatibility)

### Post-Migration

- [ ] Start V4 services
- [ ] Verify health checks pass
- [ ] Test entity extraction with new document
- [ ] Verify entities created in `entity` table
- [ ] Verify graph nodes created in AGE
- [ ] Test `hybrid_search(graph_expand=true)`
- [ ] Monitor logs for errors
- [ ] Verify expand_options returned in search results

### Rollback Triggers

Roll back to V3 if:
- [ ] AGE extension fails to initialize
- [ ] Entity resolution causes >10% ingest failures
- [ ] Graph expansion latency exceeds 500ms p95
- [ ] Database disk usage grows unexpectedly

### Rollback Procedure

```bash
# 1. Stop V4 services
docker compose -f docker-compose.v4.yml down

# 2. Rollback migrations (preserves V3 data)
psql -h localhost -U events -d events < ./v4/migrations/rollback_009.sql
psql -h localhost -U events -d events < ./v4/migrations/rollback_008.sql

# 3. Start V3 services
docker compose -f docker-compose.v3.yml up -d

# 4. Verify V3 functionality
python healthcheck.py --service all
```

---

## Monitoring & Alerting

### Key Metrics to Track

#### Entity Resolution Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `entity_resolution_duration_ms` | Time to resolve entity | p95 > 200ms |
| `entity_dedup_llm_calls` | LLM calls for deduplication | > 10/min |
| `entity_merge_decisions` | Merge decisions by type | Unusual ratios |
| `entity_needs_review_count` | Entities needing review | > 50 |

#### Graph Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `graph_expansion_duration_ms` | Graph query time | p95 > 300ms |
| `graph_node_count` | Total nodes in graph | Growth anomaly |
| `graph_edge_count` | Total edges in graph | Growth anomaly |
| `graph_query_timeout_count` | Timed out queries | > 5/min |

#### Cost Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `openai_embedding_tokens` | Embedding API usage | Budget limit |
| `openai_completion_tokens` | LLM API usage | Budget limit |
| `entity_dedup_cost_usd` | Estimated dedup cost | > $1/day |

### Prometheus Metrics Endpoint

Add to MCP server configuration:

```python
# /metrics endpoint
entity_resolution_duration = Histogram(
    'entity_resolution_duration_seconds',
    'Entity resolution duration',
    buckets=[0.05, 0.1, 0.2, 0.5, 1.0]
)

graph_expansion_duration = Histogram(
    'graph_expansion_duration_seconds',
    'Graph expansion query duration',
    buckets=[0.05, 0.1, 0.2, 0.3, 0.5]
)

entity_needs_review_gauge = Gauge(
    'entity_needs_review_total',
    'Entities requiring manual review'
)
```

### Grafana Dashboard

Import the V4 dashboard from `monitoring/grafana/v4-dashboard.json`.

Key panels:
- Entity resolution latency histogram
- Graph expansion latency histogram
- Entity merge decision breakdown
- Node/edge growth over time
- OpenAI cost tracking

### Log Aggregation

V4 adds structured logging for:

```json
{
    "event": "entity_resolved",
    "entity_id": "uuid",
    "is_new": true,
    "decision": "same|different|uncertain",
    "candidate_count": 3,
    "duration_ms": 150
}
```

```json
{
    "event": "graph_expansion",
    "seed_count": 5,
    "result_count": 8,
    "budget": 10,
    "duration_ms": 95
}
```

---

## Troubleshooting

### AGE Extension Not Found

```
ERROR: extension "age" is not available
```

**Solution:** Use AGE-enabled PostgreSQL image or install AGE from source.

### Graph Query Timeout

```
ERROR: graph query timed out after 500ms
```

**Solutions:**
1. Increase `V4_GRAPH_QUERY_TIMEOUT_MS` (max 2000)
2. Reduce `graph_budget` parameter
3. Check for missing indexes on graph nodes

### Entity Embedding Failed

```
ERROR: Failed to generate context embedding
```

**Solutions:**
1. Check OpenAI API key is valid
2. Verify network connectivity to OpenAI
3. Check rate limits on OpenAI account

### LLM Confirmation Timeout

```
ERROR: LLM confirmation failed: timeout
```

**Solutions:**
1. OpenAI service may be overloaded - retry later
2. Check `ENTITY_DEDUP_MODEL` is valid
3. Review entity context string length

### Migration Fails: semantic_event Not Found

```
ERROR: relation "semantic_event" does not exist
```

**Solution:** Ensure V3 migrations have run before V4 migrations.

---

## Performance Tuning

### PostgreSQL Tuning for AGE

```sql
-- Add to postgresql.conf
shared_preload_libraries = 'age'
search_path = '"$user", public, ag_catalog'

-- Memory settings for graph queries
work_mem = '256MB'
effective_cache_size = '2GB'
```

### Index Maintenance

```sql
-- Reindex entity embedding index (run weekly)
REINDEX INDEX CONCURRENTLY entity_embedding_idx;

-- Vacuum analyze after bulk imports
VACUUM ANALYZE entity;
VACUUM ANALYZE entity_mention;
```

### Connection Pool Sizing

For V4, increase pool size to handle parallel graph queries:

```bash
PG_POOL_SIZE=15  # Up from 10
PG_POOL_MAX_OVERFLOW=30  # Up from 20
```

---

## Security Audit Findings

See `v4-security-audit.md` for complete audit. Critical items:

1. **C-01: Cypher Injection** - Implement comprehensive escaping before production
2. **H-01: Unbounded Graph Expansion** - Enforce budget limits
3. **H-03: PII in Clear Text** - Consider encrypting email field

---

## Support & Resources

- **Apache AGE Documentation**: https://age.apache.org/age-manual/
- **pgvector Documentation**: https://github.com/pgvector/pgvector
- **Security Audit**: `.claude-workspace/security/v4-security-audit.md`
- **Architecture Decisions**: `.claude-workspace/architecture/v4/adr/`

---

**Next Review:** After 2 weeks of production operation
**Document Owner:** DevOps Engineer
