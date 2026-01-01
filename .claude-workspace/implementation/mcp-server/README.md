# MCP Memory Server v6.2 (HTTP Transport)

A persistent memory system for Claude using HTTP-based MCP transport with **semantic event extraction** and **graph-backed context expansion**.

**Version**: 6.2.0 | **Status**: Production Ready

## Port Configuration

| Environment | Compose File | Default Port |
|-------------|--------------|--------------|
| Default/Prod | `docker-compose.yml` | 3000 |
| Local Dev | `docker-compose.local.yml` | 3001 |
| Test | `docker-compose.test.yml` | 3201 |

*Source of truth: `.claude-workspace/deployment/` compose files*

## Quick Start

### 1. Start the server

```bash
cd .claude-workspace/deployment
docker compose up -d
```

Or manually:
```bash
# Start infrastructure
docker run -d --name chromadb -p 8001:8000 chromadb/chroma:0.5.23
docker run -d --name postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres pgvector/pgvector:pg16

# Run the server
cd mcp-server
pip install -r requirements.txt
python src/server.py
```

### 2. Configure Claude

**For Claude Code**, add to `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "memory": {
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

**For Claude Desktop / Claude.ai**:

1. Start ngrok: `ngrok http 3001`
2. Go to **Settings** → **Connectors** → **Add Custom Connector**
3. Enter:
   - **Name**: `memory`
   - **URL**: `https://your-ngrok-url.ngrok-free.app/mcp/`

> **Note**: Claude Desktop and Claude.ai require HTTPS. Use ngrok to expose your local server.

**Important**: Include the trailing slash in the URL!

### 3. Test it

Ask Claude:
> "Remember that I prefer Python over JavaScript"

Then later:
> "What do you recall about my coding preferences?"

## Available Tools (4)

| Tool | Description |
|------|-------------|
| `remember` | Store content with automatic chunking, embedding, and event extraction |
| `recall` | Find content with semantic search and graph expansion |
| `forget` | Delete content with cascade (chunks, events, entities) |
| `status` | Check system health and job status |

### remember()

```python
remember(
    content: str,           # Required: text to store
    context: str = None,    # meeting, email, note, preference, fact, conversation
    source: str = None,     # gmail, slack, manual, user
    importance: float = 0.5,
    title: str = None,
    author: str = None,
    participants: List[str] = None,
    date: str = None,       # ISO8601
)
```

### recall()

```python
recall(
    query: str = None,      # Semantic search
    id: str = None,         # Direct lookup (art_xxx or evt_xxx)
    context: str = None,    # Filter by type
    limit: int = 10,
    expand: bool = True,    # Graph expansion (default ON)
    include_events: bool = True,
    include_entities: bool = True,
)
```

### forget()

```python
forget(
    id: str,                # art_xxx only
    confirm: bool = False,  # Safety flag (required)
)
```

### status()

```python
status(
    artifact_id: str = None,  # Check specific job status
)
```

## Configuration

Environment variables (see `.env.example`):

### Core
| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_PORT` | 3000 | MCP server port |
| `LOG_LEVEL` | INFO | Logging verbosity |
| `OPENAI_API_KEY` | (required) | OpenAI API key for embeddings |

### ChromaDB
| Variable | Default | Description |
|----------|---------|-------------|
| `CHROMA_HOST` | localhost | ChromaDB hostname |
| `CHROMA_PORT` | 8001 | ChromaDB port |

### PostgreSQL
| Variable | Default | Description |
|----------|---------|-------------|
| `EVENTS_DB_DSN` | (required) | Postgres connection string |
| `POSTGRES_POOL_MIN` | 2 | Min pool connections |
| `POSTGRES_POOL_MAX` | 10 | Max pool connections |

### Event Extraction
| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_EVENT_MODEL` | gpt-4o-mini | Model for event extraction |
| `EVENT_MAX_ATTEMPTS` | 5 | Max retry attempts |
| `POLL_INTERVAL_MS` | 1000 | Worker poll interval |

## Verify It's Working

```bash
# Health check
curl http://localhost:3001/health

# MCP endpoint
curl http://localhost:3001/mcp/
```

## Architecture

```
Claude Desktop/Code
       ↓
   HTTP (port 3001)
       ↓
MCP Memory Server (Streamable HTTP)
       ↓
   ┌─────────────────┬─────────────────┐
   ↓                 ↓                 ↓
ChromaDB         PostgreSQL      Event Worker
(port 8001)      (port 5432)     (background)
   │                 │                 │
   │  content &      │  Events &       │  LLM
   │  chunks         │  Entities       │  Extraction
   └─────────────────┴─────────────────┘
```

### Data Flow

1. User calls `remember(content="...")`
2. Server generates content-based ID (`art_` + SHA256[:12])
3. Content stored in ChromaDB with embeddings
4. Large content (>900 tokens) chunked with overlap
5. Job enqueued for semantic event extraction
6. Event Worker extracts events via OpenAI
7. Entities resolved and linked
8. User queries via `recall()` with graph expansion

### Graph Expansion

When `recall(expand=True)`:
1. Primary search finds matching documents
2. Extract events from primary results
3. Find entities (actors/subjects) in those events
4. Find OTHER events with same entities
5. Return as `related[]` with connection reason

## Troubleshooting

### "Connection refused"
Server isn't running:
```bash
python src/server.py
```

### Tools don't appear in Claude
1. Check URL has trailing slash: `http://localhost:3001/mcp/`
2. Restart Claude completely
3. Check server logs

### ChromaDB errors
```bash
curl http://localhost:8001/api/v2/heartbeat
```

## Running Tests

```bash
cd mcp-server
source .venv/bin/activate

# Unit + Integration tests
PYTHONPATH=src pytest tests/unit ../../tests/v6 -v

# E2E tests (requires running Docker)
MCP_URL="http://localhost:3001/mcp/" PYTHONPATH=src pytest ../../tests/v6/e2e/ --run-e2e -v
```
