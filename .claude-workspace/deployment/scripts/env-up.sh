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
#   environment   Target environment: prod (default), staging, or test
#
# Examples:
#   ./scripts/env-up.sh           # Start prod environment
#   ./scripts/env-up.sh prod      # Start prod environment
#   ./scripts/env-up.sh staging   # Start staging environment
#   ./scripts/env-up.sh test      # Start test environment
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
ENVIRONMENT="${1:-prod}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$(dirname "$SCRIPT_DIR")"
HEALTH_TIMEOUT=120

# Port lookup functions per ADR-005
# prod: 3001, 8001, 5432
# staging: 3101, 8101, 5532
# test: 3201, 8201, 5632
get_mcp_port() {
    case "$1" in
        prod) echo 3001 ;;
        staging) echo 3101 ;;
        test) echo 3201 ;;
    esac
}

get_chroma_port() {
    case "$1" in
        prod) echo 8001 ;;
        staging) echo 8101 ;;
        test) echo 8201 ;;
    esac
}

get_postgres_port() {
    case "$1" in
        prod) echo 5432 ;;
        staging) echo 5532 ;;
        test) echo 5632 ;;
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
        prod|staging|test)
            log_info "Target environment: $ENVIRONMENT"
            ;;
        *)
            log_error "Invalid environment: $ENVIRONMENT"
            echo "Valid options: prod, staging, test"
            exit 1
            ;;
    esac
}

get_env_file() {
    echo "$DEPLOYMENT_DIR/.env.$ENVIRONMENT"
}

start_services() {
    local compose_file="$DEPLOYMENT_DIR/docker-compose.yml"
    local base_env="$DEPLOYMENT_DIR/.env"
    local env_file=$(get_env_file)
    local project_name="mcp-memory-$ENVIRONMENT"

    if [[ ! -f "$compose_file" ]]; then
        log_error "Compose file not found: $compose_file"
        exit 2
    fi

    if [[ ! -f "$base_env" ]]; then
        log_error "Base env file not found: $base_env (contains OPENAI_API_KEY)"
        exit 2
    fi

    if [[ ! -f "$env_file" ]]; then
        log_error "Environment file not found: $env_file"
        exit 2
    fi

    log_info "Starting services..."
    log_info "  Compose file: $compose_file"
    log_info "  Base env: $base_env"
    log_info "  Env file: $env_file"
    log_info "  Project name: $project_name"

    cd "$DEPLOYMENT_DIR"

    # Load both .env (secrets) and .env.{environment} (config)
    # The second --env-file overrides values from the first
    if ! docker compose -f "$compose_file" --env-file "$base_env" --env-file "$env_file" -p "$project_name" up -d; then
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

    # Check Postgres (optional, may not have pg_isready)
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
    echo "MCP Server:  http://localhost:$mcp_port/mcp/"
    echo "Health:      http://localhost:$mcp_port/health"
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
