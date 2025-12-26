#!/bin/bash

# MCP Memory - ChromaDB Restore Script
# Restores ChromaDB data from backup

set -e  # Exit on error
set -u  # Exit on undefined variable

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/tmp/mcp-memory-backups}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if backup directory exists
if [ ! -d "$BACKUP_DIR" ]; then
    log_error "Backup directory not found: $BACKUP_DIR"
    exit 1
fi

# List available backups
log_info "Available backups:"
echo ""
BACKUPS=($(find "$BACKUP_DIR" -name "chroma_backup_*.tar.gz" -type f | sort -r))

if [ ${#BACKUPS[@]} -eq 0 ]; then
    log_error "No backups found in $BACKUP_DIR"
    exit 1
fi

# Display backups with index
i=1
for backup in "${BACKUPS[@]}"; do
    BACKUP_SIZE=$(du -h "$backup" | cut -f1)
    BACKUP_DATE=$(date -r "$backup" "+%Y-%m-%d %H:%M:%S")
    echo "[$i] $(basename "$backup") - $BACKUP_SIZE - $BACKUP_DATE"

    # Show metadata if available
    METADATA_FILE="${backup}.metadata"
    if [ -f "$METADATA_FILE" ]; then
        echo "    Environment: $(grep "Environment:" "$METADATA_FILE" | cut -d: -f2)"
    fi

    i=$((i + 1))
done

echo ""
echo "Enter backup number to restore (or 'q' to quit): "
read -r selection

# Validate input
if [ "$selection" = "q" ]; then
    log_info "Restore cancelled"
    exit 0
fi

if ! [[ "$selection" =~ ^[0-9]+$ ]] || [ "$selection" -lt 1 ] || [ "$selection" -gt ${#BACKUPS[@]} ]; then
    log_error "Invalid selection"
    exit 1
fi

# Get selected backup
BACKUP_FILE="${BACKUPS[$((selection - 1))]}"
log_info "Selected backup: $(basename "$BACKUP_FILE")"

# Detect backup environment from filename
if [[ "$BACKUP_FILE" == *"_production_"* ]]; then
    BACKUP_ENV="production"
elif [[ "$BACKUP_FILE" == *"_development_"* ]]; then
    BACKUP_ENV="development"
else
    log_warn "Cannot determine backup environment from filename"
    BACKUP_ENV="unknown"
fi

# Ask for target environment
echo ""
echo "Restore to which environment? [dev/prod]"
read -r target_env

if [ "$target_env" = "prod" ]; then
    ENV="production"
    CONTAINER="chroma-prod"
    VOLUME="mcp_memory_chroma_data_prod"
    COMPOSE_FILE="docker-compose.prod.yml"
elif [ "$target_env" = "dev" ]; then
    ENV="development"
    CONTAINER="chroma-dev"
    VOLUME="mcp_memory_chroma_data_dev"
    COMPOSE_FILE="docker-compose.dev.yml"
else
    log_error "Invalid environment. Use 'dev' or 'prod'"
    exit 1
fi

# Warning
echo ""
log_warn "WARNING: This will DELETE all current data in $ENV environment!"
log_warn "Backup source: $BACKUP_ENV"
log_warn "Restore target: $ENV"
echo ""
echo "Are you sure you want to continue? Type 'yes' to confirm: "
read -r confirm

if [ "$confirm" != "yes" ]; then
    log_info "Restore cancelled"
    exit 0
fi

# Stop container if running
if docker ps | grep -q "$CONTAINER"; then
    log_info "Stopping $CONTAINER..."
    docker stop "$CONTAINER"
fi

# Remove existing volume
log_info "Removing existing volume: $VOLUME"
docker volume rm "$VOLUME" 2>/dev/null || true

# Create new volume
log_info "Creating new volume: $VOLUME"
docker volume create "$VOLUME"

# Restore data
log_info "Restoring data from backup..."
docker run --rm \
    -v "$VOLUME":/target \
    -v "$BACKUP_DIR":/backup:ro \
    alpine:latest \
    tar xzf "/backup/$(basename "$BACKUP_FILE")" -C /target

# Restart services
log_info "Restarting services..."
cd "$(dirname "$0")/.."  # Go to deployment directory

if [ "$ENV" = "production" ]; then
    docker-compose -f docker-compose.prod.yml up -d
else
    docker-compose -f docker-compose.dev.yml up -d
fi

# Wait for health check
log_info "Waiting for services to be healthy..."
sleep 5

# Check health
if docker ps --filter "name=$CONTAINER" --filter "health=healthy" | grep -q "$CONTAINER"; then
    log_info "Restore successful! Container is healthy."
else
    log_warn "Container started but may not be healthy yet. Check logs with: make logs-chroma"
fi

log_info "Restore complete!"
