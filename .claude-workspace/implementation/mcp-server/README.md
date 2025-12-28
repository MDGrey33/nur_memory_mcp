# MCP Memory Server v4.0 (HTTP Transport)

A persistent memory system for Claude using HTTP-based MCP transport with **semantic event extraction** and **V4 graph-backed context expansion**. Just point Claude to a URL.

**Version**: 4.0.0 | **Status**: Production Ready

## Quick Start

### 1. Start the server

```bash
# Start ChromaDB first
docker run -d --name chromadb -p 8001:8000 \
  -v chroma_data:/chroma/chroma \
  -e IS_PERSISTENT=TRUE \
  chromadb/chroma:latest

# Install dependencies
pip install -r requirements.txt

# Run the server
cd mcp-server
python src/server.py
```

Or use Docker Compose:
```bash
docker compose up -d
```

### 2. Configure Claude

**For Claude Code**, add to `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "memory": {
      "url": "http://localhost:3000/mcp/"
    }
  }
}
```

**For Claude Desktop / Claude.ai**:

1. Start ngrok: `ngrok http 3000`
2. Open **Claude Desktop** or **Claude.ai** (web)
3. Go to **Settings** → **Connectors**
4. Click **Add Custom Connector**
5. Enter:
   - **Name**: `memory`
   - **URL**: `https://your-ngrok-url.ngrok-free.app/mcp/`

> **Note**: Claude Desktop and Claude.ai require HTTPS. Use ngrok to expose your local server.

**Important**: Include the trailing slash in the URL!

## Client Compatibility Notes (Claude Desktop / Cursor)

This MCP server uses **Streamable HTTP** (long-lived **SSE**).

- **Canonical URL**: configure clients with the trailing slash: `.../mcp/`
- **Clients may still use `/mcp`**: some clients will send requests to `/mcp` (no trailing slash) even if configured with `/mcp/`.
  - The server supports this by issuing a **relative** redirect: `Location: /mcp/` (HTTP 307) and then serving MCP on `/mcp/`.
- **Behind proxies (ngrok, reverse proxy)**: redirects must preserve HTTPS.
  - The server honors forwarded headers so `/mcp` never redirects to `http://...` when accessed via `https://...`.

### 3. Restart Claude and test

Ask Claude:
> "Store a memory that I prefer Python over JavaScript"

Then later:
> "What do you remember about my coding preferences?"

## Available Tools (17 total)

### Memory Tools
| Tool | Description |
|------|-------------|
| `memory_store` | Store a memory with type and confidence |
| `memory_search` | Semantic search over memories |
| `memory_list` | List all stored memories |
| `memory_delete` | Delete a specific memory |

### History Tools
| Tool | Description |
|------|-------------|
| `history_append` | Add to conversation history |
| `history_get` | Retrieve conversation history |

### Artifact Tools
| Tool | Description |
|------|-------------|
| `artifact_ingest` | Ingest documents with automatic chunking |
| `artifact_search` | Search across artifacts |
| `artifact_get` | Get artifact by ID |
| `artifact_delete` | Delete an artifact |

### Search Tools
| Tool | Description |
|------|-------------|
| `hybrid_search` | Cross-collection semantic search |
| `embedding_health` | Check embedding service health |

### V3+ Semantic Event Tools
| Tool | Description |
|------|-------------|
| `event_search` | Query events with filters (category, time, artifact) |
| `event_get` | Get single event by ID with evidence |
| `event_list` | List all events for an artifact |
| `event_reextract` | Force re-extraction of events |
| `job_status` | Check extraction job status |

## Configuration

Environment variables:

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

### V3: PostgreSQL (Events)
| Variable | Default | Description |
|----------|---------|-------------|
| `EVENTS_DB_DSN` | (required) | Postgres connection string |
| `POSTGRES_POOL_MIN` | 2 | Min pool connections |
| `POSTGRES_POOL_MAX` | 10 | Max pool connections |

### V3: Event Extraction
| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_EVENT_MODEL` | gpt-4o-mini | Model for event extraction |
| `EVENT_MAX_ATTEMPTS` | 5 | Max retry attempts |
| `POLL_INTERVAL_MS` | 1000 | Worker poll interval |

## Verify It's Working

```bash
# Health check
curl http://localhost:3000/health

# MCP endpoint (should return SSE error without proper headers)
curl http://localhost:3000/mcp/
```

## Persistence

All data is stored in ChromaDB with Docker volumes. Your memories survive:
- Container restarts
- Server updates
- Docker Compose down/up

To completely reset:
```bash
docker volume rm chroma_data
```

## Architecture

```
Claude Desktop/Code
       ↓
   HTTP (port 3000)
       ↓
MCP Memory Server (Streamable HTTP)
       ↓
   ┌─────────────────┬─────────────────┐
   ↓                 ↓                 ↓
ChromaDB         PostgreSQL      Event Worker
(port 8001)      (port 5432)     (background)
   │                 │                 │
   │   Embeddings    │   Events &      │   LLM
   │   & Vectors     │   Job Queue     │   Extraction
   └─────────────────┴─────────────────┘
```

### V3 Event Flow
1. User ingests artifact via `artifact_ingest`
2. Server writes to ChromaDB (embeddings) + PostgreSQL (revision)
3. Job enqueued for event extraction
4. Event Worker claims job, calls OpenAI for extraction
5. Events written to PostgreSQL with evidence links
6. User queries via `event_search`, `event_list`, etc.

## Troubleshooting

### "Connection refused"
Server isn't running:
```bash
python src/server.py
```

### Tools don't appear in Claude
1. Check URL has trailing slash: `http://localhost:3000/mcp/`
2. Restart Claude completely
3. Check server logs: `python src/server.py` (in foreground)

### ChromaDB errors
```bash
# Check if ChromaDB is running
curl http://localhost:8001/api/v2/heartbeat
```
