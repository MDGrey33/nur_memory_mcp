# MCP Memory V4 Deployment Checklist

**Version:** 4.0.0
**Date:** 2025-12-28

Use this checklist for every V4 deployment. Print and check off each item.

---

## Pre-Deployment (1-2 days before)

### Environment Preparation

- [ ] Review V4 changes in `v4.md` specification
- [ ] Review security audit findings in `v4-security-audit.md`
- [ ] Verify staging environment matches production
- [ ] Confirm rollback procedure is documented and tested

### Infrastructure Verification

- [ ] PostgreSQL version is 16+
- [ ] pgvector extension available
- [ ] Apache AGE extension available (or plan for `V4_GRAPH_ENABLED=false`)
- [ ] Sufficient disk space (current DB size + 30%)
- [ ] OpenAI API key has sufficient quota

### Configuration

- [ ] Copy `env.v4.example` to `.env`
- [ ] Set `POSTGRES_PASSWORD` (strong, unique)
- [ ] Update `EVENTS_DB_DSN` with password
- [ ] Set `OPENAI_API_KEY`
- [ ] Review V4-specific settings:
  - [ ] `V4_GRAPH_ENABLED` (true/false)
  - [ ] `ENTITY_SIMILARITY_THRESHOLD` (default: 0.85)
  - [ ] `V4_GRAPH_QUERY_TIMEOUT_MS` (default: 500)
  - [ ] `V4_GRAPH_BUDGET_MAX` (security limit)

### Backup

- [ ] Full database backup created
- [ ] Backup stored off-site
- [ ] Backup restore procedure tested
- [ ] Backup timestamp: `____________`

---

## Deployment Day

### Pre-Migration (30 min before)

- [ ] Notify stakeholders of deployment window
- [ ] Stop event-worker service
- [ ] Verify no in-flight extraction jobs:
  ```sql
  SELECT COUNT(*) FROM event_jobs WHERE status = 'PROCESSING';
  ```
- [ ] Wait for count to reach 0

### Pre-Check Migration

- [ ] Run pre-migration verification:
  ```bash
  psql -f v4/migrations/001_v4_pre_check.sql
  ```
- [ ] All checks passed: `[ YES / NO ]`
- [ ] Resolve any warnings before proceeding

### Migration 008: Entity Tables

- [ ] Run migration:
  ```bash
  psql -f v4/migrations/008_v4_entity_tables.sql
  ```
- [ ] Verify tables created:
  ```sql
  SELECT tablename FROM pg_tables
  WHERE tablename IN ('entity', 'entity_alias', 'entity_mention', 'event_actor', 'event_subject');
  ```
- [ ] Expected: 5 tables
- [ ] Actual count: `____`

### Migration 009: AGE Setup (if applicable)

- [ ] Skip if `V4_GRAPH_ENABLED=false`
- [ ] Run migration:
  ```bash
  psql -f v4/migrations/009_v4_age_setup.sql
  ```
- [ ] Verify graph created:
  ```sql
  SELECT * FROM ag_catalog.ag_graph WHERE name = 'nur';
  ```
- [ ] Verify health check function:
  ```sql
  SELECT * FROM check_graph_health();
  ```
- [ ] Status: `healthy` / `unhealthy` / `skipped`

### Service Deployment

- [ ] Pull/build V4 Docker images:
  ```bash
  cd .claude-workspace/deployment/v4/docker
  docker compose -f docker-compose.v4.yml build
  ```
- [ ] Start services:
  ```bash
  docker compose -f docker-compose.v4.yml up -d
  ```
- [ ] Wait for all services healthy (5 min max)

### Health Verification

- [ ] ChromaDB health:
  ```bash
  curl http://localhost:8001/api/v2/heartbeat
  ```
  - Status: `OK` / `FAIL`

- [ ] PostgreSQL health:
  ```bash
  docker compose exec postgres pg_isready -U events
  ```
  - Status: `OK` / `FAIL`

- [ ] MCP Server health:
  ```bash
  curl http://localhost:3000/health
  ```
  - Status: `OK` / `FAIL`
  - Version: `4.0.0` / `____`

- [ ] Graph health (if enabled):
  ```bash
  curl http://localhost:3000/health/graph
  ```
  - AGE enabled: `true` / `false`
  - Graph exists: `true` / `false`

- [ ] Event worker health:
  ```bash
  docker compose logs event-worker | tail -20
  ```
  - Status: `Running` / `Error`

### Functional Verification (MCP Tools)

- [ ] V3 compatibility - `hybrid_search(graph_expand=false)` returns without graph fields:
  - Use MCP Inspector and call tool `hybrid_search` with `{"query":"test","graph_expand":false}`
  - Response: `OK` / `ERROR`

- [ ] V4 graph expansion - `hybrid_search(graph_expand=true)` returns `expand_options` on every call:
  - Use MCP Inspector and call tool `hybrid_search` with `{"query":"test","graph_expand":true,"graph_budget":5}`
  - Response includes `expand_options`: `YES` / `NO`
  - Response may include `related_context` / `entities` depending on available graph edges

- [ ] Ingest test artifact:
  - Submit test document
  - Wait for extraction (check `event_jobs`)
  - Verify entity created in `entity` table
  - Verify graph nodes created (if enabled)

---

## Post-Deployment (within 1 hour)

### Monitoring Setup

- [ ] Prometheus scraping V4 metrics
- [ ] Grafana dashboard showing data
- [ ] Key alerts configured:
  - [ ] `EntityResolutionSlowP95`
  - [ ] `GraphExpansionTimeoutHigh`
  - [ ] `GraphUnhealthy` (if enabled)

### Performance Baseline

- [ ] Record baseline metrics (first hour):
  - Entity resolution P95: `____ ms`
  - Graph expansion P95: `____ ms` (or N/A)
  - Hybrid search P95: `____ ms`

### Documentation

- [ ] Update runbooks with V4 procedures
- [ ] Update on-call documentation
- [ ] Record deployment in changelog

---

## Post-Deployment (within 24 hours)

### Verification

- [ ] No errors in logs:
  ```bash
  docker compose logs --since 24h | grep -i error | wc -l
  ```
  - Error count: `____`

- [ ] Entity resolution working:
  ```sql
  SELECT COUNT(*) FROM entity WHERE created_at > now() - interval '24 hours';
  ```
  - New entities: `____`

- [ ] Graph nodes created (if enabled):
  ```sql
  SELECT * FROM get_graph_stats();
  ```
  - Entity nodes: `____`
  - Event nodes: `____`

- [ ] No stuck jobs:
  ```sql
  SELECT COUNT(*) FROM event_jobs
  WHERE status = 'PENDING'
  AND created_at < now() - interval '1 hour';
  ```
  - Stuck jobs: `____` (should be 0)

### Cost Monitoring

- [ ] Check OpenAI usage dashboard
- [ ] Daily cost within expected range: `$____`

### Review Queue

- [ ] Check entities needing review:
  ```sql
  SELECT COUNT(*) FROM entity WHERE needs_review = true;
  ```
  - Count: `____`
- [ ] Process review queue if >20 entities

---

## Rollback Procedure (if needed)

### Trigger Conditions

Check these conditions - if ANY are true, consider rollback:

- [ ] Graph health failing for >10 minutes
- [ ] Entity resolution error rate >10%
- [ ] Event extraction queue growing (>100 pending for >30 min)
- [ ] Hybrid search latency >2x baseline
- [ ] Critical security vulnerability discovered

### Rollback Steps

1. [ ] Stop V4 services:
   ```bash
   docker compose -f docker-compose.v4.yml down
   ```

2. [ ] Rollback graph (if created):
   ```bash
   psql -f v4/migrations/rollback_009.sql
   ```

3. [ ] Rollback entity tables:
   ```bash
   psql -f v4/migrations/rollback_008.sql
   ```

4. [ ] Start V3 services:
   ```bash
   docker compose -f docker-compose.v3.yml up -d
   ```

5. [ ] Verify V3 functionality:
   ```bash
   curl http://localhost:3000/health
   python healthcheck.py --service all
   ```

6. [ ] Document rollback reason: `________________________`

---

## Sign-Off

### Deployment Completed

- Deployed by: `________________________`
- Date/Time: `________________________`
- Environment: `[ ] Staging  [ ] Production`
- Result: `[ ] Success  [ ] Partial  [ ] Rollback`

### Notes

```
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________
```

### Approvals

- DevOps Engineer: `____________` Date: `________`
- Platform Lead: `____________` Date: `________`
- Security (if applicable): `____________` Date: `________`

---

**Keep this checklist with deployment records for audit purposes.**
