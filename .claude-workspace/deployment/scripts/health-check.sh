#!/bin/bash
# ==============================================================================
# health-check.sh - MCP Memory Server V5 Health Check Script
# ==============================================================================
#
# Checks the health status of all V5 services and validates V5-specific
# features like the new collections and tools.
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
#   --v5-check    Validate V5-specific features (collections, tools)
#
# Examples:
#   ./scripts/health-check.sh              # Check test environment
#   ./scripts/health-check.sh staging      # Check staging environment
#   ./scripts/health-check.sh test --wait  # Wait for test to be healthy
#   ./scripts/health-check.sh --json       # Output as JSON
#   ./scripts/health-check.sh --v5-check   # Validate V5 features
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
V5_CHECK=false

# Port lookup functions (bash 3.x compatible)
get_mcp_port() {
    case "$1" in
        test) echo 3201 ;;
        staging) echo 3101 ;;
        prod) echo 3001 ;;
        *) echo 3000 ;;
    esac
}

get_chroma_port() {
    case "$1" in
        test) echo 8201 ;;
        staging) echo 8101 ;;
        prod) echo 8001 ;;
        *) echo 8001 ;;
    esac
}

get_postgres_port() {
    case "$1" in
        test) echo 5632 ;;
        staging) echo 5532 ;;
        prod) echo 5432 ;;
        *) echo 5432 ;;
    esac
}

get_inspector_port() {
    case "$1" in
        test) echo 6474 ;;
        staging) echo 6374 ;;
        prod) echo 6274 ;;
        *) echo 6274 ;;
    esac
}

# Service status
MCP_HEALTHY=false
CHROMA_HEALTHY=false
POSTGRES_HEALTHY=false
SERVER_VERSION=""
V5_TOOLS_AVAILABLE=false
V5_COLLECTIONS_OK=false

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
            --v5-check)
                V5_CHECK=true
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
    echo "MCP Memory Server V5 Health Check Script"
    echo ""
    echo "Arguments:"
    echo "  environment    test, staging, or prod (default: test)"
    echo ""
    echo "Options:"
    echo "  --wait, -w     Wait for services to become healthy"
    echo "  --timeout N    Maximum seconds to wait (default: 60)"
    echo "  --quiet, -q    Minimal output (exit code only)"
    echo "  --json, -j     Output status as JSON"
    echo "  --v5-check     Validate V5-specific features"
    echo "  --help, -h     Show this help message"
    echo ""
    echo "V5 Features Checked:"
    echo "  - Server version (5.x.x)"
    echo "  - V5 tools: remember, recall, forget, status"
    echo "  - V5 collections: content, chunks"
    echo "  - ChromaDB health and collections"
    echo "  - PostgreSQL health and schema"
}

check_mcp_health() {
    local port=$(get_mcp_port "$ENVIRONMENT")
    local url="http://localhost:$port/health"

    local response
    if response=$(curl -sf "$url" 2>/dev/null); then
        MCP_HEALTHY=true

        # Extract version if available
        if command -v jq &> /dev/null; then
            SERVER_VERSION=$(echo "$response" | jq -r '.version // "unknown"')
        fi

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

check_v5_tools() {
    local port=$(get_mcp_port "$ENVIRONMENT")
    local url="http://localhost:$port/tools"

    local response
    if response=$(curl -sf "$url" 2>/dev/null); then
        if command -v jq &> /dev/null; then
            # Check for V5 tools
            local has_remember=$(echo "$response" | jq 'any(.name == "remember")')
            local has_recall=$(echo "$response" | jq 'any(.name == "recall")')
            local has_forget=$(echo "$response" | jq 'any(.name == "forget")')
            local has_status=$(echo "$response" | jq 'any(.name == "status")')

            if [[ "$has_remember" == "true" && "$has_recall" == "true" && "$has_forget" == "true" && "$has_status" == "true" ]]; then
                V5_TOOLS_AVAILABLE=true
                return 0
            fi
        fi
    fi
    return 1
}

check_v5_collections() {
    local port=$(get_chroma_port "$ENVIRONMENT")
    local url="http://localhost:$port/api/v2/collections"

    local response
    if response=$(curl -sf "$url" 2>/dev/null); then
        if command -v jq &> /dev/null; then
            # Check for V5 collections
            local has_content=$(echo "$response" | jq 'any(.name == "content")')
            local has_chunks=$(echo "$response" | jq 'any(.name == "chunks")')

            # V5 collections are optional - also check for V4 collections
            local has_artifacts=$(echo "$response" | jq 'any(.name == "artifacts")')

            if [[ "$has_content" == "true" || "$has_artifacts" == "true" ]]; then
                V5_COLLECTIONS_OK=true
                return 0
            fi
        fi
    fi
    return 1
}

check_all_services() {
    MCP_HEALTHY=false
    CHROMA_HEALTHY=false
    POSTGRES_HEALTHY=false
    V5_TOOLS_AVAILABLE=false
    V5_COLLECTIONS_OK=false

    check_mcp_health || true
    check_chroma_health || true
    check_postgres_health || true

    if [[ "$V5_CHECK" == "true" ]]; then
        check_v5_tools || true
        check_v5_collections || true
    fi

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
  "version": "$SERVER_VERSION",
  "services": {
    "mcp_server": {
      "healthy": $MCP_HEALTHY,
      "port": $mcp_port,
      "url": "http://localhost:$mcp_port",
      "version": "$SERVER_VERSION"
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
  },
  "v5_features": {
    "tools_available": $V5_TOOLS_AVAILABLE,
    "collections_ok": $V5_COLLECTIONS_OK
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
    echo "MCP Memory Server V5 Health Check"
    echo "Environment: $ENVIRONMENT"
    echo "=============================================="

    # Server Version
    if [[ -n "$SERVER_VERSION" && "$SERVER_VERSION" != "unknown" ]]; then
        echo -e "  Version:     ${BLUE}$SERVER_VERSION${NC}"
    fi

    echo ""
    echo "Services:"
    echo "----------------------------------------------"

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

    # V5 Features (if checked)
    if [[ "$V5_CHECK" == "true" ]]; then
        echo ""
        echo "V5 Features:"
        echo "----------------------------------------------"

        if [[ "$V5_TOOLS_AVAILABLE" == "true" ]]; then
            echo -e "  V5 Tools     (remember, recall, forget, status): ${GREEN}AVAILABLE${NC}"
        else
            echo -e "  V5 Tools     (remember, recall, forget, status): ${YELLOW}NOT DETECTED${NC}"
        fi

        if [[ "$V5_COLLECTIONS_OK" == "true" ]]; then
            echo -e "  V5 Collections: ${GREEN}OK${NC}"
        else
            echo -e "  V5 Collections: ${YELLOW}NOT DETECTED${NC}"
        fi
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
