#!/bin/bash

# MCP Memory - ChromaDB Backup Script
# Creates timestamped backup of ChromaDB data volumes

set -e  # Exit on error
set -u  # Exit on undefined variable

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/tmp/mcp-memory-backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

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

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Detect which environment is running
if docker ps | grep -q "chroma-prod"; then
    ENV="production"
    CONTAINER="chroma-prod"
    VOLUME="mcp_memory_chroma_data_prod"
elif docker ps | grep -q "chroma-dev"; then
    ENV="development"
    CONTAINER="chroma-dev"
    VOLUME="mcp_memory_chroma_data_dev"
else
    log_error "No ChromaDB container is running"
    echo "Start the environment first with 'make dev' or 'make prod'"
    exit 1
fi

log_info "Backing up $ENV environment..."
log_info "Container: $CONTAINER"
log_info "Volume: $VOLUME"

# Create backup filename
BACKUP_FILE="$BACKUP_DIR/chroma_backup_${ENV}_${TIMESTAMP}.tar.gz"

# Check if container is healthy
if ! docker ps --filter "name=$CONTAINER" --filter "health=healthy" | grep -q "$CONTAINER"; then
    log_warn "Container $CONTAINER is not healthy. Backup may be incomplete."
    echo "Continue anyway? [y/N]"
    read -r confirm
    if [ "$confirm" != "y" ]; then
        log_info "Backup cancelled"
        exit 0
    fi
fi

# Create backup
log_info "Creating backup: $BACKUP_FILE"

# Use docker run with volume mount to create backup
docker run --rm \
    -v "$VOLUME":/source:ro \
    -v "$BACKUP_DIR":/backup \
    alpine:latest \
    tar czf "/backup/$(basename "$BACKUP_FILE")" -C /source .

# Verify backup was created
if [ -f "$BACKUP_FILE" ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log_info "Backup created successfully: $BACKUP_FILE ($BACKUP_SIZE)"
else
    log_error "Backup failed - file not created"
    exit 1
fi

# Create metadata file
METADATA_FILE="${BACKUP_FILE}.metadata"
cat > "$METADATA_FILE" <<EOF
Backup Metadata
================
Environment: $ENV
Container: $CONTAINER
Volume: $VOLUME
Timestamp: $TIMESTAMP
Date: $(date)
Size: $BACKUP_SIZE
Hostname: $(hostname)
Docker Version: $(docker --version)
EOF

log_info "Metadata saved: $METADATA_FILE"

# Cleanup old backups
log_info "Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "chroma_backup_*.tar.gz" -type f -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "chroma_backup_*.metadata" -type f -mtime +$RETENTION_DAYS -delete

# List recent backups
log_info "Recent backups:"
ls -lh "$BACKUP_DIR"/chroma_backup_*.tar.gz | tail -5 || log_warn "No backups found"

log_info "Backup complete!"
