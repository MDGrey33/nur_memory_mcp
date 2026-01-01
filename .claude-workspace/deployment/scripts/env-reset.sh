#!/bin/bash
# ==============================================================================
# env-reset.sh - Reset MCP Memory Server test environment
# ==============================================================================
#
# Resets the test environment by removing all data and restarting services.
# This is useful for ensuring clean test runs.
#
# SAFETY: This script will NOT run against production.
#
# Usage:
#   ./scripts/env-reset.sh [environment]
#
# Arguments:
#   environment   Target environment: test (default) or staging
#                 NOTE: 'prod' is not allowed
#
# Examples:
#   ./scripts/env-reset.sh         # Reset test environment
#   ./scripts/env-reset.sh staging # Reset staging environment
#
# Exit codes:
#   0 - Success
#   1 - Invalid environment or production blocked
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
    esac
}

get_chroma_port() {
    case "$1" in
        dev) echo 8001 ;;
    esac
}

get_postgres_port() {
    case "$1" in
        dev) echo 5432 ;;
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
        dev)
            log_info "Target environment: $ENVIRONMENT"
            ;;
        prod|production)
            log_error "CANNOT RESET PRODUCTION ENVIRONMENT!"
            log_error "This operation would delete all production data."
            log_error "If you really need to reset production, do it manually."
            exit 1
            ;;
        *)
            log_error "Invalid environment: $ENVIRONMENT"
            echo "Valid options: dev (prod cannot be reset via script)"
            exit 1
            ;;
    esac
}

confirm_reset() {
    echo ""
    log_warn "This will DELETE ALL DATA in the $ENVIRONMENT environment!"
    log_warn "Including: PostgreSQL data, ChromaDB vectors, and extracted events."
    echo ""

    read -p "Are you sure you want to proceed? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        log_info "Reset cancelled"
        exit 0
    fi
}

get_compose_file() {
    case "$ENVIRONMENT" in
        dev)
            echo "$DEPLOYMENT_DIR/docker-compose.local.yml"
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

stop_and_remove() {
    local compose_file=$(get_compose_file)
    local env_file=$(get_env_file)
    local project_name="mcp-memory-$ENVIRONMENT"

    log_info "Stopping services and removing volumes..."

    cd "$DEPLOYMENT_DIR"

    # Build command array to handle paths with spaces
    local -a cmd=(docker compose -f "$compose_file" -p "$project_name")

    if [[ -n "$env_file" ]]; then
        cmd+=(--env-file "$env_file")
    fi

    # Stop and remove volumes
    "${cmd[@]}" down -v --remove-orphans 2>/dev/null || true

    log_info "Services stopped and volumes removed"
}

start_services() {
    local compose_file=$(get_compose_file)
    local env_file=$(get_env_file)
    local project_name="mcp-memory-$ENVIRONMENT"

    log_info "Starting fresh services..."

    cd "$DEPLOYMENT_DIR"

    # Build command array to handle paths with spaces
    local -a cmd=(docker compose -f "$compose_file" -p "$project_name")

    if [[ -n "$env_file" ]]; then
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

    # Check MCP server
    if ! curl -sf "http://localhost:$mcp_port/health" > /dev/null 2>&1; then
        return 1
    fi

    # Check ChromaDB
    if ! curl -sf "http://localhost:$chroma_port/api/v2/heartbeat" > /dev/null 2>&1; then
        return 1
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
    echo "Environment Reset Complete: $ENVIRONMENT"
    echo "=============================================="
    echo "MCP Server:  http://localhost:$mcp_port"
    echo "ChromaDB:    http://localhost:$chroma_port"
    echo "PostgreSQL:  localhost:$postgres_port"
    echo ""
    echo "All data has been cleared."
    echo "=============================================="
    echo ""
}

# ==============================================================================
# Main
# ==============================================================================

main() {
    echo ""
    echo "=============================================="
    echo "MCP Memory Server - Environment Reset"
    echo "=============================================="
    echo ""

    validate_environment
    confirm_reset
    stop_and_remove
    start_services
    wait_for_healthy
    print_status

    log_info "Environment $ENVIRONMENT has been reset!"
}

main
