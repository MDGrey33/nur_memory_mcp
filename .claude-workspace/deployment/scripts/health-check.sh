#!/bin/bash
# ==============================================================================
# health-check.sh - Check health of MCP Memory Server environment
# ==============================================================================
#
# Checks the health status of all services in the specified environment.
# Returns detailed status for each service with exit code 0 if all healthy.
#
# Usage:
#   ./scripts/health-check.sh [environment] [options]
#
# Arguments:
#   environment   Target environment: test (default), staging, or prod
#
# Options:
#   --wait        Wait for services to become healthy
#   --timeout N   Maximum seconds to wait (default: 60)
#   --quiet       Minimal output (exit code only)
#   --json        Output status as JSON
#
# Examples:
#   ./scripts/health-check.sh              # Check test environment
#   ./scripts/health-check.sh staging      # Check staging environment
#   ./scripts/health-check.sh test --wait  # Wait for test to be healthy
#   ./scripts/health-check.sh --json       # Output as JSON
#
# Exit codes:
#   0 - All services healthy
#   1 - One or more services unhealthy
#   2 - Invalid arguments
# ==============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
ENVIRONMENT=""
WAIT_MODE=false
TIMEOUT=60
QUIET_MODE=false
JSON_OUTPUT=false

# Port lookup functions (bash 3.x compatible)
get_mcp_port() {
    case "$1" in
        test) echo 3201 ;;
        staging) echo 3101 ;;
        prod) echo 3001 ;;
    esac
}

get_chroma_port() {
    case "$1" in
        test) echo 8201 ;;
        staging) echo 8101 ;;
        prod) echo 8001 ;;
    esac
}

get_postgres_port() {
    case "$1" in
        test) echo 5632 ;;
        staging) echo 5532 ;;
        prod) echo 5432 ;;
    esac
}

get_inspector_port() {
    case "$1" in
        test) echo 6474 ;;
        staging) echo 6374 ;;
        prod) echo 6274 ;;
    esac
}

# Service status
MCP_HEALTHY=false
CHROMA_HEALTHY=false
POSTGRES_HEALTHY=false

# ==============================================================================
# Functions
# ==============================================================================

log_info() {
    if [[ "$QUIET_MODE" != "true" && "$JSON_OUTPUT" != "true" ]]; then
        echo -e "${GREEN}[INFO]${NC} $1"
    fi
}

log_warn() {
    if [[ "$QUIET_MODE" != "true" && "$JSON_OUTPUT" != "true" ]]; then
        echo -e "${YELLOW}[WARN]${NC} $1"
    fi
}

log_error() {
    if [[ "$QUIET_MODE" != "true" && "$JSON_OUTPUT" != "true" ]]; then
        echo -e "${RED}[ERROR]${NC} $1"
    fi
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            test|staging|prod)
                ENVIRONMENT="$1"
                ;;
            --wait|-w)
                WAIT_MODE=true
                ;;
            --timeout|-t)
                shift
                TIMEOUT="$1"
                ;;
            --quiet|-q)
                QUIET_MODE=true
                ;;
            --json|-j)
                JSON_OUTPUT=true
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

    # Default environment
    if [[ -z "$ENVIRONMENT" ]]; then
        ENVIRONMENT="test"
    fi
}

show_help() {
    echo "Usage: $0 [environment] [options]"
    echo ""
    echo "Arguments:"
    echo "  environment    test, staging, or prod (default: test)"
    echo ""
    echo "Options:"
    echo "  --wait, -w     Wait for services to become healthy"
    echo "  --timeout N    Maximum seconds to wait (default: 60)"
    echo "  --quiet, -q    Minimal output (exit code only)"
    echo "  --json, -j     Output status as JSON"
    echo "  --help, -h     Show this help message"
}

check_mcp_health() {
    local port=$(get_mcp_port "$ENVIRONMENT")
    local url="http://localhost:$port/health"

    if curl -sf "$url" > /dev/null 2>&1; then
        MCP_HEALTHY=true
        return 0
    fi
    return 1
}

check_chroma_health() {
    local port=$(get_chroma_port "$ENVIRONMENT")
    local url="http://localhost:$port/api/v2/heartbeat"

    if curl -sf "$url" > /dev/null 2>&1; then
        CHROMA_HEALTHY=true
        return 0
    fi
    return 1
}

check_postgres_health() {
    local port=$(get_postgres_port "$ENVIRONMENT")

    # Try pg_isready first
    if command -v pg_isready &> /dev/null; then
        if pg_isready -h localhost -p "$port" -U events > /dev/null 2>&1; then
            POSTGRES_HEALTHY=true
            return 0
        fi
    else
        # Fallback: try TCP connection
        if timeout 2 bash -c "echo > /dev/tcp/localhost/$port" 2>/dev/null; then
            POSTGRES_HEALTHY=true
            return 0
        fi
    fi
    return 1
}

check_all_services() {
    MCP_HEALTHY=false
    CHROMA_HEALTHY=false
    POSTGRES_HEALTHY=false

    check_mcp_health || true
    check_chroma_health || true
    check_postgres_health || true

    if [[ "$MCP_HEALTHY" == "true" && "$CHROMA_HEALTHY" == "true" && "$POSTGRES_HEALTHY" == "true" ]]; then
        return 0
    fi
    return 1
}

wait_for_healthy() {
    local elapsed=0
    local interval=2

    log_info "Waiting for services (timeout: ${TIMEOUT}s)..."

    while [[ $elapsed -lt $TIMEOUT ]]; do
        if check_all_services; then
            return 0
        fi

        if [[ "$QUIET_MODE" != "true" && "$JSON_OUTPUT" != "true" ]]; then
            echo -n "."
        fi

        sleep $interval
        elapsed=$((elapsed + interval))
    done

    if [[ "$QUIET_MODE" != "true" && "$JSON_OUTPUT" != "true" ]]; then
        echo ""
    fi

    return 1
}

output_status() {
    local all_healthy=false
    if [[ "$MCP_HEALTHY" == "true" && "$CHROMA_HEALTHY" == "true" && "$POSTGRES_HEALTHY" == "true" ]]; then
        all_healthy=true
    fi

    if [[ "$JSON_OUTPUT" == "true" ]]; then
        output_json "$all_healthy"
    elif [[ "$QUIET_MODE" != "true" ]]; then
        output_table "$all_healthy"
    fi

    if [[ "$all_healthy" == "true" ]]; then
        return 0
    fi
    return 1
}

output_json() {
    local all_healthy=$1
    local mcp_port=$(get_mcp_port "$ENVIRONMENT")
    local chroma_port=$(get_chroma_port "$ENVIRONMENT")
    local postgres_port=$(get_postgres_port "$ENVIRONMENT")

    cat <<EOF
{
  "environment": "$ENVIRONMENT",
  "all_healthy": $all_healthy,
  "services": {
    "mcp_server": {
      "healthy": $MCP_HEALTHY,
      "port": $mcp_port,
      "url": "http://localhost:$mcp_port"
    },
    "chromadb": {
      "healthy": $CHROMA_HEALTHY,
      "port": $chroma_port,
      "url": "http://localhost:$chroma_port"
    },
    "postgres": {
      "healthy": $POSTGRES_HEALTHY,
      "port": $postgres_port
    }
  }
}
EOF
}

output_table() {
    local all_healthy=$1
    local mcp_port=$(get_mcp_port "$ENVIRONMENT")
    local chroma_port=$(get_chroma_port "$ENVIRONMENT")
    local postgres_port=$(get_postgres_port "$ENVIRONMENT")

    echo ""
    echo "=============================================="
    echo "Health Check: $ENVIRONMENT"
    echo "=============================================="

    # MCP Server
    if [[ "$MCP_HEALTHY" == "true" ]]; then
        echo -e "  MCP Server   (port $mcp_port): ${GREEN}HEALTHY${NC}"
    else
        echo -e "  MCP Server   (port $mcp_port): ${RED}UNHEALTHY${NC}"
    fi

    # ChromaDB
    if [[ "$CHROMA_HEALTHY" == "true" ]]; then
        echo -e "  ChromaDB     (port $chroma_port): ${GREEN}HEALTHY${NC}"
    else
        echo -e "  ChromaDB     (port $chroma_port): ${RED}UNHEALTHY${NC}"
    fi

    # PostgreSQL
    if [[ "$POSTGRES_HEALTHY" == "true" ]]; then
        echo -e "  PostgreSQL   (port $postgres_port): ${GREEN}HEALTHY${NC}"
    else
        echo -e "  PostgreSQL   (port $postgres_port): ${RED}UNHEALTHY${NC}"
    fi

    echo "=============================================="

    if [[ "$all_healthy" == "true" ]]; then
        echo -e "  Overall: ${GREEN}ALL SERVICES HEALTHY${NC}"
    else
        echo -e "  Overall: ${RED}SOME SERVICES UNHEALTHY${NC}"
    fi

    echo "=============================================="
    echo ""
}

# ==============================================================================
# Main
# ==============================================================================

main() {
    parse_args "$@"

    if [[ "$WAIT_MODE" == "true" ]]; then
        if wait_for_healthy; then
            output_status
            exit 0
        else
            output_status
            exit 1
        fi
    else
        check_all_services || true
        output_status
        exit $?
    fi
}

main "$@"
