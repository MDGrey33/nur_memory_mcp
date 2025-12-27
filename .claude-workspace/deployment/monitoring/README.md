# Monitoring Setup for MCP Memory

## Current Status

The MCP Memory V1 services do not currently expose Prometheus metrics endpoints. This directory contains templates and guidance for future monitoring implementation.

## Available Monitoring

### 1. Docker Health Checks

All services include Docker health checks that can be monitored:

```bash
# Check health status
make health

# Or directly
docker ps --format "table {{.Names}}\t{{.Status}}"
```

### 2. Log Monitoring

All services log to Docker's JSON file driver with rotation:

```bash
# View real-time logs
make logs

# Search for errors
docker logs --since 1h chroma-prod 2>&1 | grep -i error

# Export logs for analysis
docker logs chroma-prod > /tmp/chroma-logs.txt
```

### 3. Resource Monitoring

Monitor container resource usage:

```bash
# Real-time resource stats
make resources

# Or directly
docker stats chroma-prod agent-app-prod chroma-mcp-prod
```

### 4. Health Check Script

Automated health checking:

```bash
# Run comprehensive health check
./scripts/health-check.sh

# Automate with cron
# Add to crontab:
*/5 * * * * /opt/mcp-memory/deployment/scripts/health-check.sh >> /var/log/mcp-health.log 2>&1
```

## Future Monitoring Implementation

### Phase 1: Basic Metrics (V2)

Add Prometheus metrics endpoints to services:

**Agent App:**
- Request count and latency
- Memory operations (append, recall, write)
- Error rates
- Active sessions

**ChromaDB:**
- Query performance
- Collection sizes
- Connection pool metrics

### Phase 2: Full Observability Stack (V3)

Implement complete monitoring solution:

1. **Metrics:** Prometheus + Grafana
2. **Logs:** ELK Stack (Elasticsearch, Logstash, Kibana)
3. **Traces:** Jaeger or Zipkin
4. **Alerting:** Alertmanager

### Phase 3: Production Monitoring (V3+)

- Application Performance Monitoring (APM)
- Synthetic monitoring
- User experience monitoring
- SLA/SLO tracking

## Quick Start (When Metrics Are Available)

### 1. Add Prometheus Service

Add to `docker-compose.prod.yml`:

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    restart: unless-stopped
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
    ports:
      - "127.0.0.1:9090:9090"  # Bind to localhost only
    networks:
      - mcp-memory-network

volumes:
  prometheus_data:
```

### 2. Add Grafana Service

Add to `docker-compose.prod.yml`:

```yaml
services:
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=changeme
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "127.0.0.1:3000:3000"  # Bind to localhost only
    networks:
      - mcp-memory-network
    depends_on:
      - prometheus

volumes:
  grafana_data:
```

### 3. Add cAdvisor (Docker Metrics)

Add to `docker-compose.prod.yml`:

```yaml
services:
  cadvisor:
    image: gcr.io/cadvisor/cadvisor:latest
    container_name: cadvisor
    restart: unless-stopped
    privileged: true
    devices:
      - /dev/kmsg
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    ports:
      - "127.0.0.1:8080:8080"
    networks:
      - mcp-memory-network
```

### 4. Start Monitoring Stack

```bash
# Start services
docker-compose -f docker-compose.prod.yml up -d

# Access Grafana
open http://localhost:3001
# Login: admin / changeme

# Add Prometheus data source:
# Configuration > Data Sources > Add Prometheus
# URL: http://prometheus:9090
```

## Monitoring Best Practices

### 1. What to Monitor

**System Metrics:**
- CPU usage
- Memory usage
- Disk I/O
- Network I/O

**Application Metrics:**
- Request rate
- Error rate
- Response time (latency)
- Saturation (queue depth)

**Business Metrics:**
- Active users/sessions
- Memory operations per second
- Data growth rate

### 2. Alerting Rules

Create alert rules in `monitoring/alerts.yml`:

```yaml
groups:
  - name: mcp_memory_alerts
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} errors/sec"

      - alert: HighMemoryUsage
        expr: container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage"
          description: "Memory usage is {{ $value }}%"

      - alert: ServiceDown
        expr: up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Service is down"
          description: "{{ $labels.job }} has been down for 2 minutes"
```

### 3. Dashboard Examples

**System Dashboard:**
- Container CPU usage over time
- Container memory usage over time
- Network I/O
- Disk usage

**Application Dashboard:**
- Request rate by operation
- Error rate by operation
- Response time percentiles (p50, p95, p99)
- Active sessions

**Business Dashboard:**
- Total memories stored
- Average memories per conversation
- Most active users
- Data growth trends

## Log Management

### Centralized Logging

For production, consider centralized logging:

**Option 1: ELK Stack**
```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.x
    environment:
      - discovery.type=single-node
    volumes:
      - elasticsearch_data:/usr/share/elasticsearch/data

  logstash:
    image: docker.elastic.co/logstash/logstash:8.x
    volumes:
      - ./monitoring/logstash.conf:/usr/share/logstash/pipeline/logstash.conf

  kibana:
    image: docker.elastic.co/kibana/kibana:8.x
    ports:
      - "127.0.0.1:5601:5601"
```

**Option 2: Cloud Services**
- DataDog
- New Relic
- Splunk
- Sumo Logic

### Structured Logging

Ensure all logs are in JSON format for easy parsing:

```python
# Python logging configuration
import logging
import json_log_formatter

formatter = json_log_formatter.JSONFormatter()
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(handler)
```

## Alerting Channels

Configure notification channels:

1. **Email** - For non-urgent alerts
2. **Slack/Teams** - For team notifications
3. **PagerDuty** - For on-call incidents
4. **SMS** - For critical alerts

## SLA/SLO Monitoring

Define and track Service Level Objectives:

**Example SLOs:**
- Availability: 99.9% uptime
- Latency: p95 < 200ms
- Error Rate: < 0.1%

**Track with Prometheus:**
```promql
# Availability (over 30 days)
avg_over_time(up[30d]) * 100

# Latency p95
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Error rate
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])
```

## Resources

- **Prometheus:** https://prometheus.io/docs/
- **Grafana:** https://grafana.com/docs/
- **cAdvisor:** https://github.com/google/cadvisor
- **Docker Logging:** https://docs.docker.com/config/containers/logging/
- **ELK Stack:** https://www.elastic.co/elastic-stack

---

**Note:** This is a planning document. Actual metrics implementation will be in V2 or later.
