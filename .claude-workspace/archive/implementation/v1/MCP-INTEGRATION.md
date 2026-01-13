# MCP Integration Guide

How to integrate Chroma MCP Memory into Claude Desktop or Claude Code.

## Architecture

```
Claude Desktop/Code
       ↓ (MCP protocol via stdio)
chroma-mcp server
       ↓ (HTTP)
ChromaDB (persistent storage)
```

## Step 1: Start ChromaDB

ChromaDB must be running before connecting the MCP server.

```bash
# Start only ChromaDB (not the full stack)
docker run -d \
  --name chromadb \
  -p 8000:8000 \
  -v chroma_data:/chroma/chroma \
  -e IS_PERSISTENT=TRUE \
  -e ANONYMIZED_TELEMETRY=FALSE \
  chromadb/chroma:latest
```

Verify it's running:
```bash
curl http://localhost:8000/api/v1/heartbeat
```

## Step 2: Configure MCP in Claude

### For Claude Desktop

Edit your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add the chroma-mcp server:

```json
{
  "mcpServers": {
    "chroma-memory": {
      "command": "uvx",
      "args": ["chroma-mcp"],
      "env": {
        "CHROMA_CLIENT_TYPE": "http",
        "CHROMA_HTTP_HOST": "localhost",
        "CHROMA_HTTP_PORT": "8000"
      }
    }
  }
}
```

**Alternative using npx:**
```json
{
  "mcpServers": {
    "chroma-memory": {
      "command": "npx",
      "args": ["-y", "chroma-mcp"],
      "env": {
        "CHROMA_CLIENT_TYPE": "http",
        "CHROMA_HTTP_HOST": "localhost",
        "CHROMA_HTTP_PORT": "8000"
      }
    }
  }
}
```

### For Claude Code

Add to your `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "chroma-memory": {
      "command": "uvx",
      "args": ["chroma-mcp"],
      "env": {
        "CHROMA_CLIENT_TYPE": "http",
        "CHROMA_HTTP_HOST": "localhost",
        "CHROMA_HTTP_PORT": "8000"
      }
    }
  }
}
```

## Step 3: Restart Claude

- **Claude Desktop**: Quit and reopen
- **Claude Code**: Run `/mcp` to see connected servers

## Step 4: Verify Connection

Ask Claude:
> "What MCP tools do you have available for chroma?"

You should see tools like:
- `chroma_list_collections`
- `chroma_create_collection`
- `chroma_add_documents`
- `chroma_query_documents`
- `chroma_get_documents`

## Step 5: Test Memory Operations

Try these prompts:

**Create collections:**
> "Create two chroma collections: 'history' and 'memory'"

**Store a memory:**
> "Add a document to the 'memory' collection with text 'User prefers dark mode' and metadata type=preference, confidence=0.9"

**Query memories:**
> "Search the 'memory' collection for 'user preferences'"

**Check persistence:**
> "List all collections and their document counts"

## Troubleshooting

### "chroma-mcp not found"

Install it first:
```bash
# Using pip
pip install chroma-mcp

# Or using uvx (recommended)
uvx chroma-mcp --help
```

### "Connection refused to localhost:8000"

ChromaDB isn't running. Start it:
```bash
docker start chromadb
# or
docker run -d --name chromadb -p 8000:8000 -v chroma_data:/chroma/chroma chromadb/chroma:latest
```

### "MCP server not showing up"

1. Check config JSON syntax (use a JSON validator)
2. Verify the command works standalone: `uvx chroma-mcp`
3. Check Claude logs for errors

### View ChromaDB data directly

```bash
# List collections
curl http://localhost:8000/api/v1/collections

# Count documents
curl http://localhost:8000/api/v1/collections/memory/count
```

## What About agent-app?

The `agent-app` we built contains:
- **Memory policy** (confidence gating, rate limiting)
- **Context builder** (assembles history + memories for prompts)

These are **optional enhancements**. For basic experimentation:
- Just use ChromaDB + chroma-mcp directly
- Claude can call the MCP tools to store/retrieve

For production use with policy enforcement:
- Run the full docker-compose stack
- Have your app call the agent-app APIs

## Quick Start Summary

```bash
# 1. Start ChromaDB
docker run -d --name chromadb -p 8000:8000 \
  -v chroma_data:/chroma/chroma \
  -e IS_PERSISTENT=TRUE \
  chromadb/chroma:latest

# 2. Add to Claude config (see above)

# 3. Restart Claude

# 4. Test: "Create a chroma collection called 'test'"
```

That's it! You now have persistent memory in Claude.
