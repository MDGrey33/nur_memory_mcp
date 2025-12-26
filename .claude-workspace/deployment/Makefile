.PHONY: help dev prod test logs backup restore clean build stop restart status health

# Default target
help:
	@echo "MCP Memory - Deployment Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make dev          - Start development environment"
	@echo "  make prod         - Start production environment"
	@echo "  make build        - Build Docker images"
	@echo "  make stop         - Stop all services"
	@echo "  make restart      - Restart all services"
	@echo "  make logs         - View logs (all services)"
	@echo "  make logs-chroma  - View ChromaDB logs"
	@echo "  make logs-agent   - View agent-app logs"
	@echo "  make test         - Run tests"
	@echo "  make backup       - Backup ChromaDB data"
	@echo "  make restore      - Restore ChromaDB data from backup"
	@echo "  make clean        - Cleanup containers and volumes"
	@echo "  make status       - Show service status"
	@echo "  make health       - Check service health"
	@echo "  make shell-chroma - Open shell in ChromaDB container"
	@echo "  make shell-agent  - Open shell in agent-app container"
	@echo ""

# Development environment
dev:
	@echo "Starting development environment..."
	@if [ ! -f .env.development ]; then \
		echo "Creating .env.development from example..."; \
		cp .env.production.example .env.development; \
	fi
	docker-compose -f docker-compose.dev.yml up -d
	@echo "Development environment started!"
	@echo "ChromaDB available at: http://localhost:8000"
	@echo "View logs with: make logs"

# Production environment
prod:
	@echo "Starting production environment..."
	@if [ ! -f .env.production ]; then \
		echo "ERROR: .env.production not found!"; \
		echo "Create it from .env.production.example and configure appropriately."; \
		exit 1; \
	fi
	docker-compose -f docker-compose.prod.yml up -d
	@echo "Production environment started!"
	@echo "View logs with: make logs"
	@echo "Check health with: make health"

# Build images
build:
	@echo "Building Docker images..."
	docker-compose -f docker-compose.dev.yml build --no-cache
	@echo "Build complete!"

# Build production images
build-prod:
	@echo "Building production Docker images..."
	docker-compose -f docker-compose.prod.yml build --no-cache
	@echo "Production build complete!"

# Stop all services
stop:
	@echo "Stopping all services..."
	@docker-compose -f docker-compose.dev.yml down 2>/dev/null || true
	@docker-compose -f docker-compose.prod.yml down 2>/dev/null || true
	@echo "All services stopped."

# Restart services
restart: stop
	@echo "Which environment? [dev/prod]"
	@read env; \
	if [ "$$env" = "prod" ]; then \
		$(MAKE) prod; \
	else \
		$(MAKE) dev; \
	fi

# View logs
logs:
	@echo "Viewing logs (Ctrl+C to exit)..."
	@if docker ps | grep -q "chroma-dev"; then \
		docker-compose -f docker-compose.dev.yml logs -f; \
	elif docker ps | grep -q "chroma-prod"; then \
		docker-compose -f docker-compose.prod.yml logs -f; \
	else \
		echo "No services running. Start with 'make dev' or 'make prod'"; \
	fi

# View ChromaDB logs
logs-chroma:
	@if docker ps | grep -q "chroma-dev"; then \
		docker logs -f chroma-dev; \
	elif docker ps | grep -q "chroma-prod"; then \
		docker logs -f chroma-prod; \
	else \
		echo "ChromaDB not running."; \
	fi

# View agent-app logs
logs-agent:
	@if docker ps | grep -q "agent-app-dev"; then \
		docker logs -f agent-app-dev; \
	elif docker ps | grep -q "agent-app-prod"; then \
		docker logs -f agent-app-prod; \
	else \
		echo "Agent app not running."; \
	fi

# Run tests
test:
	@echo "Running tests..."
	@if [ ! -f .env.development ]; then \
		cp .env.production.example .env.development; \
	fi
	docker-compose -f docker-compose.dev.yml up -d
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@if docker ps | grep -q "agent-app-dev"; then \
		docker exec agent-app-dev python -m pytest tests/ -v; \
	else \
		echo "Agent app not running. Start with 'make dev' first."; \
	fi

# Backup ChromaDB data
backup:
	@echo "Creating backup..."
	@./scripts/backup.sh
	@echo "Backup complete!"

# Restore ChromaDB data
restore:
	@echo "Restoring from backup..."
	@./scripts/restore.sh
	@echo "Restore complete!"

# Clean up everything
clean:
	@echo "WARNING: This will remove all containers, volumes, and data!"
	@echo "Are you sure? [y/N]"
	@read confirm; \
	if [ "$$confirm" = "y" ]; then \
		echo "Cleaning up..."; \
		docker-compose -f docker-compose.dev.yml down -v 2>/dev/null || true; \
		docker-compose -f docker-compose.prod.yml down -v 2>/dev/null || true; \
		docker volume rm mcp_memory_chroma_data_dev 2>/dev/null || true; \
		docker volume rm mcp_memory_chroma_data_prod 2>/dev/null || true; \
		docker network rm mcp-memory-dev-network 2>/dev/null || true; \
		docker network rm mcp-memory-prod-network 2>/dev/null || true; \
		echo "Cleanup complete!"; \
	else \
		echo "Cancelled."; \
	fi

# Show service status
status:
	@echo "Service Status:"
	@echo "==============="
	@docker ps --filter "name=chroma" --filter "name=agent-app" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Check service health
health:
	@echo "Running health checks..."
	@./scripts/health-check.sh

# Open shell in ChromaDB container
shell-chroma:
	@if docker ps | grep -q "chroma-dev"; then \
		docker exec -it chroma-dev /bin/bash; \
	elif docker ps | grep -q "chroma-prod"; then \
		docker exec -it chroma-prod /bin/bash; \
	else \
		echo "ChromaDB not running."; \
	fi

# Open shell in agent-app container
shell-agent:
	@if docker ps | grep -q "agent-app-dev"; then \
		docker exec -it agent-app-dev /bin/bash; \
	elif docker ps | grep -q "agent-app-prod"; then \
		docker exec -it agent-app-prod /bin/bash; \
	else \
		echo "Agent app not running."; \
	fi

# Debug ChromaDB connection
debug-chroma:
	@echo "Testing ChromaDB connection..."
	@if docker ps | grep -q "chroma-dev"; then \
		docker exec chroma-dev curl -s http://localhost:8000/api/v1/heartbeat || echo "Failed to connect"; \
	elif docker ps | grep -q "chroma-prod"; then \
		docker exec chroma-prod curl -s http://localhost:8000/api/v1/heartbeat || echo "Failed to connect"; \
	else \
		echo "ChromaDB not running."; \
	fi

# Show resource usage
resources:
	@echo "Resource Usage:"
	@echo "==============="
	@docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
		chroma-dev chroma-prod chroma-mcp-dev chroma-mcp-prod agent-app-dev agent-app-prod 2>/dev/null || true

# Prune unused resources
prune:
	@echo "Pruning unused Docker resources..."
	@docker system prune -f
	@echo "Prune complete!"
