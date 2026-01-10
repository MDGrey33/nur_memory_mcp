#!/bin/bash
# ==============================================================================
# version-check.sh - Check and sync deployed version with local code
# ==============================================================================
#
# Compares local server.py __version__ with deployed /health version.
# Auto-rebuilds and restarts if mismatch is detected.
#
# Usage:
#   ./scripts/version-check.sh [environment]
#
# Arguments:
#   environment   Target environment: prod, staging, or test (default: test)
#
# Options:
#   --skip        Skip version check (useful for CI)
#   --quiet       Minimal output
#   --help        Show this help
#
# Exit codes:
#   0 - Versions match or rebuild succeeded
#   1 - Rebuild failed
#   2 - Invalid arguments
# ==============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$(dirname "$SCRIPT_DIR")"

# Default values
ENVIRONMENT="test"
SKIP_CHECK=false
QUIET_MODE=false

# Port lookup functions (bash 3.x compatible)
get_mcp_port() {
    case "$1" in
        test) echo 3201 ;;
        staging) echo 3101 ;;
        prod) echo 3001 ;;
        *) echo 3001 ;;
    esac
}

# ==============================================================================
# Functions
# ==============================================================================

log_info() {
    if [[ "$QUIET_MODE" != "true" ]]; then
        echo -e "${GREEN}[INFO]${NC} $1"
    fi
}

log_warn() {
    if [[ "$QUIET_MODE" != "true" ]]; then
        echo -e "${YELLOW}[WARN]${NC} $1"
    fi
}

log_error() {
    if [[ "$QUIET_MODE" != "true" ]]; then
        echo -e "${RED}[ERROR]${NC} $1"
    fi
}

show_help() {
    echo "Usage: $0 [environment] [options]"
    echo ""
    echo "Check and sync deployed version with local code."
    echo "Auto-rebuilds if versions don't match."
    echo ""
    echo "Arguments:"
    echo "  environment    prod, staging, or test (default: test)"
    echo ""
    echo "Options:"
    echo "  --skip         Skip version check"
    echo "  --quiet, -q    Minimal output"
    echo "  --help, -h     Show this help message"
    echo ""
    echo "Environment variable:"
    echo "  SKIP_VERSION_CHECK=1  Skip version check"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            test|staging|prod)
                ENVIRONMENT="$1"
                ;;
            --skip)
                SKIP_CHECK=true
                ;;
            --quiet|-q)
                QUIET_MODE=true
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown argument: $1"
                exit 2
                ;;
        esac
        shift
    done
}

get_local_version() {
    local server_path="$DEPLOYMENT_DIR/../implementation/mcp-server/src/server.py"

    if [[ ! -f "$server_path" ]]; then
        log_error "server.py not found at: $server_path"
        echo "unknown"
        return 1
    fi

    grep -E '^__version__\s*=' "$server_path" | sed 's/.*"\([^"]*\)".*/\1/'
}

get_deployed_version() {
    local port=$(get_mcp_port "$ENVIRONMENT")
    local url="http://localhost:$port/health"

    local response
    if response=$(curl -sf "$url" 2>/dev/null); then
        if command -v jq &> /dev/null; then
            echo "$response" | jq -r '.version // "unknown"'
        else
            # Fallback: extract version with grep/sed
            echo "$response" | grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/'
        fi
    else
        echo "unreachable"
    fi
}

rebuild_services() {
    log_info "Rebuilding mcp-server and event-worker (--no-cache)..."

    cd "$DEPLOYMENT_DIR"

    local base_env=".env"
    local env_file=".env.$ENVIRONMENT"
    local project_name="mcp-memory-$ENVIRONMENT"

    # Check if env files exist
    if [[ ! -f "$base_env" ]]; then
        log_error "Missing $base_env"
        return 1
    fi

    if [[ ! -f "$env_file" ]]; then
        log_error "Missing $env_file"
        return 1
    fi

    # Rebuild containers
    docker compose --env-file "$base_env" --env-file "$env_file" \
        -p "$project_name" build mcp-server event-worker --no-cache

    if [[ $? -ne 0 ]]; then
        log_error "Docker build failed"
        return 1
    fi

    log_info "Restarting services..."
    docker compose --env-file "$base_env" --env-file "$env_file" \
        -p "$project_name" up -d mcp-server event-worker

    if [[ $? -ne 0 ]]; then
        log_error "Docker restart failed"
        return 1
    fi

    log_info "Waiting for services to be healthy..."
    "$SCRIPT_DIR/health-check.sh" "$ENVIRONMENT" --wait --timeout 120

    return $?
}

# ==============================================================================
# Main
# ==============================================================================

main() {
    parse_args "$@"

    # Check for skip via environment variable
    if [[ "${SKIP_VERSION_CHECK:-}" == "1" ]]; then
        SKIP_CHECK=true
    fi

    if [[ "$SKIP_CHECK" == "true" ]]; then
        log_info "Version check skipped"
        exit 0
    fi

    log_info "Checking version for $ENVIRONMENT environment..."

    # Get versions
    local local_version
    local_version=$(get_local_version)

    local deployed_version
    deployed_version=$(get_deployed_version)

    log_info "Local version:    $local_version"
    log_info "Deployed version: $deployed_version"

    # Handle unreachable server
    if [[ "$deployed_version" == "unreachable" ]]; then
        log_warn "Server not reachable. Starting services..."
        "$SCRIPT_DIR/env-up.sh" "$ENVIRONMENT"

        # Re-check after starting
        deployed_version=$(get_deployed_version)
        log_info "Deployed version: $deployed_version"
    fi

    # Compare versions
    if [[ "$local_version" == "$deployed_version" ]]; then
        log_info "${GREEN}Versions match!${NC} No rebuild needed."
        exit 0
    fi

    log_warn "Version mismatch detected!"
    log_info "Rebuilding to sync versions..."

    if rebuild_services; then
        # Verify rebuild succeeded
        deployed_version=$(get_deployed_version)
        if [[ "$local_version" == "$deployed_version" ]]; then
            log_info "${GREEN}Rebuild successful!${NC} Versions now match: $deployed_version"
            exit 0
        else
            log_error "Rebuild completed but versions still don't match"
            log_error "Expected: $local_version, Got: $deployed_version"
            exit 1
        fi
    else
        log_error "Rebuild failed"
        exit 1
    fi
}

main "$@"
