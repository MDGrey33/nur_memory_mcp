#!/bin/bash
# ==============================================================================
# env-reset.sh - Reset MCP Memory Server environment
# ==============================================================================
#
# Resets the specified environment by removing all data and restarting services.
# This is useful for ensuring clean test runs.
#
# SAFETY: Production requires --force flag.
#
# Usage:
#   ./scripts/env-reset.sh [environment] [--force]
#
# Arguments:
#   environment   Target environment: test (default), staging, or prod
#   --force       Required for prod reset (safety measure)
#
# Examples:
#   ./scripts/env-reset.sh              # Reset test environment
#   ./scripts/env-reset.sh staging      # Reset staging environment
#   ./scripts/env-reset.sh prod --force # Reset prod (requires --force)
#
# Exit codes:
#   0 - Success
#   1 - Invalid environment or missing --force for prod
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
ENVIRONMENT=""
FORCE=false
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
            --force|-f)
                FORCE=true
                shift
                ;;
            -h|--help)
                echo "Usage: $0 [environment] [--force]"
                echo ""
                echo "Arguments:"
                echo "  environment   test, staging, or prod (default: test)"
                echo "  --force       Required for prod reset"
                exit 0
                ;;
            *)
                log_error "Unknown argument: $1"
                exit 1
                ;;
        esac
    done

    # Default to test if not specified
    if [[ -z "$ENVIRONMENT" ]]; then
        ENVIRONMENT="test"
    fi
}

validate_environment() {
    case "$ENVIRONMENT" in
        test|staging)
            log_info "Target environment: $ENVIRONMENT"
            ;;
        prod)
            if [[ "$FORCE" != "true" ]]; then
                log_error "SAFETY: Cannot reset production without --force flag!"
                log_error "Usage: $0 prod --force"
                exit 1
            fi
            log_warn "Resetting PRODUCTION environment (--force specified)"
            ;;
        *)
            log_error "Invalid environment: $ENVIRONMENT"
            echo "Valid options: test, staging, prod"
            exit 1
            ;;
    esac
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

    parse_args "$@"
    validate_environment

    log_warn "This will DELETE ALL DATA in the $ENVIRONMENT environment!"
    echo ""

    # Stop services and remove volumes
    log_info "Stopping services and removing volumes..."
    "$SCRIPT_DIR/env-down.sh" "$ENVIRONMENT" --volumes

    # Restart services
    log_info "Restarting services..."
    "$SCRIPT_DIR/env-up.sh" "$ENVIRONMENT"

    log_info "Environment $ENVIRONMENT has been reset!"
}

main "$@"
