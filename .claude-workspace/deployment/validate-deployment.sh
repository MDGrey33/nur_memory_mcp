#!/bin/bash
# MCP Memory Server V3: Deployment Validation Script
# Validates that all deployment files are present and correctly configured

set -e

DEPLOYMENT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DEPLOYMENT_DIR"

echo "======================================"
echo "MCP Memory Server V3"
echo "Deployment Validation Script"
echo "======================================"
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

# Function to check file exists
check_file() {
    local file=$1
    local description=$2

    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $description: $file"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} $description: $file (MISSING)"
        ((FAILED++))
        return 1
    fi
}

# Function to check file size
check_file_size() {
    local file=$1
    local min_size=$2
    local description=$3

    if [ -f "$file" ]; then
        size=$(wc -c < "$file")
        if [ "$size" -ge "$min_size" ]; then
            echo -e "${GREEN}✓${NC} $description has content ($size bytes)"
            ((PASSED++))
        else
            echo -e "${YELLOW}⚠${NC} $description is too small ($size bytes < $min_size)"
            ((WARNINGS++))
        fi
    fi
}

# Function to check environment file
check_env() {
    if [ -f ".env" ]; then
        if grep -q "OPENAI_API_KEY=sk-" .env; then
            echo -e "${GREEN}✓${NC} .env file exists with OPENAI_API_KEY"
            ((PASSED++))
        else
            echo -e "${YELLOW}⚠${NC} .env file exists but OPENAI_API_KEY may not be set"
            ((WARNINGS++))
        fi
    else
        echo -e "${YELLOW}⚠${NC} .env file not found (copy from .env.example)"
        ((WARNINGS++))
    fi
}

echo "Checking Required Files..."
echo "-----------------------------------"

# Configuration Files
check_file "docker-compose.v3.yml" "V3 Production Compose"
check_file "docker-compose.v3.dev.yml" "V3 Development Overrides"
check_file ".env.example" "Environment Template"
check_file "init.sql" "Database Init Script"
check_file "Dockerfile" "Multi-stage Dockerfile"
check_file "healthcheck.py" "Health Check Script"

echo ""
echo "Checking Documentation..."
echo "-----------------------------------"

# Documentation Files
check_file "V3-README.md" "Quick Reference Guide"
check_file "deploy.md" "Deployment Guide"
check_file "monitoring.md" "Monitoring Guide"
check_file "V3-DEPLOYMENT-SUMMARY.md" "Deployment Summary"

echo ""
echo "Checking File Content..."
echo "-----------------------------------"

# Check file sizes (rough validation)
check_file_size "docker-compose.v3.yml" 4000 "docker-compose.v3.yml"
check_file_size "init.sql" 8000 "init.sql"
check_file_size "healthcheck.py" 5000 "healthcheck.py"
check_file_size "deploy.md" 15000 "deploy.md"

echo ""
echo "Checking Configuration..."
echo "-----------------------------------"

# Check for .env file
check_env

# Check if Docker is installed
if command -v docker &> /dev/null; then
    echo -e "${GREEN}✓${NC} Docker is installed ($(docker --version | cut -d' ' -f3))"
    ((PASSED++))
else
    echo -e "${RED}✗${NC} Docker is not installed"
    ((FAILED++))
fi

# Check if Docker Compose is available
if docker compose version &> /dev/null; then
    echo -e "${GREEN}✓${NC} Docker Compose is available ($(docker compose version | cut -d' ' -f4))"
    ((PASSED++))
elif command -v docker-compose &> /dev/null; then
    echo -e "${GREEN}✓${NC} Docker Compose is available ($(docker-compose --version | cut -d' ' -f3))"
    ((PASSED++))
else
    echo -e "${RED}✗${NC} Docker Compose is not available"
    ((FAILED++))
fi

echo ""
echo "Checking Docker Compose Syntax..."
echo "-----------------------------------"

# Validate docker-compose files
if docker compose -f docker-compose.v3.yml config > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} docker-compose.v3.yml syntax is valid"
    ((PASSED++))
else
    echo -e "${RED}✗${NC} docker-compose.v3.yml has syntax errors"
    ((FAILED++))
fi

if [ -f ".env" ]; then
    if docker compose -f docker-compose.v3.yml -f docker-compose.v3.dev.yml config > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} docker-compose.v3.dev.yml syntax is valid"
        ((PASSED++))
    else
        echo -e "${RED}✗${NC} docker-compose.v3.dev.yml has syntax errors"
        ((FAILED++))
    fi
fi

echo ""
echo "Checking Dockerfile..."
echo "-----------------------------------"

# Check Dockerfile for required sections
if grep -q "FROM python:3.11-slim AS base" Dockerfile; then
    echo -e "${GREEN}✓${NC} Dockerfile has multi-stage build"
    ((PASSED++))
else
    echo -e "${RED}✗${NC} Dockerfile missing multi-stage build"
    ((FAILED++))
fi

if grep -q "USER mcp" Dockerfile; then
    echo -e "${GREEN}✓${NC} Dockerfile uses non-root user"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠${NC} Dockerfile may not use non-root user"
    ((WARNINGS++))
fi

echo ""
echo "Checking init.sql..."
echo "-----------------------------------"

# Check init.sql for required tables
required_tables=("artifact_revision" "event_jobs" "semantic_event" "event_evidence")
for table in "${required_tables[@]}"; do
    if grep -q "CREATE TABLE IF NOT EXISTS $table" init.sql; then
        echo -e "${GREEN}✓${NC} init.sql includes $table table"
        ((PASSED++))
    else
        echo -e "${RED}✗${NC} init.sql missing $table table"
        ((FAILED++))
    fi
done

echo ""
echo "======================================"
echo "Validation Summary"
echo "======================================"
echo -e "${GREEN}Passed:${NC}   $PASSED"
echo -e "${YELLOW}Warnings:${NC} $WARNINGS"
echo -e "${RED}Failed:${NC}   $FAILED"
echo ""

if [ $FAILED -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}✓ All checks passed! Ready for deployment.${NC}"
        echo ""
        echo "Next steps:"
        echo "  1. Copy .env.example to .env and set OPENAI_API_KEY"
        echo "  2. Run: docker compose -f docker-compose.v3.yml up -d"
        echo "  3. Verify: docker compose -f docker-compose.v3.yml exec mcp-server python healthcheck.py --service all"
        exit 0
    else
        echo -e "${YELLOW}⚠ Checks passed with warnings. Review warnings before deployment.${NC}"
        exit 0
    fi
else
    echo -e "${RED}✗ Some checks failed. Fix errors before deployment.${NC}"
    exit 1
fi
