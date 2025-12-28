# MCP Memory Server v3.0

A Model Context Protocol (MCP) server for persistent memory and context management with **semantic event extraction**. Provides semantic search, artifact storage, and intelligent event analysis.

## What's New in V3

- **Semantic Event Extraction** - Automatically extracts commitments, decisions, risks from documents
- **Evidence Linking** - Every extracted event includes source quotes with character offsets
- **PostgreSQL Storage** - Events stored in Postgres with full-text search
- **Async Worker Pipeline** - Background event extraction with retry logic
- **Source Metadata** - Track document dates, source types, and author context for credibility reasoning
- **Hybrid Search with Events** - Search across artifacts AND events in one query

## Features

- **Persistent Memory Storage** - Store and retrieve memories across sessions
- **Semantic Search** - Find memories using natural language queries (OpenAI embeddings)
- **Artifact Ingestion** - Store and chunk large documents (emails, docs, code)
- **Hybrid Search** - Combined semantic + keyword search with RRF ranking
- **History Tracking** - Append-only conversation history per session
- **Event Extraction** - Extract structured events (commitments, decisions, risks) from artifacts

## Tools Available (17 total)

### Memory Tools
- `memory_store` - Store a memory with type and confidence
- `memory_search` - Semantic search over memories
- `memory_list` - List all stored memories
- `memory_delete` - Delete a specific memory

### History Tools
- `history_append` - Add entry to session history
- `history_get` - Retrieve session history

### Artifact Tools
- `artifact_ingest` - Ingest and chunk large documents
- `artifact_search` - Search within artifacts
- `artifact_get` - Retrieve artifact by ID
- `artifact_delete` - Delete an artifact

### Search Tools
- `hybrid_search` - Cross-collection search (artifacts + events) with source metadata
- `embedding_health` - Check OpenAI embedding service status

### V3 Event Tools
- `event_search` - Query events with filters (category, time, artifact)
- `event_get` - Get single event by ID with evidence
- `event_list` - List all events for an artifact
- `event_reextract` - Force re-extraction of events
- `job_status` - Check extraction job status

## Quick Start

### Prerequisites
- Python 3.11+
- ChromaDB running on port 8001
- PostgreSQL running on port 5432
- OpenAI API key

### Start the Server

```bash
# Start services with Docker Compose
cd .claude-workspace/deployment
docker-compose up -d

# Or manually:
cd .claude-workspace/implementation/mcp-server
pip install -r requirements.txt
python src/server.py

# Start event worker (separate terminal)
python -m src.worker
```

Server runs at: `http://localhost:3001/mcp/`

### HTTPS Access (via ngrok)

For Claude AI web access, use ngrok:

```bash
ngrok http 3000
```

This provides an HTTPS URL like: `https://xxxx.ngrok-free.app/mcp/`

## Client Configuration

### Cursor IDE

Edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "memory": {
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

### Claude Desktop

1. Open Claude Desktop → **Settings** → **Connectors**
2. Click **Add Custom Connector**
3. Enter:
   - **Name**: `memory`
   - **URL**: `https://your-ngrok-url.ngrok-free.app/mcp/`

> **Note**: Claude Desktop requires HTTPS. Use ngrok to expose your local server.

## MCP Transport Semantics (Read This Before Wiring Clients)

This server uses **Streamable HTTP** (long-lived **SSE** under the hood).

- **Use the canonical endpoint**: always configure clients with a trailing slash: `.../mcp/`
- **Clients may call `/mcp` anyway**: some clients (including Claude connector validation) will send requests to `/mcp` (no trailing slash). The server must support this and route the client to `/mcp/` safely.
- **Redirects must preserve HTTPS**: when exposed behind a proxy (e.g., ngrok), any redirect from `/mcp` must not downgrade to `http://...`. The server should either:
  - handle `/mcp` directly, or
  - issue a **relative** redirect (`Location: /mcp/`) and honor forwarded proto/host headers.

## Testing

### Automated Tests

```bash
# Full user simulation (22 tests)
python3 .claude-workspace/tests/e2e/full_user_simulation.py

# Event extraction validation
python3 .claude-workspace/tests/e2e/validate_event_extraction.py

# Test sample documents
cd .claude-workspace/tests/e2e/sample_docs
python test_samples.py all
```

### Health Check

```bash
curl http://localhost:3001/health
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│  MCP Clients    │────▶│  MCP Server     │
│  (Cursor/Claude)│     │  (Streamable    │
└─────────────────┘     │   HTTP)         │
                        └────────┬────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
          ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    ChromaDB     │    │   PostgreSQL    │    │  Event Worker   │
│  (Vector Store) │    │   (Events DB)   │    │  (Background)   │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
                       ┌────────▼────────┐
                       │   OpenAI API    │
                       │  (Embeddings +  │
                       │   Extraction)   │
                       └─────────────────┘
```

## Environment Variables

### Core
| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_PORT` | 3000 | Server port |
| `OPENAI_API_KEY` | (required) | OpenAI API key |
| `LOG_LEVEL` | INFO | Logging level |

### ChromaDB
| Variable | Default | Description |
|----------|---------|-------------|
| `CHROMA_HOST` | localhost | ChromaDB host |
| `CHROMA_PORT` | 8001 | ChromaDB port |

### V3: PostgreSQL
| Variable | Default | Description |
|----------|---------|-------------|
| `EVENTS_DB_DSN` | (required) | Postgres connection string |
| `POSTGRES_POOL_MIN` | 2 | Min pool connections |
| `POSTGRES_POOL_MAX` | 10 | Max pool connections |

### V3: Event Extraction
| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_EVENT_MODEL` | gpt-4o-mini | Model for extraction |
| `EVENT_MAX_ATTEMPTS` | 5 | Max retry attempts |

## Project Structure

```
mcp_memory/
├── .claude/                    # Claude Code configuration
│   ├── docs/                   # Workflow documentation
│   └── settings.json           # Hooks configuration
├── .claude-workspace/          # Build artifacts
│   ├── implementation/         # Source code
│   │   └── mcp-server/         # MCP server implementation
│   │       ├── src/
│   │       │   ├── server.py          # Main MCP server
│   │       │   ├── services/          # V3 services
│   │       │   ├── storage/           # Postgres client
│   │       │   ├── tools/             # Event tools
│   │       │   └── worker/            # Event extraction worker
│   │       └── migrations/            # SQL migrations
│   ├── tests/                  # Test suites
│   │   └── e2e/                # End-to-end tests
│   └── deployment/             # Docker configs
├── CLAUDE.md                   # Project instructions
└── README.md                   # This file
```

## Event Categories

V3 extracts 8 types of semantic events:

| Category | Description |
|----------|-------------|
| Commitment | Promises, deadlines, deliverables |
| Execution | Actions taken, completions |
| Decision | Choices made, directions set |
| Collaboration | Meetings, discussions, handoffs |
| QualityRisk | Issues, blockers, concerns |
| Feedback | User input, reviews, critiques |
| Change | Modifications, pivots, updates |
| Stakeholder | Who's involved, roles |

## Source Metadata

V3 supports rich source metadata for credibility reasoning. When ingesting artifacts, you can provide:

| Field | Values | Purpose |
|-------|--------|---------|
| `document_date` | ISO date (YYYY-MM-DD) | When document was authored |
| `source_type` | email, slack, meeting_notes, document, policy, contract, chat, transcript, wiki, ticket | Document origin |
| `document_status` | draft, final, approved, superseded, archived | Document lifecycle stage |
| `author_title` | Free text (e.g., "CEO", "Project Lead") | Author's role |
| `distribution_scope` | private, team, department, company, public | Intended audience |

This metadata flows through to events, enabling models to reason about:
- **Recency**: Which information is most current
- **Authority**: Who made statements and in what capacity
- **Formality**: Draft vs. approved documents
- **Context**: Meeting notes vs. official policy

## License

Private - All rights reserved.
