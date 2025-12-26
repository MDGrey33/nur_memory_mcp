# Directory Structure: Chroma MCP Memory V1

**Date:** 2025-12-25
**Version:** 1.0

---

## Complete Project Structure

```
mcp_memory/                                   # Project root
├── docker-compose.yml                        # Docker Compose orchestration
├── .env.example                              # Environment variable template
├── .gitignore                                # Git ignore patterns
├── README.md                                 # Project documentation
├── LICENSE                                   # License file
│
├── agent-app/                                # Python agent application
│   ├── Dockerfile                            # Agent app container definition
│   ├── requirements.txt                      # Python dependencies
│   ├── pyproject.toml                        # Python project metadata (optional)
│   ├── setup.py                              # Package setup (optional)
│   │
│   ├── src/                                  # Source code
│   │   ├── __init__.py                       # Package initialization
│   │   │
│   │   ├── app.py                            # Main application entrypoint
│   │   │   # - Application initialization
│   │   │   # - Component wiring (DI)
│   │   │   # - Message handling flow
│   │   │   # - Graceful shutdown
│   │   │   # - Health check endpoint
│   │   │
│   │   ├── memory_gateway.py                 # MCP transport layer
│   │   │   # - MemoryGateway class
│   │   │   # - MCP client initialization
│   │   │   # - ensure_collections()
│   │   │   # - append_history()
│   │   │   # - tail_history()
│   │   │   # - write_memory()
│   │   │   # - recall_memory()
│   │   │   # - Error mapping (MCP → domain)
│   │   │   # - Retry logic
│   │   │
│   │   ├── context_builder.py                # Context assembly layer
│   │   │   # - ContextBuilder class
│   │   │   # - build_context()
│   │   │   # - format_for_prompt()
│   │   │   # - _truncate_to_budget()
│   │   │   # - _count_tokens()
│   │   │   # - _format_history()
│   │   │   # - _format_memories()
│   │   │
│   │   ├── memory_policy.py                  # Memory policy logic
│   │   │   # - MemoryPolicy class
│   │   │   # - should_store()
│   │   │   # - enforce_rate_limit()
│   │   │   # - validate_memory_type()
│   │   │   # - _check_confidence()
│   │   │   # - _check_window_limit()
│   │   │
│   │   ├── models.py                         # Data models (dataclasses)
│   │   │   # - HistoryTurn
│   │   │   # - MemoryItem
│   │   │   # - ContextPackage
│   │   │   # - Validation functions
│   │   │
│   │   ├── config.py                         # Configuration management
│   │   │   # - Load environment variables
│   │   │   # - AppConfig dataclass
│   │   │   # - Validation and defaults
│   │   │
│   │   ├── exceptions.py                     # Custom exceptions
│   │   │   # - MCPError
│   │   │   # - ConnectionError
│   │   │   # - ContextBuildError
│   │   │   # - ValidationError
│   │   │
│   │   └── utils.py                          # Utility functions
│   │       # - Timestamp formatting
│   │       # - Token counting
│   │       # - Logging helpers
│   │
│   ├── tests/                                # Test suite
│   │   ├── __init__.py
│   │   │
│   │   ├── conftest.py                       # Pytest fixtures
│   │   │   # - Mock MCP client
│   │   │   # - Mock gateway
│   │   │   # - Sample data fixtures
│   │   │
│   │   ├── unit/                             # Unit tests
│   │   │   ├── __init__.py
│   │   │   ├── test_memory_gateway.py        # Gateway layer tests
│   │   │   ├── test_context_builder.py       # Builder layer tests
│   │   │   ├── test_memory_policy.py         # Policy layer tests
│   │   │   ├── test_models.py                # Data model tests
│   │   │   └── test_utils.py                 # Utility tests
│   │   │
│   │   ├── integration/                      # Integration tests
│   │   │   ├── __init__.py
│   │   │   ├── test_end_to_end.py            # Full flow tests
│   │   │   ├── test_persistence.py           # Restart tests
│   │   │   └── test_docker_compose.py        # Container tests
│   │   │
│   │   └── fixtures/                         # Test data
│   │       ├── sample_history.json           # Sample conversation history
│   │       ├── sample_memories.json          # Sample memories
│   │       └── sample_contexts.json          # Sample context packages
│   │
│   ├── scripts/                              # Helper scripts
│   │   ├── bootstrap.py                      # Bootstrap collections
│   │   ├── seed_data.py                      # Seed test data
│   │   └── verify_setup.py                   # Setup verification
│   │
│   └── docs/                                 # Agent-app specific docs
│       ├── api.md                            # API documentation
│       ├── configuration.md                  # Configuration guide
│       └── troubleshooting.md                # Common issues
│
├── .claude-workspace/                        # Claude Mind workspace
│   ├── current-task.json                     # Task tracking
│   ├── specs/                                # Specifications
│   │   └── v1-specification.md               # V1 detailed spec
│   ├── architecture/                         # Architecture docs
│   │   ├── ADR-001-docker-first.md           # Docker decision
│   │   ├── ADR-002-chromadb-vector-store.md  # ChromaDB decision
│   │   ├── ADR-003-separation-of-concerns.md # Architecture decision
│   │   ├── ADR-004-two-collection-model.md   # Collections decision
│   │   ├── component-diagram.md              # Component architecture
│   │   ├── data-flows.md                     # Flow diagrams
│   │   └── directory-structure.md            # This file
│   ├── implementation/                       # Implementation artifacts
│   ├── tests/                                # Test plans
│   ├── security/                             # Security audits
│   ├── deployment/                           # Deployment configs
│   └── deliverables/                         # UAT packages
│
├── docs/                                     # Project-wide documentation
│   ├── quickstart.md                         # Getting started guide
│   ├── architecture.md                       # Architecture overview
│   ├── deployment.md                         # Deployment guide
│   ├── development.md                        # Development workflow
│   ├── api-reference.md                      # API reference
│   └── troubleshooting.md                    # Troubleshooting guide
│
└── scripts/                                  # Project-level scripts
    ├── setup.sh                              # Initial setup script
    ├── test-persistence.sh                   # Persistence test
    ├── backup-volume.sh                      # Volume backup script
    ├── restore-volume.sh                     # Volume restore script
    └── clean.sh                              # Cleanup script
```

---

## agent-app/src/ Module Details

### 1. app.py (Main Application)

```python
"""
Main application entrypoint and orchestration.

Responsibilities:
- Initialize all components
- Wire dependencies (dependency injection)
- Handle message lifecycle
- Coordinate flows
- Manage graceful shutdown

Entry point: main()
"""

# Key classes/functions:
class Application:
    def __init__(self, config: AppConfig)
    def start(self)
    def stop(self)
    def handle_message(self, message: dict)
    def _bootstrap(self)
    def _health_check(self)

def main():
    # Load config, initialize app, run
```

**Size estimate**: 200-300 lines

---

### 2. memory_gateway.py (Transport Layer)

```python
"""
MCP transport layer for ChromaDB operations.

Responsibilities:
- MCP protocol communication (stdio)
- Serialize/deserialize payloads
- Connection management
- Retry logic
- Error mapping

NO business logic - pure transport.
"""

# Key classes/functions:
class MemoryGateway:
    def __init__(self, mcp_endpoint: str)
    def ensure_collections(self, names: list[str]) -> None
    def append_history(self, conversation_id: str, role: str,
                      text: str, turn_index: int, ts: str,
                      message_id: str | None = None,
                      channel: str | None = None) -> str
    def tail_history(self, conversation_id: str, n: int) -> list[dict]
    def write_memory(self, text: str, memory_type: str,
                    confidence: float, ts: str,
                    conversation_id: str | None = None,
                    entities: str | None = None,
                    source: str | None = None,
                    tags: str | None = None) -> str
    def recall_memory(self, query_text: str, k: int,
                     min_confidence: float,
                     conversation_id: str | None = None) -> list[dict]
    def _call_mcp(self, tool: str, arguments: dict) -> dict
    def _handle_error(self, error: Exception) -> None
```

**Size estimate**: 250-350 lines

---

### 3. context_builder.py (Assembly Layer)

```python
"""
Context assembly from history and memory sources.

Responsibilities:
- Fetch data via gateway
- Assemble context dictionary
- Token budget management
- Format for LLM prompt

NO storage decisions - pure assembly.
"""

# Key classes/functions:
class ContextBuilder:
    def __init__(self, gateway: MemoryGateway,
                history_tail_n: int = 16,
                memory_top_k: int = 8,
                min_confidence: float = 0.7,
                token_budget: int | None = None)
    def build_context(self, conversation_id: str,
                     latest_user_text: str) -> dict
    def format_for_prompt(self, context: dict) -> str
    def _truncate_to_budget(self, context: dict) -> dict
    def _count_tokens(self, text: str) -> int
    def _format_history(self, history: list[dict]) -> str
    def _format_memories(self, memories: list[tuple]) -> str
```

**Size estimate**: 200-250 lines

---

### 4. memory_policy.py (Policy Layer)

```python
"""
Memory storage policy and rate limiting.

Responsibilities:
- Determine if memory should be stored
- Enforce rate limits
- Validate memory types

Pure logic, NO I/O.
"""

# Key classes/functions:
class MemoryPolicy:
    def __init__(self, min_confidence: float = 0.7,
                max_per_window: int = 3)
    def should_store(self, memory_type: str, confidence: float) -> bool
    def enforce_rate_limit(self, window_key: str) -> bool
    def validate_memory_type(self, memory_type: str) -> bool
    def _check_confidence(self, confidence: float) -> bool
    def _check_window_limit(self, window_key: str) -> bool
    def _increment_window_count(self, window_key: str)

# In-memory state (simple dict for V1)
_window_counts: dict[str, int] = {}
```

**Size estimate**: 100-150 lines

---

### 5. models.py (Data Models)

```python
"""
Data models and validation.

All models use Python dataclasses with type hints.
"""

from dataclasses import dataclass
from typing import Optional

@dataclass
class HistoryTurn:
    conversation_id: str
    role: str  # "user" | "assistant" | "system"
    text: str
    turn_index: int
    ts: str  # ISO-8601
    message_id: Optional[str] = None
    channel: Optional[str] = None

    def validate(self) -> None:
        # Validation logic

@dataclass
class MemoryItem:
    text: str
    memory_type: str  # "preference" | "fact" | "project" | "decision"
    confidence: float  # [0.0, 1.0]
    ts: str  # ISO-8601
    conversation_id: Optional[str] = None
    entities: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[str] = None

    def validate(self) -> None:
        # Validation logic

@dataclass
class ContextPackage:
    history: list[HistoryTurn]
    memories: list[tuple[MemoryItem, float]]  # (item, similarity_score)
    latest_message: str
    metadata: dict  # token_counts, truncated, etc.
```

**Size estimate**: 100-150 lines

---

### 6. config.py (Configuration)

```python
"""
Configuration management and environment variables.
"""

from dataclasses import dataclass
from typing import Optional
import os

@dataclass
class AppConfig:
    mcp_endpoint: str
    memory_confidence_min: float
    history_tail_n: int
    memory_top_k: int
    memory_max_per_window: int
    context_token_budget: Optional[int]
    log_level: str

    @classmethod
    def from_env(cls) -> 'AppConfig':
        # Load from environment variables
        return cls(
            mcp_endpoint=os.getenv('MCP_ENDPOINT', 'chroma-mcp'),
            memory_confidence_min=float(os.getenv('MEMORY_CONFIDENCE_MIN', '0.7')),
            history_tail_n=int(os.getenv('HISTORY_TAIL_N', '16')),
            memory_top_k=int(os.getenv('MEMORY_TOP_K', '8')),
            memory_max_per_window=int(os.getenv('MEMORY_MAX_PER_WINDOW', '3')),
            context_token_budget=int(os.getenv('CONTEXT_TOKEN_BUDGET')) if os.getenv('CONTEXT_TOKEN_BUDGET') else None,
            log_level=os.getenv('LOG_LEVEL', 'INFO')
        )

    def validate(self) -> None:
        # Validation logic
```

**Size estimate**: 50-100 lines

---

### 7. exceptions.py (Custom Exceptions)

```python
"""
Custom exception hierarchy.
"""

class MCPMemoryError(Exception):
    """Base exception for MCP memory system."""
    pass

class MCPError(MCPMemoryError):
    """MCP operation failed."""
    pass

class ConnectionError(MCPMemoryError):
    """Cannot connect to MCP server."""
    pass

class ContextBuildError(MCPMemoryError):
    """Context assembly failed."""
    pass

class ValidationError(MCPMemoryError):
    """Data validation failed."""
    pass

class PolicyRejectionError(MCPMemoryError):
    """Memory rejected by policy."""
    pass
```

**Size estimate**: 50 lines

---

### 8. utils.py (Utilities)

```python
"""
Utility functions.
"""

from datetime import datetime
import json
import logging

def get_iso_timestamp() -> str:
    """Return current timestamp in ISO-8601 format."""
    return datetime.utcnow().isoformat() + 'Z'

def count_tokens(text: str) -> int:
    """Estimate token count (simple heuristic)."""
    # V1: simple word count * 1.3
    # V2: use tiktoken library
    return int(len(text.split()) * 1.3)

def setup_logging(level: str = 'INFO') -> logging.Logger:
    """Configure structured JSON logging."""
    logger = logging.getLogger('mcp_memory')
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger

class JsonFormatter(logging.Formatter):
    """JSON log formatter."""
    def format(self, record):
        # Format log as JSON
```

**Size estimate**: 100-150 lines

---

## Testing Structure

### Unit Tests (tests/unit/)

Each module has corresponding unit tests:

| Module | Test File | Coverage Target | Mocking |
|--------|-----------|-----------------|---------|
| memory_gateway.py | test_memory_gateway.py | >90% | Mock MCP calls |
| context_builder.py | test_context_builder.py | >85% | Mock gateway |
| memory_policy.py | test_memory_policy.py | >95% | No mocks (pure logic) |
| models.py | test_models.py | >90% | None |
| utils.py | test_utils.py | >80% | None |

**Example test structure** (test_memory_gateway.py):
```python
import pytest
from unittest.mock import Mock, patch
from src.memory_gateway import MemoryGateway
from src.exceptions import MCPError, ConnectionError

class TestMemoryGateway:
    def test_append_history_success(self, mock_mcp_client):
        # Test successful history append

    def test_append_history_invalid_role(self):
        # Test validation

    def test_append_history_connection_failure(self):
        # Test error handling

    def test_tail_history_success(self, mock_mcp_client):
        # Test history retrieval

    # ... more tests
```

---

### Integration Tests (tests/integration/)

**test_end_to_end.py**:
```python
"""
End-to-end flow tests with real Docker containers.
"""

def test_full_message_flow():
    # 1. Start services (docker compose up)
    # 2. Send message via app
    # 3. Verify stored in history
    # 4. Build context
    # 5. Verify context includes message
    # 6. Teardown

def test_memory_write_and_recall():
    # 1. Write memory
    # 2. Query with similar text
    # 3. Verify memory returned
```

**test_persistence.py**:
```python
"""
Test data persistence across restarts.
"""

def test_restart_persistence():
    # 1. Start, write data
    # 2. docker compose restart
    # 3. Verify data still exists

def test_full_teardown_persistence():
    # 1. Start, write data
    # 2. docker compose down
    # 3. docker compose up
    # 4. Verify data still exists
```

---

## Docker and Compose Files

### docker-compose.yml

```yaml
services:
  chroma:
    image: chromadb/chroma:latest
    container_name: chroma
    ports:
      - "8000:8000"  # Optional for debugging
    volumes:
      - chroma_data:/chroma/chroma
    environment:
      - IS_PERSISTENT=TRUE
      - ANONYMIZED_TELEMETRY=FALSE
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8000/api/v1/heartbeat"]
      interval: 10s
      timeout: 5s
      retries: 10

  chroma-mcp:
    image: ghcr.io/chroma-core/chroma-mcp:latest
    container_name: chroma-mcp
    depends_on:
      chroma:
        condition: service_healthy
    environment:
      - CHROMA_CLIENT_TYPE=http
      - CHROMA_HTTP_HOST=chroma
      - CHROMA_HTTP_PORT=8000

  agent-app:
    build: ./agent-app
    container_name: agent-app
    depends_on:
      chroma-mcp:
        condition: service_started
    environment:
      - MCP_ENDPOINT=chroma-mcp
      - MEMORY_CONFIDENCE_MIN=0.7
      - HISTORY_TAIL_N=16
      - MEMORY_TOP_K=8
      - MEMORY_MAX_PER_WINDOW=3
      - LOG_LEVEL=INFO
    # ports:
    #   - "8080:8080"  # If exposing API

volumes:
  chroma_data:
```

---

### agent-app/Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy requirements first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/
COPY scripts/ ./scripts/

# Run bootstrap then start app
CMD ["python", "-m", "src.app"]
```

---

### agent-app/requirements.txt

```
# MCP Client
mcp>=1.0.0

# Data validation
pydantic>=2.5.0

# Utilities
python-dateutil>=2.8.2

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
pytest-docker>=1.0.0

# Linting
ruff>=0.1.0
mypy>=1.7.0

# Logging
python-json-logger>=2.0.0
```

---

## File Size Estimates

| File | Lines of Code | Purpose |
|------|---------------|---------|
| app.py | 200-300 | Orchestration |
| memory_gateway.py | 250-350 | MCP transport |
| context_builder.py | 200-250 | Context assembly |
| memory_policy.py | 100-150 | Policy logic |
| models.py | 100-150 | Data models |
| config.py | 50-100 | Configuration |
| exceptions.py | 50 | Custom exceptions |
| utils.py | 100-150 | Utilities |
| **Total (src/)** | **~1,150-1,500** | **Core code** |

---

| Test File | Lines | Coverage |
|-----------|-------|----------|
| test_memory_gateway.py | 300-400 | Gateway |
| test_context_builder.py | 250-300 | Builder |
| test_memory_policy.py | 150-200 | Policy |
| test_models.py | 100-150 | Models |
| test_utils.py | 100-150 | Utils |
| test_end_to_end.py | 200-300 | Integration |
| test_persistence.py | 150-200 | Persistence |
| **Total (tests/)** | **~1,250-1,700** | **Test suite** |

**Total project size**: ~2,400-3,200 lines of code (excluding dependencies)

---

## Scripts

### scripts/setup.sh

```bash
#!/bin/bash
# Initial project setup

set -e

echo "Setting up MCP Memory V1..."

# Check dependencies
command -v docker >/dev/null 2>&1 || { echo "Docker required"; exit 1; }
command -v docker-compose >/dev/null 2>&1 || { echo "Docker Compose required"; exit 1; }

# Create .env from example
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env file"
fi

# Build images
docker-compose build

# Start services
docker-compose up -d

# Wait for ready
echo "Waiting for services..."
sleep 15

# Verify
docker-compose ps
docker-compose logs agent-app | grep "ready"

echo "✓ Setup complete"
```

---

### scripts/test-persistence.sh

```bash
#!/bin/bash
# Test persistence across restarts

set -e

echo "Testing persistence..."

# Start
docker-compose up -d
sleep 10

# Write test data
docker-compose exec agent-app python scripts/seed_data.py

# Restart
echo "Restarting..."
docker-compose restart
sleep 10

# Verify
docker-compose exec agent-app python scripts/verify_setup.py

echo "✓ Persistence test passed"
```

---

## Development Workflow

### Local Development

```bash
# 1. Clone and setup
git clone <repo>
cd mcp_memory
./scripts/setup.sh

# 2. Development with hot-reload (optional)
docker-compose -f docker-compose.dev.yml up

# 3. Run tests
docker-compose exec agent-app pytest

# 4. Run linting
docker-compose exec agent-app ruff check .
docker-compose exec agent-app mypy src/

# 5. Check coverage
docker-compose exec agent-app pytest --cov=src --cov-report=html
```

---

## Production Deployment Structure

For production, consider organizing:

```
production/
├── docker-compose.prod.yml       # Production compose file
├── .env.prod                     # Production env vars
├── nginx/                        # Reverse proxy config (if exposing API)
├── monitoring/                   # Prometheus, Grafana configs
└── backup/                       # Backup scripts and schedules
```

---

## Related Documents

- ADR-001: Docker-First Deployment
- ADR-002: ChromaDB as Vector Store
- ADR-003: Separation of Concerns
- component-diagram.md: Component architecture
- data-flows.md: Flow diagrams
- v1-specification.md: Detailed requirements
