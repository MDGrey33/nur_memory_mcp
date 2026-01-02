#!/bin/bash
# ==============================================================================
# env-down.sh - Stop MCP Memory Server environment
# ==============================================================================
#
# Stops the specified environment (test, staging, prod) using Docker Compose.
# Optionally removes volumes for complete cleanup.
#
# Usage:
#   ./scripts/env-down.sh [environment] [--volumes|-v]
#
# Arguments:
#   environment   Target environment: prod (default), staging, or test
#   --volumes|-v  Also remove volumes (data)
#
# Examples:
#   ./scripts/env-down.sh           # Stop prod environment
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
DEPLOYMENT_DIR="$(dirname "$SCRIPT_DIR")"

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
            prod|staging|test)
                ENVIRONMENT="$1"
                shift
                ;;
            -v|--volumes)
                REMOVE_VOLUMES=true
                shift
                ;;
            -h|--help)
                echo "Usage: $0 [environment] [--volumes|-v]"
                echo ""
                echo "Arguments:"
                echo "  environment   prod, staging, or test (default: prod)"
                echo "  --volumes|-v  Also remove volumes (data)"
                exit 0
                ;;
            *)
                log_error "Unknown argument: $1"
                exit 1
                ;;
        esac
    done

    # Default to prod if not specified
    if [[ -z "$ENVIRONMENT" ]]; then
        ENVIRONMENT="prod"
    fi
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

stop_services() {
    local compose_file="$DEPLOYMENT_DIR/docker-compose.yml"
    local base_env="$DEPLOYMENT_DIR/.env"
    local env_file="$DEPLOYMENT_DIR/.env.$ENVIRONMENT"
    local project_name="mcp-memory-$ENVIRONMENT"

    log_info "Stopping services..."
    log_info "  Project name: $project_name"

    cd "$DEPLOYMENT_DIR"

    # Build command with both env files
    local -a cmd=(docker compose -f "$compose_file" -p "$project_name")

    if [[ -f "$base_env" ]]; then
        cmd+=(--env-file "$base_env")
    fi

    if [[ -f "$env_file" ]]; then
        cmd+=(--env-file "$env_file")
    fi

    cmd+=(down)

    if [[ "$REMOVE_VOLUMES" == "true" ]]; then
        log_warn "Removing volumes (data will be deleted)"
        cmd+=(-v)
    fi

    if ! "${cmd[@]}"; then
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

    log_info "Environment $ENVIRONMENT stopped!"
}

main "$@"
