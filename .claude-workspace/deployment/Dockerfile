# MCP Memory Server V3 - Production Dockerfile
# Multi-stage build for optimized final image

# ============================================================================
# Stage 1: Base Dependencies
# ============================================================================
FROM python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r mcp && useradd -r -g mcp mcp

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================================
# Stage 2: Development (optional target)
# ============================================================================
FROM base AS development

# Install development tools
RUN pip install --no-cache-dir \
    debugpy \
    watchdog \
    ipython \
    pytest \
    pytest-cov \
    pytest-asyncio

# Copy source code
COPY src/ ./src/
COPY prompts/ ./prompts/

# Keep as root for development convenience
USER root

# Expose debug ports
EXPOSE 3000 5678

CMD ["python", "src/server.py"]

# ============================================================================
# Stage 3: Production
# ============================================================================
FROM base AS production

# Copy only necessary files
COPY src/ ./src/
COPY prompts/ ./prompts/

# Change ownership to non-root user
RUN chown -R mcp:mcp /app

# Switch to non-root user
USER mcp

# Health check dependencies
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:3000/health', timeout=5)" || exit 1

# Expose MCP server port
EXPOSE 3000

# Default command (can be overridden for worker)
CMD ["python", "src/server.py"]

# ============================================================================
# Metadata
# ============================================================================
LABEL maintainer="MCP Memory Team"
LABEL version="3.0"
LABEL description="MCP Memory Server with Semantic Events"
LABEL org.opencontainers.image.source="https://github.com/your-org/mcp-memory"
