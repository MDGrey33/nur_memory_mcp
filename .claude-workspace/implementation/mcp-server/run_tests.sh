#!/bin/bash
# Test runner script for MCP Memory Server v2.0

set -e

echo "======================================"
echo "MCP Memory Server v2.0 - Test Suite"
echo "======================================"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    echo "Warning: No virtual environment found."
    echo "Consider creating one with: python -m venv venv"
    echo ""
fi

# Install dependencies if needed
if ! python -c "import pytest" 2>/dev/null; then
    echo "Installing test dependencies..."
    pip install -r requirements.txt
    echo ""
fi

# Parse command line arguments
COVERAGE=false
VERBOSE=false
MARKERS=""
SPECIFIC_TEST=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --coverage|-c)
            COVERAGE=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --unit)
            SPECIFIC_TEST="tests/unit"
            shift
            ;;
        --integration)
            SPECIFIC_TEST="tests/integration"
            shift
            ;;
        --markers|-m)
            MARKERS="-m $2"
            shift 2
            ;;
        *)
            SPECIFIC_TEST="$1"
            shift
            ;;
    esac
done

# Build pytest command
PYTEST_CMD="pytest"

if [ "$SPECIFIC_TEST" != "" ]; then
    PYTEST_CMD="$PYTEST_CMD $SPECIFIC_TEST"
fi

if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -v"
fi

if [ "$MARKERS" != "" ]; then
    PYTEST_CMD="$PYTEST_CMD $MARKERS"
fi

if [ "$COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=src --cov-report=term-missing --cov-report=html"
    echo "Running tests with coverage report..."
else
    echo "Running tests..."
fi

echo ""
echo "Command: $PYTEST_CMD"
echo ""

# Run tests
$PYTEST_CMD

# Show coverage report location if generated
if [ "$COVERAGE" = true ]; then
    echo ""
    echo "======================================"
    echo "Coverage report generated!"
    echo "HTML report: htmlcov/index.html"
    echo "======================================"
fi

echo ""
echo "======================================"
echo "Test run complete!"
echo "======================================"
