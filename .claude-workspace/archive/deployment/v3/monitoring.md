# MCP Memory Server V3: Monitoring Guide

**Version:** 3.0
**Date:** 2025-12-27
**Status:** Production Ready

---

## Table of Contents

1. [Overview](#overview)
2. [Key Metrics](#key-metrics)
3. [Alerting Thresholds](#alerting-thresholds)
4. [Log Aggregation](#log-aggregation)
5. [Monitoring Stack Setup](#monitoring-stack-setup)
6. [Dashboards](#dashboards)
7. [Performance Tuning](#performance-tuning)

---

## Overview

### Monitoring Philosophy

V3 monitoring focuses on three key areas:

1. **Service Health**: Are all containers running and healthy?
2. **Job Queue Health**: Are jobs being processed successfully?
3. **Resource Utilization**: Are we approaching capacity limits?

### Quick Health Check

```bash
# Run comprehensive health check
docker-compose exec mcp-server python healthcheck.py --service all

# Check job queue status
docker-compose exec postgres psql -U events -d events -c \
  "SELECT status, COUNT(*) FROM event_jobs GROUP BY status;"
```

---

## Key Metrics

### 1. Service Availability

| Metric | Description | Target | Source |
|--------|-------------|--------|--------|
| **Container Uptime** | Time since container started | > 99% | Docker |
| **Health Check Pass Rate** | % of health checks passing | 100% | Health script |
| **Restart Count** | Number of container restarts | 0 per day | Docker events |

**Monitoring**:
```bash
# Check container status
docker-compose ps

# Check restart count
docker inspect --format='{{.RestartCount}}' mcp-server
docker inspect --format='{{.RestartCount}}' event-worker
```

### 2. Job Queue Metrics

| Metric | Description | Target | Alert Threshold |
|--------|-------------|--------|----------------|
| **Pending Jobs** | Jobs waiting to be processed | < 10 | > 50 |
| **Processing Time** | Avg time per job | < 60s | > 300s |
| **Failed Jobs** | Jobs in FAILED state | 0 | > 5 per hour |
| **Retry Rate** | % of jobs requiring retries | < 10% | > 25% |
| **Queue Depth** | Total pending + processing | < 20 | > 100 |

**Monitoring**:
```sql
-- Job status summary
SELECT
    status,
    COUNT(*) as count,
    AVG(attempts) as avg_attempts,
    MAX(attempts) as max_attempts
FROM event_jobs
GROUP BY status;

-- Recent failures
SELECT
    job_id,
    artifact_uid,
    attempts,
    last_error_message,
    created_at
FROM event_jobs
WHERE status = 'FAILED'
ORDER BY created_at DESC
LIMIT 10;

-- Queue depth over time
SELECT
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as jobs_created
FROM event_jobs
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour DESC;

-- Processing time analysis
SELECT
    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_seconds,
    MIN(EXTRACT(EPOCH FROM (updated_at - created_at))) as min_seconds,
    MAX(EXTRACT(EPOCH FROM (updated_at - created_at))) as max_seconds,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (updated_at - created_at))) as p95_seconds
FROM event_jobs
WHERE status = 'DONE'
    AND updated_at > NOW() - INTERVAL '24 hours';
```

### 3. Database Metrics

| Metric | Description | Target | Alert Threshold |
|--------|-------------|--------|----------------|
| **Connection Pool Usage** | Active DB connections | < 80% | > 90% |
| **Query Latency** | Avg query time | < 50ms | > 200ms |
| **Database Size** | Total DB size | Monitor trend | > 80% disk |
| **Index Hit Rate** | % queries using indexes | > 95% | < 90% |
| **Transaction Rate** | Transactions per second | Monitor trend | Large deviation |

**Monitoring**:
```sql
-- Connection count
SELECT
    COUNT(*) as total_connections,
    COUNT(*) FILTER (WHERE state = 'active') as active_connections,
    COUNT(*) FILTER (WHERE state = 'idle') as idle_connections
FROM pg_stat_activity
WHERE datname = 'events';

-- Database size
SELECT
    pg_size_pretty(pg_database_size('events')) as db_size;

-- Table sizes
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as data_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) as index_size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Index usage stats
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;

-- Cache hit ratio
SELECT
    'index hit rate' AS name,
    (sum(idx_blks_hit)) / nullif(sum(idx_blks_hit + idx_blks_read),0) AS ratio
FROM pg_statio_user_indexes
UNION ALL
SELECT
    'table hit rate' AS name,
    sum(heap_blks_hit) / nullif(sum(heap_blks_hit) + sum(heap_blks_read),0) AS ratio
FROM pg_statio_user_tables;
```

### 4. ChromaDB Metrics

| Metric | Description | Target | Alert Threshold |
|--------|-------------|--------|----------------|
| **Collection Size** | Number of vectors stored | Monitor trend | Approaching limit |
| **Query Latency** | Vector search time | < 500ms | > 2s |
| **Disk Usage** | ChromaDB volume size | Monitor trend | > 80% disk |

**Monitoring**:
```bash
# Check ChromaDB collections (via HTTP API)
curl -s http://localhost:8001/api/v1/collections | jq

# Check disk usage
docker exec mcp-chroma du -sh /chroma/chroma
```

### 5. Resource Utilization

| Metric | Description | Target | Alert Threshold |
|--------|-------------|--------|----------------|
| **CPU Usage** | Container CPU % | < 70% | > 90% |
| **Memory Usage** | Container memory % | < 80% | > 95% |
| **Disk I/O** | Read/write ops | Monitor baseline | 10x baseline |
| **Network I/O** | Bytes sent/received | Monitor baseline | 10x baseline |

**Monitoring**:
```bash
# Real-time resource stats
docker stats

# Detailed container stats
docker stats --no-stream mcp-server event-worker postgres chroma

# Disk usage
docker system df -v

# Network stats
docker inspect mcp-network
```

### 6. Application Metrics

| Metric | Description | Target | Alert Threshold |
|--------|-------------|--------|----------------|
| **Ingestion Rate** | Artifacts ingested/min | Monitor trend | Large drop |
| **Event Extraction Rate** | Events extracted/min | Monitor trend | Large drop |
| **Error Rate** | Application errors/min | < 1 | > 10 |
| **OpenAI API Latency** | LLM response time | < 10s | > 30s |
| **OpenAI API Errors** | API failures | 0 | > 5 per hour |

**Monitoring**:
```bash
# Check application logs for errors
docker-compose logs --since 1h mcp-server | grep ERROR
docker-compose logs --since 1h event-worker | grep ERROR

# Count recent ingestions
docker-compose exec postgres psql -U events -d events -c \
  "SELECT COUNT(*) FROM artifact_revision WHERE ingested_at > NOW() - INTERVAL '1 hour';"

# Count recent events
docker-compose exec postgres psql -U events -d events -c \
  "SELECT COUNT(*) FROM semantic_event WHERE created_at > NOW() - INTERVAL '1 hour';"
```

---

## Alerting Thresholds

### Critical Alerts (Immediate Action)

| Alert | Condition | Action |
|-------|-----------|--------|
| **Service Down** | Container not running | Check logs, restart container |
| **Database Down** | Postgres not accepting connections | Check logs, verify volume, restart |
| **Memory Exhausted** | Container using > 95% memory | Check for leaks, increase limits, restart |
| **Disk Full** | > 95% disk usage | Clean old data, expand volume |
| **Job Queue Stalled** | No jobs processed in 5 min | Check worker logs, restart worker |
| **High Error Rate** | > 10 errors/min | Check logs, investigate root cause |

### Warning Alerts (Monitor Closely)

| Alert | Condition | Action |
|-------|-----------|--------|
| **High Queue Depth** | > 50 pending jobs | Consider scaling workers |
| **High Memory** | Container using > 80% memory | Monitor trend, prepare to scale |
| **High CPU** | Container using > 80% CPU | Monitor trend, prepare to scale |
| **Slow Jobs** | Avg processing time > 300s | Check OpenAI API latency |
| **Failed Jobs** | > 5 failed jobs/hour | Check error messages, retry manually |

### Example Alert Rules (Prometheus)

```yaml
groups:
  - name: mcp_memory_alerts
    interval: 30s
    rules:
      # Critical: Service Down
      - alert: MCPServerDown
        expr: up{job="mcp-server"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "MCP Server is down"
          description: "MCP Server has been down for more than 1 minute"

      # Critical: High Job Queue Depth
      - alert: JobQueueDepthHigh
        expr: event_jobs_pending > 50
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Job queue depth is high"
          description: "More than 50 jobs pending for 5 minutes"

      # Warning: High Memory Usage
      - alert: HighMemoryUsage
        expr: container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Container memory usage is high"
          description: "Container using more than 80% memory for 5 minutes"

      # Critical: Database Connection Pool Exhausted
      - alert: DatabaseConnectionPoolExhausted
        expr: pg_stat_activity_count / pg_settings_max_connections > 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Database connection pool near exhaustion"
          description: "More than 90% of DB connections in use"
```

---

## Log Aggregation

### Structured Logging Format

Application logs use structured JSON format:

```json
{
  "timestamp": "2024-03-15T14:30:00Z",
  "level": "INFO",
  "service": "mcp-server",
  "message": "Artifact ingested successfully",
  "artifact_id": "art_abc123",
  "revision_id": "rev_def456",
  "is_chunked": true,
  "num_chunks": 5,
  "duration_ms": 450
}
```

### Centralized Logging with ELK Stack

#### Setup Filebeat

```yaml
# filebeat.yml
filebeat.inputs:
  - type: container
    paths:
      - '/var/lib/docker/containers/*/*.log'
    processors:
      - add_docker_metadata:
          host: "unix:///var/run/docker.sock"

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "mcp-memory-%{+yyyy.MM.dd}"

setup.kibana:
  host: "kibana:5601"
```

#### Docker Compose Addition

```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.0
    environment:
      - discovery.type=single-node
    volumes:
      - es_data:/usr/share/elasticsearch/data
    networks:
      - mcp-network

  kibana:
    image: docker.elastic.co/kibana/kibana:8.11.0
    ports:
      - "5601:5601"
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
    networks:
      - mcp-network

  filebeat:
    image: docker.elastic.co/beats/filebeat:8.11.0
    user: root
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
    networks:
      - mcp-network
```

### Alternative: Grafana Loki

```yaml
services:
  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"
    volumes:
      - loki_data:/loki
    networks:
      - mcp-network

  promtail:
    image: grafana/promtail:latest
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./promtail-config.yml:/etc/promtail/config.yml:ro
    networks:
      - mcp-network
```

---

## Monitoring Stack Setup

### Option 1: Prometheus + Grafana

#### 1. Add Prometheus

Create `prometheus.yml`:
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'docker'
    static_configs:
      - targets: ['host.docker.internal:9323']

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres-exporter:9187']

  - job_name: 'mcp-server'
    static_configs:
      - targets: ['mcp-server:3000']
    metrics_path: '/metrics'
```

#### 2. Add to Docker Compose

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    networks:
      - mcp-network

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    networks:
      - mcp-network

  postgres-exporter:
    image: prometheuscommunity/postgres-exporter:latest
    environment:
      - DATA_SOURCE_NAME=postgresql://events:events@postgres:5432/events?sslmode=disable
    networks:
      - mcp-network

volumes:
  prometheus_data:
  grafana_data:
  loki_data:
```

#### 3. Start Monitoring Stack

```bash
# Start all services including monitoring
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

# Access Grafana at http://localhost:3001
# Username: admin, Password: admin (change after login)

# Access Prometheus at http://localhost:9090
```

---

## Dashboards

### Grafana Dashboard: MCP Memory Overview

#### Panels to Include:

1. **Service Status** (Stat panel)
   - Query: `up{job=~"mcp-server|postgres|chroma"}`
   - Thresholds: 0 (red), 1 (green)

2. **Job Queue Depth** (Graph)
   - Query: `SELECT status, COUNT(*) FROM event_jobs GROUP BY status`
   - Show: PENDING, PROCESSING, DONE, FAILED

3. **Job Processing Rate** (Graph)
   - Query: Jobs completed per minute

4. **CPU Usage** (Graph)
   - Query: `container_cpu_usage_seconds_total{name=~"mcp-.*"}`

5. **Memory Usage** (Graph)
   - Query: `container_memory_usage_bytes{name=~"mcp-.*"}`

6. **Database Connections** (Graph)
   - Query: `pg_stat_activity_count`

7. **Recent Errors** (Table)
   - Query: Last 10 errors from logs

### Example Dashboard JSON

See `dashboards/mcp-memory-overview.json` (to be created separately).

---

## Performance Tuning

### Database Optimization

#### 1. Connection Pooling

```python
# In config.py
PG_POOL_SIZE = 20  # Increase from default 10
PG_POOL_MAX_OVERFLOW = 40  # Increase from default 20
```

#### 2. Query Optimization

```sql
-- Add missing indexes if slow queries detected
CREATE INDEX idx_semantic_event_created_at ON semantic_event (created_at DESC);
CREATE INDEX idx_event_jobs_updated_at ON event_jobs (updated_at DESC);

-- Analyze query plans
EXPLAIN ANALYZE SELECT * FROM semantic_event WHERE category = 'Decision';
```

#### 3. Vacuum Schedule

```bash
# Add to crontab
0 3 * * * docker-compose exec postgres psql -U events -d events -c "VACUUM ANALYZE;"
```

### Worker Tuning

#### 1. Scale Workers

```bash
# Run multiple workers
docker-compose up -d --scale event-worker=3
```

#### 2. Adjust Polling Interval

```bash
# In .env
POLL_INTERVAL_MS=500  # More frequent polling (default: 1000)
```

#### 3. Batch Processing

Consider implementing batch job claiming for high-throughput scenarios.

### Resource Allocation

#### 1. Increase Memory Limits

```yaml
# docker-compose.yml
services:
  mcp-server:
    deploy:
      resources:
        limits:
          memory: 4G  # Increased from 2G
```

#### 2. Add Swap Space

```bash
# On host machine
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## Custom Monitoring Scripts

### Job Queue Monitor Script

```bash
#!/bin/bash
# monitor_queue.sh - Monitor job queue health

ALERT_THRESHOLD=50
POSTGRES_DSN="postgresql://events:events@localhost:5432/events"

# Get queue depth
PENDING=$(docker-compose exec -T postgres psql -U events -d events -t -c \
  "SELECT COUNT(*) FROM event_jobs WHERE status='PENDING';" | tr -d ' ')

echo "Pending jobs: $PENDING"

if [ "$PENDING" -gt "$ALERT_THRESHOLD" ]; then
  echo "WARNING: Queue depth exceeds threshold!"
  # Send alert (email, Slack, PagerDuty, etc.)
fi
```

### Health Check Monitor

```bash
#!/bin/bash
# monitor_health.sh - Continuous health monitoring

while true; do
  docker-compose exec mcp-server python healthcheck.py --service all
  if [ $? -ne 0 ]; then
    echo "Health check failed at $(date)"
    # Send alert
  fi
  sleep 60
done
```

---

## Integration with External Monitoring

### Datadog

```yaml
# datadog-agent.yml
services:
  datadog-agent:
    image: gcr.io/datadoghq/agent:latest
    environment:
      - DD_API_KEY=${DATADOG_API_KEY}
      - DD_SITE=datadoghq.com
      - DD_LOGS_ENABLED=true
      - DD_LOGS_CONFIG_CONTAINER_COLLECT_ALL=true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /proc/:/host/proc/:ro
      - /sys/fs/cgroup/:/host/sys/fs/cgroup:ro
    networks:
      - mcp-network
```

### New Relic

```yaml
services:
  newrelic-infra:
    image: newrelic/infrastructure:latest
    environment:
      - NRIA_LICENSE_KEY=${NEW_RELIC_LICENSE_KEY}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - mcp-network
```

---

**Last Updated**: 2025-12-27
**Version**: 3.0
**Maintainer**: MCP Memory Team
