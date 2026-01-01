# MCP Memory V4 Monitoring Guide

**Version:** 4.0.0
**Date:** 2025-12-28

---

## Overview

V4 introduces new monitoring requirements for:
- Entity resolution service (embedding + LLM deduplication)
- Graph service (Apache AGE queries)
- Enhanced hybrid_search with graph expansion

This guide covers metrics, alerting, logging, and dashboards for V4.

---

## Key Metrics

### Entity Resolution Metrics

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `entity_resolution_total` | Counter | Total entity resolutions | `decision=[new,merged,uncertain]` |
| `entity_resolution_duration_seconds` | Histogram | Time to resolve an entity | `phase=[embedding,candidate,llm,db]` |
| `entity_dedup_candidates_found` | Histogram | Number of candidates per resolution | - |
| `entity_dedup_llm_calls_total` | Counter | LLM confirmation calls | `decision=[same,different,uncertain]` |
| `entity_needs_review_total` | Gauge | Entities awaiting manual review | - |
| `entity_table_size` | Gauge | Total entities in database | `type=[person,org,project,other]` |

### Graph Metrics

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `graph_expansion_total` | Counter | Graph expansion requests | `status=[success,timeout,error]` |
| `graph_expansion_duration_seconds` | Histogram | Time for graph query | - |
| `graph_expansion_results` | Histogram | Number of related items returned | - |
| `graph_node_count` | Gauge | Total nodes in graph | `type=[Entity,Event]` |
| `graph_edge_count` | Gauge | Total edges in graph | `type=[ACTED_IN,ABOUT,POSSIBLY_SAME]` |
| `graph_query_timeout_total` | Counter | Timed out graph queries | - |
| `graph_health_status` | Gauge | Graph health (1=healthy, 0=unhealthy) | - |

### Hybrid Search V4 Metrics

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `hybrid_search_v4_total` | Counter | V4 search requests | `graph_expand=[true,false]` |
| `hybrid_search_v4_duration_seconds` | Histogram | Total search time | `phase=[primary,graph,total]` |
| `hybrid_search_v4_primary_results` | Histogram | Primary result count | - |
| `hybrid_search_v4_related_results` | Histogram | Related context count | - |

### Cost Metrics

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `openai_tokens_total` | Counter | Total tokens used | `type=[embedding,completion],model` |
| `openai_cost_usd` | Counter | Estimated cost in USD | `type=[embedding,completion]` |
| `entity_dedup_cost_usd` | Counter | Entity deduplication cost | - |

---

## Prometheus Configuration

### Scrape Configuration

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'mcp-memory-v4'
    static_configs:
      - targets:
        - 'mcp-server:9090'
        - 'event-worker:9090'
    metrics_path: '/metrics'
    scrape_interval: 15s
    scrape_timeout: 10s
```

### Recording Rules

Create `mcp_v4_rules.yml`:

```yaml
groups:
  - name: mcp_v4_entity_resolution
    rules:
      # Entity resolution rate
      - record: mcp:entity_resolution_rate_5m
        expr: rate(entity_resolution_total[5m])

      # Entity resolution error rate
      - record: mcp:entity_resolution_error_rate_5m
        expr: rate(entity_resolution_total{decision="error"}[5m]) / rate(entity_resolution_total[5m])

      # Average entity resolution latency
      - record: mcp:entity_resolution_latency_avg_5m
        expr: rate(entity_resolution_duration_seconds_sum[5m]) / rate(entity_resolution_duration_seconds_count[5m])

      # LLM calls per entity resolution
      - record: mcp:entity_llm_calls_ratio_5m
        expr: rate(entity_dedup_llm_calls_total[5m]) / rate(entity_resolution_total[5m])

  - name: mcp_v4_graph
    rules:
      # Graph expansion rate
      - record: mcp:graph_expansion_rate_5m
        expr: rate(graph_expansion_total[5m])

      # Graph expansion success rate
      - record: mcp:graph_expansion_success_rate_5m
        expr: rate(graph_expansion_total{status="success"}[5m]) / rate(graph_expansion_total[5m])

      # Graph expansion timeout rate
      - record: mcp:graph_expansion_timeout_rate_5m
        expr: rate(graph_query_timeout_total[5m]) / rate(graph_expansion_total[5m])

      # Average graph expansion latency
      - record: mcp:graph_expansion_latency_avg_5m
        expr: rate(graph_expansion_duration_seconds_sum[5m]) / rate(graph_expansion_duration_seconds_count[5m])
```

---

## Alerting Rules

Create `mcp_v4_alerts.yml`:

```yaml
groups:
  - name: mcp_v4_entity_resolution_alerts
    rules:
      # High entity resolution latency
      - alert: EntityResolutionSlowP95
        expr: histogram_quantile(0.95, rate(entity_resolution_duration_seconds_bucket[5m])) > 0.2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Entity resolution P95 latency is high"
          description: "P95 latency is {{ $value | printf \"%.3f\" }}s (threshold: 0.2s)"

      # High entity resolution latency - critical
      - alert: EntityResolutionSlowP95Critical
        expr: histogram_quantile(0.95, rate(entity_resolution_duration_seconds_bucket[5m])) > 0.5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Entity resolution P95 latency is critically high"
          description: "P95 latency is {{ $value | printf \"%.3f\" }}s (threshold: 0.5s)"

      # High LLM call rate (cost concern)
      - alert: EntityDedupHighLLMCalls
        expr: rate(entity_dedup_llm_calls_total[1h]) > 100
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High LLM call rate for entity deduplication"
          description: "LLM calls: {{ $value | printf \"%.1f\" }}/hour"

      # Many entities needing review
      - alert: EntityReviewQueueHigh
        expr: entity_needs_review_total > 50
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Many entities awaiting manual review"
          description: "{{ $value }} entities need review"

  - name: mcp_v4_graph_alerts
    rules:
      # Graph expansion timeout rate
      - alert: GraphExpansionTimeoutHigh
        expr: mcp:graph_expansion_timeout_rate_5m > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Graph expansion timeout rate is high"
          description: "Timeout rate: {{ $value | printf \"%.2f\" }}% (threshold: 5%)"

      # Graph health check failing
      - alert: GraphUnhealthy
        expr: graph_health_status == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Graph database is unhealthy"
          description: "AGE graph health check is failing"

      # Graph expansion latency
      - alert: GraphExpansionSlowP95
        expr: histogram_quantile(0.95, rate(graph_expansion_duration_seconds_bucket[5m])) > 0.3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Graph expansion P95 latency is high"
          description: "P95 latency is {{ $value | printf \"%.3f\" }}s (threshold: 0.3s)"

  - name: mcp_v4_cost_alerts
    rules:
      # Daily cost limit
      - alert: OpenAICostHighDaily
        expr: increase(openai_cost_usd[24h]) > 10
        labels:
          severity: warning
        annotations:
          summary: "OpenAI daily cost is high"
          description: "Daily cost: ${{ $value | printf \"%.2f\" }}"

      # Entity dedup cost spike
      - alert: EntityDedupCostSpike
        expr: rate(entity_dedup_cost_usd[1h]) * 24 > 5
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Entity deduplication cost is spiking"
          description: "Projected daily cost: ${{ $value | printf \"%.2f\" }}"
```

---

## Grafana Dashboards

### V4 Overview Dashboard

Import `v4-overview-dashboard.json` or create with these panels:

#### Row 1: Entity Resolution

1. **Entity Resolution Rate** (Graph)
   ```promql
   rate(entity_resolution_total[5m])
   ```

2. **Entity Resolution Decisions** (Pie Chart)
   ```promql
   sum by (decision) (increase(entity_resolution_total[24h]))
   ```

3. **Entity Resolution Latency** (Heatmap)
   ```promql
   rate(entity_resolution_duration_seconds_bucket[5m])
   ```

4. **Entities Needing Review** (Stat)
   ```promql
   entity_needs_review_total
   ```

#### Row 2: Graph Operations

1. **Graph Expansion Rate** (Graph)
   ```promql
   rate(graph_expansion_total[5m])
   ```

2. **Graph Expansion Latency P50/P95/P99** (Graph)
   ```promql
   histogram_quantile(0.5, rate(graph_expansion_duration_seconds_bucket[5m]))
   histogram_quantile(0.95, rate(graph_expansion_duration_seconds_bucket[5m]))
   histogram_quantile(0.99, rate(graph_expansion_duration_seconds_bucket[5m]))
   ```

3. **Graph Node/Edge Counts** (Stat)
   ```promql
   graph_node_count
   graph_edge_count
   ```

4. **Graph Health Status** (Stat with color)
   ```promql
   graph_health_status
   ```

#### Row 3: Hybrid Search V4

1. **Search Request Rate by Type** (Graph)
   ```promql
   sum by (graph_expand) (rate(hybrid_search_v4_total[5m]))
   ```

2. **Search Latency Breakdown** (Stacked Graph)
   ```promql
   rate(hybrid_search_v4_duration_seconds_sum{phase="primary"}[5m]) / rate(hybrid_search_v4_duration_seconds_count{phase="primary"}[5m])
   rate(hybrid_search_v4_duration_seconds_sum{phase="graph"}[5m]) / rate(hybrid_search_v4_duration_seconds_count{phase="graph"}[5m])
   ```

3. **Results Count Distribution** (Histogram)
   ```promql
   rate(hybrid_search_v4_primary_results_bucket[5m])
   rate(hybrid_search_v4_related_results_bucket[5m])
   ```

#### Row 4: Cost Tracking

1. **Daily OpenAI Cost** (Stat)
   ```promql
   increase(openai_cost_usd[24h])
   ```

2. **Cost by Type** (Pie Chart)
   ```promql
   sum by (type) (increase(openai_cost_usd[24h]))
   ```

3. **Token Usage Rate** (Graph)
   ```promql
   rate(openai_tokens_total[5m])
   ```

---

## Logging Configuration

### Structured Logging Format

V4 logs are structured JSON for easy parsing:

```json
{
  "timestamp": "2025-12-28T12:34:56.789Z",
  "level": "INFO",
  "service": "mcp-server",
  "version": "4.0.0",
  "event": "entity_resolved",
  "entity_id": "uuid",
  "canonical_name": "Alice Chen",
  "entity_type": "person",
  "is_new": true,
  "decision": "new",
  "candidate_count": 0,
  "duration_ms": 150,
  "trace_id": "abc123"
}
```

### Key Log Events

| Event | Level | Description |
|-------|-------|-------------|
| `entity_resolved` | INFO | Entity resolution completed |
| `entity_merged` | INFO | Entity merged with existing |
| `entity_uncertain` | WARN | Entity created with needs_review=true |
| `entity_resolution_failed` | ERROR | Entity resolution failed |
| `graph_expansion_completed` | INFO | Graph expansion query completed |
| `graph_expansion_timeout` | WARN | Graph query timed out |
| `graph_upsert_completed` | INFO | Graph node/edge upserted |
| `llm_dedup_call` | DEBUG | LLM deduplication call made |
| `embedding_generated` | DEBUG | Entity embedding generated |

### Log Aggregation (Loki/ELK)

#### Loki LogQL Queries

```logql
# Entity resolution errors
{service="mcp-server"} |= "entity_resolution_failed"

# Slow entity resolutions (>200ms)
{service="mcp-server"} | json | event="entity_resolved" | duration_ms > 200

# Graph expansion timeouts
{service="mcp-server"} |= "graph_expansion_timeout"

# Uncertain entity decisions
{service="event-worker"} | json | event="entity_uncertain"
```

#### Elasticsearch Queries

```json
// Entity resolution errors in last hour
{
  "query": {
    "bool": {
      "must": [
        { "match": { "event": "entity_resolution_failed" } },
        { "range": { "@timestamp": { "gte": "now-1h" } } }
      ]
    }
  }
}

// Slow graph expansions
{
  "query": {
    "bool": {
      "must": [
        { "match": { "event": "graph_expansion_completed" } },
        { "range": { "duration_ms": { "gte": 300 } } }
      ]
    }
  }
}
```

---

## Health Check Endpoints

### V4 Health Endpoints

| Endpoint | Description | Response |
|----------|-------------|----------|
| `GET /health` | Overall service health | `{"status": "healthy", "version": "4.0.0"}` |
| `GET /health/graph` | Graph service health | `{"status": "healthy", "age_enabled": true, ...}` |
| `GET /health/entity-resolution` | Entity resolution health | `{"status": "healthy", ...}` |
| `GET /health/detailed` | Full health details | All subsystem statuses |

### Graph Health Check Response

```json
{
  "status": "healthy",
  "age_enabled": true,
  "graph_exists": true,
  "entity_node_count": 1250,
  "event_node_count": 5430,
  "acted_in_edge_count": 8200,
  "about_edge_count": 6100,
  "possibly_same_edge_count": 45,
  "last_check": "2025-12-28T12:34:56Z"
}
```

### Entity Resolution Health Check Response

```json
{
  "status": "healthy",
  "embedding_service": "ok",
  "pg_connection": "ok",
  "openai_connection": "ok",
  "entity_count": 1250,
  "pending_review_count": 12,
  "avg_resolution_ms": 145,
  "last_check": "2025-12-28T12:34:56Z"
}
```

---

## Operational Runbooks

### High Entity Resolution Latency

**Symptoms:**
- `EntityResolutionSlowP95` alert firing
- User reports slow artifact ingestion

**Investigation:**
1. Check which phase is slow:
   ```promql
   rate(entity_resolution_duration_seconds_sum{phase="embedding"}[5m]) / rate(entity_resolution_duration_seconds_count{phase="embedding"}[5m])
   rate(entity_resolution_duration_seconds_sum{phase="llm"}[5m]) / rate(entity_resolution_duration_seconds_count{phase="llm"}[5m])
   ```

2. If embedding phase slow:
   - Check OpenAI API status
   - Check network latency to OpenAI
   - Consider reducing batch size

3. If LLM phase slow:
   - Check OpenAI API status
   - Review candidate count (too many candidates = more LLM calls)
   - Consider increasing similarity threshold

4. If DB phase slow:
   - Check PostgreSQL connection pool
   - Check pgvector index health
   - Consider REINDEX CONCURRENTLY

**Resolution:**
- Increase `ENTITY_SIMILARITY_THRESHOLD` to reduce candidates
- Reduce `ENTITY_MAX_CANDIDATES`
- Scale event-worker replicas

### Graph Expansion Timeouts

**Symptoms:**
- `GraphExpansionTimeoutHigh` alert firing
- Users report missing related context

**Investigation:**
1. Check graph size:
   ```sql
   SELECT * FROM get_graph_stats();
   ```

2. Check if specific queries are slow:
   ```logql
   {service="mcp-server"} | json | event="graph_expansion_timeout"
   ```

3. Check PostgreSQL load:
   ```sql
   SELECT * FROM pg_stat_activity WHERE state = 'active';
   ```

**Resolution:**
- Increase `V4_GRAPH_QUERY_TIMEOUT_MS` (temporarily)
- Reduce `V4_GRAPH_BUDGET_DEFAULT`
- Add indexes if missing
- Consider graph partitioning for large graphs

### High Entity Review Queue

**Symptoms:**
- `EntityReviewQueueHigh` alert firing
- `entity_needs_review_total` growing

**Investigation:**
1. Check why entities are uncertain:
   ```sql
   SELECT entity_type, COUNT(*)
   FROM entity
   WHERE needs_review = true
   GROUP BY entity_type;
   ```

2. Review recent uncertain decisions:
   ```logql
   {service="event-worker"} | json | event="entity_uncertain" | line_format "{{.canonical_name}}: {{.reason}}"
   ```

**Resolution:**
- Manual review via admin interface
- Adjust similarity threshold if too conservative
- Improve entity extraction prompts for better context

---

## Performance Baselines

### Expected Latencies (P95)

| Operation | Expected P95 | Alert Threshold |
|-----------|-------------|-----------------|
| Entity resolution (total) | <200ms | >200ms |
| Entity embedding | <100ms | >150ms |
| Entity candidate search | <50ms | >100ms |
| LLM confirmation | <500ms | >1000ms |
| Graph expansion | <300ms | >300ms |
| Hybrid search (no graph) | <500ms | >500ms |
| Hybrid search (with graph) | <800ms | >800ms |

### Expected Throughput

| Operation | Expected Rate | Alert Threshold |
|-----------|--------------|-----------------|
| Entity resolutions | 10-50/min | <5/min (stuck) |
| Graph upserts | 50-200/min | <20/min (stuck) |
| Hybrid searches | varies | - |

---

## Appendix: Prometheus Metric Definitions

```python
# In mcp-server/src/metrics.py

from prometheus_client import Counter, Histogram, Gauge

# Entity Resolution
entity_resolution_total = Counter(
    'entity_resolution_total',
    'Total entity resolutions',
    ['decision']
)

entity_resolution_duration = Histogram(
    'entity_resolution_duration_seconds',
    'Entity resolution duration by phase',
    ['phase'],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0]
)

entity_dedup_candidates = Histogram(
    'entity_dedup_candidates_found',
    'Deduplication candidates found',
    buckets=[0, 1, 2, 3, 5, 10, 20]
)

entity_dedup_llm_calls = Counter(
    'entity_dedup_llm_calls_total',
    'LLM calls for entity deduplication',
    ['decision']
)

entity_needs_review = Gauge(
    'entity_needs_review_total',
    'Entities needing manual review'
)

# Graph
graph_expansion_total = Counter(
    'graph_expansion_total',
    'Graph expansion requests',
    ['status']
)

graph_expansion_duration = Histogram(
    'graph_expansion_duration_seconds',
    'Graph expansion query duration',
    buckets=[0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5]
)

graph_node_count = Gauge(
    'graph_node_count',
    'Nodes in graph',
    ['type']
)

graph_edge_count = Gauge(
    'graph_edge_count',
    'Edges in graph',
    ['type']
)

graph_health = Gauge(
    'graph_health_status',
    'Graph health status (1=healthy, 0=unhealthy)'
)

# Cost
openai_tokens = Counter(
    'openai_tokens_total',
    'OpenAI tokens used',
    ['type', 'model']
)

openai_cost = Counter(
    'openai_cost_usd',
    'Estimated OpenAI cost in USD',
    ['type']
)
```

---

**Document Owner:** DevOps Engineer
**Last Updated:** 2025-12-28
