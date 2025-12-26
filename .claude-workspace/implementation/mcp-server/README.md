# MCP Memory Server (HTTP Transport)

A persistent memory system for Claude using HTTP-based MCP transport. Just point Claude to a URL.

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

**For Claude Desktop**, edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "memory": {
      "url": "http://localhost:3000/mcp/"
    }
  }
}
```

**Important**: Include the trailing slash in the URL: `http://localhost:3000/mcp/`

### 3. Restart Claude and test

Ask Claude:
> "Store a memory that I prefer Python over JavaScript"

Then later:
> "What do you remember about my coding preferences?"

## Available Tools

| Tool | Description |
|------|-------------|
| `memory_store` | Store a memory with type and confidence |
| `memory_search` | Semantic search over memories |
| `memory_list` | List all stored memories |
| `memory_delete` | Delete a specific memory |
| `history_append` | Add to conversation history |
| `history_get` | Retrieve conversation history |

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CHROMA_HOST` | localhost | ChromaDB hostname |
| `CHROMA_PORT` | 8001 | ChromaDB port |
| `MCP_PORT` | 3000 | MCP server port |
| `LOG_LEVEL` | INFO | Logging verbosity |

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
   HTTP (port 8001)
       ↓
ChromaDB (Docker volume)
```

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
