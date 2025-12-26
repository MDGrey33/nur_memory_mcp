#!/bin/bash

# MCP Memory - Health Check Script
# Checks health of all services

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

check_container_running() {
    local container=$1
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        return 0
    else
        return 1
    fi
}

check_container_healthy() {
    local container=$1
    local health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "none")

    if [ "$health" = "healthy" ]; then
        return 0
    else
        return 1
    fi
}

check_http_endpoint() {
    local url=$1
    local name=$2

    if curl -sf "$url" > /dev/null 2>&1; then
        log_success "$name: $url is responding"
        return 0
    else
        log_error "$name: $url is not responding"
        return 1
    fi
}

# Detect environment
if docker ps | grep -q "chroma-prod"; then
    ENV="production"
    CHROMA_CONTAINER="chroma-prod"
    CHROMA_MCP_CONTAINER="chroma-mcp-prod"
    AGENT_CONTAINER="agent-app-prod"
elif docker ps | grep -q "chroma-dev"; then
    ENV="development"
    CHROMA_CONTAINER="chroma-dev"
    CHROMA_MCP_CONTAINER="chroma-mcp-dev"
    AGENT_CONTAINER="agent-app-dev"
else
    log_error "No MCP Memory services are running"
    echo "Start with 'make dev' or 'make prod'"
    exit 1
fi

log_info "Health Check - $ENV environment"
echo "========================================"
echo ""

# Overall status
OVERALL_HEALTHY=true

# Check ChromaDB
echo "ChromaDB Service:"
echo "-------------------"
if check_container_running "$CHROMA_CONTAINER"; then
    log_success "Container $CHROMA_CONTAINER is running"

    # Check health status
    if check_container_healthy "$CHROMA_CONTAINER"; then
        log_success "Container is healthy"
    else
        log_warn "Container is not healthy yet (may be starting)"
        OVERALL_HEALTHY=false
    fi

    # Check HTTP endpoint (only in dev, or via docker exec in prod)
    if [ "$ENV" = "development" ]; then
        if check_http_endpoint "http://localhost:8000/api/v1/heartbeat" "ChromaDB API"; then
            :
        else
            OVERALL_HEALTHY=false
        fi
    else
        # In production, check via docker exec
        if docker exec "$CHROMA_CONTAINER" curl -sf http://localhost:8000/api/v1/heartbeat > /dev/null 2>&1; then
            log_success "ChromaDB API: Internal endpoint responding"
        else
            log_error "ChromaDB API: Internal endpoint not responding"
            OVERALL_HEALTHY=false
        fi
    fi

    # Check resource usage
    STATS=$(docker stats --no-stream --format "{{.CPUPerc}}\t{{.MemUsage}}" "$CHROMA_CONTAINER")
    CPU=$(echo "$STATS" | cut -f1)
    MEM=$(echo "$STATS" | cut -f2)
    log_info "Resource usage: CPU: $CPU, Memory: $MEM"

else
    log_error "Container $CHROMA_CONTAINER is not running"
    OVERALL_HEALTHY=false
fi
echo ""

# Check chroma-mcp
echo "Chroma MCP Gateway:"
echo "-------------------"
if check_container_running "$CHROMA_MCP_CONTAINER"; then
    log_success "Container $CHROMA_MCP_CONTAINER is running"

    # Check resource usage
    STATS=$(docker stats --no-stream --format "{{.CPUPerc}}\t{{.MemUsage}}" "$CHROMA_MCP_CONTAINER")
    CPU=$(echo "$STATS" | cut -f1)
    MEM=$(echo "$STATS" | cut -f2)
    log_info "Resource usage: CPU: $CPU, Memory: $MEM"
else
    log_error "Container $CHROMA_MCP_CONTAINER is not running"
    OVERALL_HEALTHY=false
fi
echo ""

# Check agent-app
echo "Agent Application:"
echo "-------------------"
if check_container_running "$AGENT_CONTAINER"; then
    log_success "Container $AGENT_CONTAINER is running"

    # Check health status
    if check_container_healthy "$AGENT_CONTAINER"; then
        log_success "Container is healthy"
    else
        log_warn "Container is not healthy yet (may be starting)"
        OVERALL_HEALTHY=false
    fi

    # Check resource usage
    STATS=$(docker stats --no-stream --format "{{.CPUPerc}}\t{{.MemUsage}}" "$AGENT_CONTAINER")
    CPU=$(echo "$STATS" | cut -f1)
    MEM=$(echo "$STATS" | cut -f2)
    log_info "Resource usage: CPU: $CPU, Memory: $MEM"
else
    log_error "Container $AGENT_CONTAINER is not running"
    OVERALL_HEALTHY=false
fi
echo ""

# Check Docker volumes
echo "Data Volumes:"
echo "-------------------"
if [ "$ENV" = "production" ]; then
    VOLUME="mcp_memory_chroma_data_prod"
else
    VOLUME="mcp_memory_chroma_data_dev"
fi

if docker volume inspect "$VOLUME" > /dev/null 2>&1; then
    log_success "Volume $VOLUME exists"

    # Get volume size (requires mounting)
    VOLUME_SIZE=$(docker run --rm -v "$VOLUME":/data alpine du -sh /data 2>/dev/null | cut -f1 || echo "unknown")
    log_info "Volume size: $VOLUME_SIZE"
else
    log_error "Volume $VOLUME does not exist"
    OVERALL_HEALTHY=false
fi
echo ""

# Check Docker network
echo "Network:"
echo "-------------------"
if [ "$ENV" = "production" ]; then
    NETWORK="mcp-memory-prod-network"
else
    NETWORK="mcp-memory-dev-network"
fi

if docker network inspect "$NETWORK" > /dev/null 2>&1; then
    log_success "Network $NETWORK exists"

    # Count connected containers
    CONNECTED=$(docker network inspect "$NETWORK" --format='{{len .Containers}}')
    log_info "Connected containers: $CONNECTED"
else
    log_error "Network $NETWORK does not exist"
    OVERALL_HEALTHY=false
fi
echo ""

# Recent errors in logs
echo "Recent Errors:"
echo "-------------------"
ERROR_COUNT=0

for container in "$CHROMA_CONTAINER" "$CHROMA_MCP_CONTAINER" "$AGENT_CONTAINER"; do
    if check_container_running "$container"; then
        ERRORS=$(docker logs --since 5m "$container" 2>&1 | grep -i "error" | wc -l)
        if [ "$ERRORS" -gt 0 ]; then
            log_warn "$container: $ERRORS errors in last 5 minutes"
            ERROR_COUNT=$((ERROR_COUNT + ERRORS))
        else
            log_success "$container: No errors in last 5 minutes"
        fi
    fi
done
echo ""

# Overall status
echo "Overall Status:"
echo "========================================"
if [ "$OVERALL_HEALTHY" = true ] && [ "$ERROR_COUNT" -eq 0 ]; then
    log_success "All services are healthy!"
    exit 0
elif [ "$OVERALL_HEALTHY" = true ]; then
    log_warn "Services are running but there are recent errors"
    exit 1
else
    log_error "Some services are unhealthy"
    exit 1
fi
