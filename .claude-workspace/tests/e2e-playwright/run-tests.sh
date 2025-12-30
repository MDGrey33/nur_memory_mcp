#!/bin/bash
# MCP Memory Server - Test Runner Script
# ======================================
# Convenience script for running the Playwright test suite
#
# Usage:
#   ./run-tests.sh              # Run all API tests against test environment
#   ./run-tests.sh smoke        # Run smoke tests only
#   ./run-tests.sh api          # Run API tests
#   ./run-tests.sh memory       # Run memory-related tests
#   ./run-tests.sh --staging    # Run against staging environment
#   ./run-tests.sh --prod       # Run against production (requires ALLOW_PROD_TESTING=true)
#
# Environment Variables:
#   TEST_ENVIRONMENT  - Target environment (test, staging, prod)
#   ALLOW_PROD_TESTING - Set to 'true' to allow production tests
#   HEADED            - Set to 'true' for headed browser mode
#   SLOW_MO           - Milliseconds to slow down operations

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Defaults
TEST_ENV="${TEST_ENVIRONMENT:-test}"
PYTEST_ARGS=""
TEST_MARKERS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --staging)
            TEST_ENV="staging"
            shift
            ;;
        --prod|--production)
            TEST_ENV="prod"
            if [[ "${ALLOW_PROD_TESTING:-}" != "true" ]]; then
                echo -e "${RED}ERROR: Production testing requires ALLOW_PROD_TESTING=true${NC}"
                exit 1
            fi
            shift
            ;;
        --headed)
            export HEADED="true"
            shift
            ;;
        --slowmo)
            export SLOW_MO="${2:-500}"
            shift 2
            ;;
        -v|--verbose)
            PYTEST_ARGS="$PYTEST_ARGS -vv"
            shift
            ;;
        -n|--parallel)
            PYTEST_ARGS="$PYTEST_ARGS -n ${2:-auto}"
            shift 2
            ;;
        smoke)
            TEST_MARKERS="smoke"
            shift
            ;;
        api)
            TEST_MARKERS="api"
            PYTEST_ARGS="$PYTEST_ARGS api/"
            shift
            ;;
        browser)
            TEST_MARKERS="browser"
            PYTEST_ARGS="$PYTEST_ARGS browser/"
            shift
            ;;
        memory)
            TEST_MARKERS="memory"
            shift
            ;;
        artifact)
            TEST_MARKERS="artifact"
            shift
            ;;
        event)
            TEST_MARKERS="event"
            shift
            ;;
        health)
            TEST_MARKERS="health"
            shift
            ;;
        v3)
            TEST_MARKERS="v3"
            shift
            ;;
        v4)
            TEST_MARKERS="v4"
            shift
            ;;
        *)
            # Pass through to pytest
            PYTEST_ARGS="$PYTEST_ARGS $1"
            shift
            ;;
    esac
done

# Set environment
export TEST_ENVIRONMENT="$TEST_ENV"

# Print header
echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}MCP Memory Server Test Suite${NC}"
echo -e "${BLUE}======================================${NC}"
echo -e "Environment: ${GREEN}${TEST_ENV}${NC}"
if [[ -n "$TEST_MARKERS" ]]; then
    echo -e "Markers: ${YELLOW}${TEST_MARKERS}${NC}"
fi
echo ""

# Build pytest command
PYTEST_CMD="python -m pytest"

if [[ -n "$TEST_MARKERS" ]]; then
    PYTEST_CMD="$PYTEST_CMD -m $TEST_MARKERS"
fi

if [[ -z "$PYTEST_ARGS" || "$PYTEST_ARGS" == " " ]]; then
    # Default to api tests
    PYTEST_CMD="$PYTEST_CMD api/"
else
    PYTEST_CMD="$PYTEST_CMD $PYTEST_ARGS"
fi

# Run tests
echo -e "${BLUE}Running: ${NC}$PYTEST_CMD"
echo ""

exec $PYTEST_CMD
