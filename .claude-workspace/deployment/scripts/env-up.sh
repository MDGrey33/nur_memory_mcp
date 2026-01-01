#!/bin/bash
# ==============================================================================
# env-up.sh - Start MCP Memory Server environment
# ==============================================================================
#
# Starts the specified environment (test, staging, prod) using Docker Compose.
# Waits for all services to be healthy before returning.
#
# Usage:
#   ./scripts/env-up.sh [environment]
#
# Arguments:
#   environment   Target environment: test (default), staging, or prod
#
# Examples:
#   ./scripts/env-up.sh           # Start test environment
#   ./scripts/env-up.sh test      # Start test environment
#   ./scripts/env-up.sh staging   # Start staging environment
#
# Exit codes:
#   0 - Success
#   1 - Invalid environment
#   2 - Docker Compose failed
#   3 - Health check timeout
# ==============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
ENVIRONMENT="${1:-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$DEPLOYMENT_DIR")"
HEALTH_TIMEOUT=120

# Port lookup functions (bash 3.x compatible)
get_mcp_port() {
    case "$1" in
        dev) echo 3001 ;;
        prod) echo 3001 ;;  # Using 3001, change to 3000 if available
    esac
}

get_chroma_port() {
    case "$1" in
        dev) echo 8001 ;;
        prod) echo 8001 ;;
    esac
}

get_postgres_port() {
    case "$1" in
        dev) echo 5432 ;;
        prod) echo 5432 ;;
    esac
}

# ==============================================================================
# Functions
# ==============================================================================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

validate_environment() {
    case "$ENVIRONMENT" in
        dev|prod)
            log_info "Target environment: $ENVIRONMENT"
            ;;
        *)
            log_error "Invalid environment: $ENVIRONMENT"
            echo "Valid options: dev, prod"
            exit 1
            ;;
    esac
}

get_compose_file() {
    case "$ENVIRONMENT" in
        dev)
            echo "$DEPLOYMENT_DIR/docker-compose.local.yml"
            ;;
        prod)
            echo "$DEPLOYMENT_DIR/docker-compose.yml"
            ;;
    esac
}

get_env_file() {
    local env_file="$DEPLOYMENT_DIR/.env.$ENVIRONMENT"
    if [[ -f "$env_file" ]]; then
        echo "$env_file"
    else
        echo ""
    fi
}

start_services() {
    local compose_file=$(get_compose_file)
    local env_file=$(get_env_file)
    local project_name="mcp-memory-$ENVIRONMENT"

    if [[ ! -f "$compose_file" ]]; then
        log_error "Compose file not found: $compose_file"
        exit 2
    fi

    log_info "Starting services..."
    log_info "  Compose file: $compose_file"
    log_info "  Project name: $project_name"

    cd "$DEPLOYMENT_DIR"

    # Build command array to handle paths with spaces
    local -a cmd=(docker compose -f "$compose_file" -p "$project_name")

    if [[ -n "$env_file" ]]; then
        log_info "  Env file: $env_file"
        cmd+=(--env-file "$env_file")
    fi

    cmd+=(up -d)

    if ! "${cmd[@]}"; then
        log_error "Failed to start Docker Compose services"
        exit 2
    fi

    log_info "Services started"
}

check_health() {
    local mcp_port=$(get_mcp_port "$ENVIRONMENT")
    local chroma_port=$(get_chroma_port "$ENVIRONMENT")
    local postgres_port=$(get_postgres_port "$ENVIRONMENT")

    # Check MCP server
    if ! curl -sf "http://localhost:$mcp_port/health" > /dev/null 2>&1; then
        return 1
    fi

    # Check ChromaDB
    if ! curl -sf "http://localhost:$chroma_port/api/v2/heartbeat" > /dev/null 2>&1; then
        return 1
    fi

    # Check Postgres
    if command -v pg_isready &> /dev/null; then
        if ! pg_isready -h localhost -p "$postgres_port" -U events > /dev/null 2>&1; then
            return 1
        fi
    fi

    return 0
}

wait_for_healthy() {
    log_info "Waiting for services to be healthy..."

    local elapsed=0
    local interval=3

    while [[ $elapsed -lt $HEALTH_TIMEOUT ]]; do
        if check_health; then
            log_info "All services are healthy!"
            return 0
        fi

        echo -n "."
        sleep $interval
        elapsed=$((elapsed + interval))
    done

    echo ""
    log_error "Health check timeout after ${HEALTH_TIMEOUT}s"
    exit 3
}

print_status() {
    local mcp_port=$(get_mcp_port "$ENVIRONMENT")
    local chroma_port=$(get_chroma_port "$ENVIRONMENT")
    local postgres_port=$(get_postgres_port "$ENVIRONMENT")

    echo ""
    echo "=============================================="
    echo "Environment: $ENVIRONMENT"
    echo "=============================================="
    echo "MCP Server:  http://localhost:$mcp_port"
    echo "ChromaDB:    http://localhost:$chroma_port"
    echo "PostgreSQL:  localhost:$postgres_port"
    echo "=============================================="
    echo ""
}

# ==============================================================================
# Main
# ==============================================================================

main() {
    echo ""
    echo "=============================================="
    echo "MCP Memory Server - Environment Startup"
    echo "=============================================="
    echo ""

    validate_environment
    start_services
    wait_for_healthy
    print_status

    log_info "Environment $ENVIRONMENT is ready!"
}

main
