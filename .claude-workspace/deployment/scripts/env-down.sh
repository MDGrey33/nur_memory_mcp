#!/bin/bash
# ==============================================================================
# env-down.sh - Stop MCP Memory Server environment
# ==============================================================================
#
# Stops the specified environment (test, staging, prod) using Docker Compose.
# Optionally removes volumes for complete cleanup.
#
# Usage:
#   ./scripts/env-down.sh [environment] [--volumes]
#
# Arguments:
#   environment   Target environment: test (default), staging, or prod
#   --volumes     Also remove volumes (data)
#
# Examples:
#   ./scripts/env-down.sh           # Stop test environment
#   ./scripts/env-down.sh staging   # Stop staging environment
#   ./scripts/env-down.sh test -v   # Stop test and remove volumes
#
# Exit codes:
#   0 - Success
#   1 - Invalid environment
#   2 - Docker Compose failed
# ==============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
ENVIRONMENT=""
REMOVE_VOLUMES=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOYMENT_DIR="$PROJECT_ROOT/deployment"

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

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            test|staging|prod)
                ENVIRONMENT="$1"
                ;;
            -v|--volumes)
                REMOVE_VOLUMES=true
                ;;
            -h|--help)
                echo "Usage: $0 [environment] [--volumes]"
                echo ""
                echo "Arguments:"
                echo "  environment   test, staging, or prod (default: test)"
                echo "  --volumes     Remove volumes (data)"
                exit 0
                ;;
            *)
                log_error "Unknown argument: $1"
                exit 1
                ;;
        esac
        shift
    done

    # Default environment
    if [[ -z "$ENVIRONMENT" ]]; then
        ENVIRONMENT="test"
    fi
}

validate_environment() {
    case "$ENVIRONMENT" in
        test|staging|prod)
            log_info "Target environment: $ENVIRONMENT"
            ;;
        *)
            log_error "Invalid environment: $ENVIRONMENT"
            exit 1
            ;;
    esac
}

get_compose_file() {
    case "$ENVIRONMENT" in
        test)
            echo "$DEPLOYMENT_DIR/docker-compose.test.yml"
            ;;
        staging)
            echo "$DEPLOYMENT_DIR/docker-compose.staging.yml"
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

stop_services() {
    local compose_file=$(get_compose_file)
    local env_file=$(get_env_file)
    local project_name="mcp-memory-$ENVIRONMENT"

    if [[ ! -f "$compose_file" ]]; then
        log_warn "Compose file not found: $compose_file"
        log_info "Attempting to stop by project name..."
    fi

    log_info "Stopping services..."

    local cmd="docker compose -f $compose_file -p $project_name"

    if [[ -n "$env_file" ]]; then
        cmd="$cmd --env-file $env_file"
    fi

    cd "$DEPLOYMENT_DIR"

    local down_args="down"
    if [[ "$REMOVE_VOLUMES" == "true" ]]; then
        log_warn "Removing volumes (data will be deleted)"
        down_args="down -v"
    fi

    if ! $cmd $down_args; then
        log_error "Failed to stop Docker Compose services"
        exit 2
    fi

    log_info "Services stopped"
}

# ==============================================================================
# Main
# ==============================================================================

main() {
    echo ""
    echo "=============================================="
    echo "MCP Memory Server - Environment Shutdown"
    echo "=============================================="
    echo ""

    parse_args "$@"
    validate_environment
    stop_services

    if [[ "$REMOVE_VOLUMES" == "true" ]]; then
        log_info "Environment $ENVIRONMENT stopped and data removed"
    else
        log_info "Environment $ENVIRONMENT stopped (data preserved)"
    fi
}

main "$@"
