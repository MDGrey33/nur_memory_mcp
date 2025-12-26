# MCP Memory V1 Agent Application

An LLM agent application that implements persistent memory using ChromaDB via chroma-mcp.

## Overview

This agent provides:
- **Persistent conversation history** - Store every turn for context replay
- **Semantic memory storage** - Store high-value information for long-term recall
- **Context assembly** - Build rich context from history + memories for LLM responses
- **Memory policy** - Confidence gating and rate limiting to prevent spam

## Architecture

```
Agent App (this application)
    ↓ HTTP calls
chroma-mcp (MCP gateway)
    ↓ HTTP API
ChromaDB (vector database)
    ↓
Docker volume (persistence)
```

## Quick Start

### Using Docker Compose

```bash
# Start all services (from project root)
docker compose up -d

# View agent logs
docker compose logs -f agent-app

# Stop services
docker compose down
```

### Configuration

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Key environment variables:
- `MCP_ENDPOINT` - MCP server hostname (default: `chroma-mcp`)
- `MEMORY_CONFIDENCE_MIN` - Minimum confidence to store memories (default: `0.7`)
- `HISTORY_TAIL_N` - Number of history turns to retrieve (default: `16`)
- `MEMORY_TOP_K` - Number of memories to retrieve (default: `8`)
- `MEMORY_MAX_PER_WINDOW` - Rate limit per time window (default: `3`)
- `LOG_LEVEL` - Logging verbosity (default: `INFO`)

## Core Modules

### memory_gateway.py
Transport layer for all MCP/ChromaDB operations. Handles:
- Collection management
- Document storage (history + memory)
- Document retrieval (tail history, semantic search)
- Error handling and retries

### context_builder.py
Assembles context from multiple sources:
- Fetches history tail (last N turns)
- Recalls relevant memories (semantic search)
- Formats for LLM consumption
- Handles token budget truncation

### memory_policy.py
Implements storage policies:
- Confidence threshold gating
- Rate limiting per time window
- Memory type validation

### models.py
Data models:
- `HistoryTurn` - Single conversation turn
- `MemoryItem` - Long-term memory
- `ContextPackage` - Complete context for LLM

### app.py
Main application orchestrating all components.

## Usage Example

```python
from src.app import Application
from src.config import AppConfig
import asyncio

async def main():
    # Load config
    config = AppConfig.from_env()

    # Create app
    app = Application(config)

    # Start (bootstraps collections)
    await app.start()

    # Handle a message
    await app.handle_message(
        conversation_id="conv_123",
        role="user",
        text="Hello!",
        turn_index=1
    )

    # Store a memory
    await app.store_memory(
        text="User prefers concise responses",
        memory_type="preference",
        confidence=0.85,
        conversation_id="conv_123"
    )

asyncio.run(main())
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_memory_gateway.py
```

### Linting

```bash
# Check code style
ruff check .

# Type checking
mypy src/
```

### Local Development (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export MCP_ENDPOINT=localhost
export LOG_LEVEL=DEBUG

# Run application
python -m src.app
```

## Data Flows

### 1. Append History
Every message is stored in the `history` collection with metadata (conversation_id, role, timestamp, turn_index).

### 2. Write Memory
High-confidence information is stored in the `memory` collection with type, confidence, and metadata.

### 3. Build Context
Before generating a response:
1. Fetch last N history turns (chronological)
2. Semantic search for top-K relevant memories
3. Assemble into context package
4. Format for LLM prompt

### 4. Bootstrap
On startup:
1. Connect to MCP server
2. Ensure `history` and `memory` collections exist
3. Initialize components
4. Mark as ready

## Troubleshooting

### Application won't start
- Check MCP_ENDPOINT is correct
- Verify chroma-mcp container is running
- Check logs: `docker compose logs agent-app`

### Collections not created
- Ensure ChromaDB is healthy: `docker compose ps`
- Check chroma-mcp connection: `docker compose logs chroma-mcp`

### Memory not storing
- Check confidence threshold: must be >= MEMORY_CONFIDENCE_MIN
- Check rate limit: max MEMORY_MAX_PER_WINDOW per time window
- Review logs for policy rejections

### Context build fails
- Verify history and memory collections exist
- Check ChromaDB connectivity
- Review gateway error logs

## Testing Persistence

```bash
# Start services
docker compose up -d

# Store some data
docker compose exec agent-app python -m src.app

# Restart containers
docker compose restart

# Verify data persists
docker compose logs agent-app
```

## Performance

Expected latencies (p95):
- History append: < 100ms
- Memory write: < 150ms
- Context build: < 500ms (parallel fetch)

## Production Considerations

- **Volume backups**: Regularly backup the `chroma_data` volume
- **Monitoring**: Export metrics for history/memory counts, latencies
- **Scaling**: Current design is single-instance; use load balancer for multiple instances
- **Token budgets**: Set CONTEXT_TOKEN_BUDGET to prevent excessive context sizes

## Version

**V1.0.0** - Initial release with core functionality

## License

See project root LICENSE file.
