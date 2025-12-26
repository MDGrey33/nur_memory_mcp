# MCP Memory Server v2.0

A Model Context Protocol (MCP) server for persistent memory and context management. Provides semantic search, artifact storage, and hybrid retrieval capabilities.

## Features

- **Persistent Memory Storage** - Store and retrieve memories across sessions
- **Semantic Search** - Find memories using natural language queries (OpenAI embeddings)
- **Artifact Ingestion** - Store and chunk large documents (emails, docs, code)
- **Hybrid Search** - Combined semantic + keyword search with RRF ranking
- **History Tracking** - Append-only conversation history per session
- **Privacy Filtering** - Automatic PII detection and filtering

## Tools Available (12 total)

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

### Advanced Tools
- `hybrid_search` - Cross-collection semantic + keyword search
- `embedding_health` - Check OpenAI embedding service status

## Quick Start

### Prerequisites
- Python 3.11+
- ChromaDB running on port 8001
- OpenAI API key

### Start the Server

```bash
cd .claude-workspace/implementation/mcp-server
pip install -r requirements.txt
python src/server.py
```

Server runs at: `http://localhost:3000/mcp/`

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
      "url": "http://localhost:3000/mcp/"
    }
  }
}
```

### Claude Desktop

Claude Desktop requires stdio transport. Use `mcp-remote` proxy:

```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-remote", "https://your-ngrok-url.ngrok-free.app/mcp/"]
    }
  }
}
```

### Claude AI (Web)

Use the HTTPS ngrok URL directly in Claude AI's MCP configuration.

## Testing

### Automated Tests

```bash
# Full user simulation (HTTP client)
python3 .claude-workspace/tests/e2e/full_user_simulation.py

# Browser UI automation (requires Playwright)
cd .claude-workspace/tests/e2e
npm install playwright
npx playwright install chromium
node browser_mcp_test.js
```

### Health Check

```bash
curl http://localhost:3000/health
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│  MCP Clients    │────▶│  MCP Server     │
│  (Cursor/Claude)│     │  (Streamable    │
└─────────────────┘     │   HTTP)         │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │    ChromaDB     │
                        │  (Vector Store) │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │  OpenAI API     │
                        │  (Embeddings)   │
                        └─────────────────┘
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_PORT` | 3000 | Server port |
| `CHROMA_HOST` | localhost | ChromaDB host |
| `CHROMA_PORT` | 8001 | ChromaDB port |
| `OPENAI_API_KEY` | (required) | OpenAI API key for embeddings |
| `OPENAI_EMBED_MODEL` | text-embedding-3-large | Embedding model |
| `LOG_LEVEL` | INFO | Logging level |

## Project Structure

```
mcp_memory/
├── .claude/                    # Claude Code configuration
│   ├── docs/                   # Workflow documentation
│   └── settings.json           # Hooks configuration
├── .claude-workspace/          # Build artifacts
│   ├── implementation/         # Source code
│   │   └── mcp-server/         # MCP server implementation
│   ├── tests/                  # Test suites
│   │   └── e2e/                # End-to-end tests
│   └── deployment/             # Docker configs
├── CLAUDE.md                   # Project instructions
└── README.md                   # This file
```

## License

Private - All rights reserved.
