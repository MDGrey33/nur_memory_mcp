# MCP Memory Server v7.0

A Model Context Protocol (MCP) server for persistent memory and context management with **semantic event extraction**, **graph-backed context expansion**, and **quality benchmarks**. Provides semantic search, artifact storage, and event + entity context packs.

---

## Philosophy: Total Recall Over Precision

MCP Memory is designed as an **extension of the human mind**, not just a work productivity tool.

### Core Principles

**1. Capture Everything, Filter Nothing**

The human brain processes vast amounts of information daily - conversations, observations, ideas, facts, emotions, transactions, movements, relationships. A true memory system should capture the full spectrum of human experience, not just "work events."

Modern LLMs (GPT-4o+, Claude Opus, etc.) are capable of extracting nuanced categories from any content. We should leverage this capability fully rather than constraining it to a fixed taxonomy.

**2. Noise Is Acceptable, Missing Information Is Not**

> *"All relevant data plus noise is better than partial recall with no noise."*

The human brain deals with noise constantly - irrelevant memories surface alongside relevant ones, and we naturally filter. LLMs can do the same. What they cannot do is recall information that was never stored or was filtered out during extraction.

**Prefer recall over precision.** Return more context than needed and let the consuming LLM decide relevance.

**3. Let Usage Define Structure**

Instead of pre-defining rigid categories, let the system evolve:
- **Events**: Any occurrence worth remembering - the system suggests categories, not the other way around
- **Entities**: Any person, place, thing, concept, or abstraction that participates in events
- **Relationships**: Emerge from co-occurrence in events and explicit mentions

Entity schemas should expand based on the queries received. If users frequently ask about "health" or "finances," the system should develop richer representations for those domains.

**4. Connected Context Over Isolated Facts**

Memory isn't a flat list - it's a graph. Every piece of information connects to:
- **Who** was involved (entities)
- **What** happened (events)
- **When** it occurred (temporal)
- **Where** it happened (spatial)
- **Why** it matters (causal links)
- **What else** is related (associative links)

Recall should traverse this graph liberally, returning the full context web rather than isolated matches.

### Design Implications

| Traditional Approach | MCP Memory Approach |
|---------------------|---------------------|
| Fixed event categories | Dynamic, LLM-suggested categories |
| Filter noise at extraction | Filter noise at recall (or not at all) |
| Precision-optimized retrieval | Recall-optimized retrieval |
| Schema-first design | Usage-driven schema evolution |
| Work-focused taxonomy | Life-encompassing taxonomy |

---

## What's New in V7

- **Quality Benchmark Suite** - Comprehensive benchmarks for event extraction, entity resolution, recall relevance, and graph expansion with replay mode for CI/CD
- **Outcome Evaluation** - Simple LLM-based outcome test for quick quality verification (~$0.006/run)
- **Simplified API (V5/V6)** - `remember()`, `recall()`, `forget()`, `status()` - four intuitive tools replacing 17

## Previous Releases

### V4: Graph Expansion
- **Graph-backed context expansion** - `recall(expand=true)` returns `related_context[]` and `entities[]` using graph traversal (Apache AGE in Postgres)
- **Quality-tuned defaults** - `graph_expand=true`, `graph_seed_limit=1`, smart category filters
- **Noise reduction** - Default vector distance cutoff filters low-quality hits

## Features

- **Persistent Memory Storage** - Store and retrieve memories across sessions
- **Semantic Search** - Find memories using natural language queries (OpenAI embeddings)
- **Artifact Ingestion** - Store and chunk large documents (emails, docs, code)
- **Hybrid Search** - Combined semantic + keyword search with RRF ranking
- **History Tracking** - Append-only conversation history per session
- **Event Extraction** - Extract structured events (commitments, decisions, risks) from artifacts

## Tools Available

### V5+ Simplified API (Recommended)

| Tool | Description |
|------|-------------|
| `remember` | Store content with automatic chunking, embedding, and event extraction |
| `recall` | Semantic search with optional graph expansion and entity enrichment |
| `forget` | Delete stored content with cascade confirmation |
| `status` | Check system health and extraction job status |

### Legacy Tools (V1-V4)

<details>
<summary>Click to expand legacy tools (17 total)</summary>

#### Memory Tools
- `memory_store` - Store a memory with type and confidence
- `memory_search` - Semantic search over memories
- `memory_list` - List all stored memories
- `memory_delete` - Delete a specific memory

#### History Tools
- `history_append` - Add entry to session history
- `history_get` - Retrieve session history

#### Artifact Tools
- `artifact_ingest` - Ingest and chunk large documents
- `artifact_search` - Search within artifacts
- `artifact_get` - Retrieve artifact by ID
- `artifact_delete` - Delete an artifact

#### Search Tools
- `hybrid_search` - Cross-collection search (artifacts + events) with source metadata
- `embedding_health` - Check OpenAI embedding service status

#### Event Tools
- `event_search` - Query events with filters (category, time, artifact)
- `event_get` - Get single event by ID with evidence
- `event_list` - List all events for an artifact
- `event_reextract` - Force re-extraction of events
- `job_status` - Check extraction job status

</details>

## Quick Start

### Prerequisites
- Python 3.11+
- ChromaDB running on port 8001
- PostgreSQL running on port 5432
- OpenAI API key

### Start the Server

```bash
# Start with scripts (recommended)
cd .claude-workspace/deployment
echo "OPENAI_API_KEY=sk-proj-your-key" > .env
./scripts/env-up.sh prod

# Or manually:
cd .claude-workspace/implementation/mcp-server
pip install -r requirements.txt
python src/server.py

# Start event worker (separate terminal)
python -m src.worker
```

Server runs at: `http://localhost:3001/mcp/`

### Environment Ports

| Environment | MCP | ChromaDB | PostgreSQL |
|-------------|-----|----------|------------|
| prod | 3001 | 8001 | 5432 |
| staging | 3101 | 8101 | 5532 |
| test | 3201 | 8201 | 5632 |

### HTTPS Access (via ngrok)

For Claude AI web access, use ngrok:

```bash
ngrok http 3001
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

### Claude Desktop / Claude.ai

1. Start ngrok: `ngrok http 3001`
2. Open **Claude Desktop** or **Claude.ai** (web)
3. Go to **Settings** → **Connectors**
4. Click **Add Custom Connector**
5. Enter:
   - **Name**: `memory`
   - **URL**: `https://your-ngrok-url.ngrok-free.app/mcp/`

> **Note**: Claude Desktop and Claude.ai require HTTPS. Use ngrok to expose your local server.

### Claude Code (CLI)

Create or edit `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "memory": {
      "type": "http",
      "url": "http://localhost:3001/mcp/"
    }
  }
}
```

**Important schema requirements** (Claude Code is stricter than other clients):

| Field | Required | Notes |
|-------|----------|-------|
| `type` | Yes | Must be `"http"` (not `"url"`) |
| `url` | Yes | Include trailing slash |

**Common errors:**
- `"Does not adhere to MCP server configuration schema"` - Missing `type` field or using invalid type like `"url"`
- Adding unsupported fields like `"description"` will cause validation errors

**Verify configuration:**
```bash
claude /doctor
```

**Multiple servers example:**
```json
{
  "mcpServers": {
    "memory": {
      "type": "http",
      "url": "http://localhost:3001/mcp/"
    },
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    }
  }
}
```

> **Note**: Claude Code works with `http://localhost` - no HTTPS required for local development.

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

## Quality Benchmarks (V7)

V7 includes a comprehensive benchmark suite for measuring extraction and retrieval quality.

### Quick Quality Check

```bash
cd .claude-workspace/benchmarks
export $(grep OPENAI_API_KEY ../deployment/.env)
python outcome_eval.py
```

This stores test documents, queries for connections, and uses GPT-4o-mini to verify expected outcomes. Cost: ~$0.006/run.

### Full Benchmark Suite

```bash
# Replay mode (uses fixtures, no API calls - for CI/CD)
python tests/benchmark_runner.py --mode=replay

# Live mode (requires running services)
python tests/benchmark_runner.py --mode=live
```

### Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| Retrieval MRR | First relevant result ranking | 0.60 |
| Retrieval NDCG | Overall ranking quality | 0.65 |
| Event F1 | Event extraction accuracy | 0.70 |
| Entity F1 | Entity extraction accuracy | 0.70 |
| Graph F1 | Graph expansion accuracy | 0.60 |

See [benchmarks/README.md](.claude-workspace/benchmarks/README.md) for details.

## Graph Visualization (V4: Apache AGE → Neo4j Browser)

V4 materializes an **Apache AGE** graph (inside Postgres) for context expansion. The most convenient way to *visually* explore it is to export it to CSV and load it into **Neo4j**, then use **Neo4j Browser**.

### What this shows (important)

- **Neo4j will show all nodes/edges that you exported and imported**, not a live view of Postgres/AGE.
- If your graph is large, prefer visualizing *subgraphs* (limits) instead of attempting to render everything at once.

### 1) Export the AGE graph (`nur`) from Postgres to CSV

This repo’s AGE graph name is `nur` (see `GraphService` default).

From the repo root:

```bash
mkdir -p temp/neo4j_import

# Export nodes + edges from AGE to CSV (host files)
docker exec -i postgres-v4 psql -U events -d events -v ON_ERROR_STOP=1 <<'SQL' | sed '1,2d' > temp/neo4j_import/entities.csv
LOAD 'age';
SET search_path = ag_catalog, public;
COPY (
  SELECT
    trim(both '"' from entity_id::text) AS entity_id,
    trim(both '"' from canonical_name::text) AS canonical_name,
    trim(both '"' from type::text) AS type,
    nullif(trim(both '"' from coalesce(role::text,'')), '') AS role,
    nullif(trim(both '"' from coalesce(organization::text,'')), '') AS organization
  FROM cypher('nur', $$
    MATCH (e:Entity)
    RETURN e.entity_id AS entity_id,
           e.canonical_name AS canonical_name,
           e.type AS type,
           e.role AS role,
           e.organization AS organization
  $$) AS (entity_id agtype, canonical_name agtype, type agtype, role agtype, organization agtype)
) TO STDOUT WITH (FORMAT csv, HEADER true);
SQL

docker exec -i postgres-v4 psql -U events -d events -v ON_ERROR_STOP=1 <<'SQL' | sed '1,2d' > temp/neo4j_import/events.csv
LOAD 'age';
SET search_path = ag_catalog, public;
COPY (
  SELECT
    trim(both '"' from event_id::text) AS event_id,
    trim(both '"' from category::text) AS category,
    trim(both '"' from narrative::text) AS narrative,
    trim(both '"' from artifact_uid::text) AS artifact_uid,
    trim(both '"' from revision_id::text) AS revision_id,
    nullif(trim(both '"' from coalesce(event_time::text,'')), '') AS event_time,
    (trim(both '"' from confidence::text)) AS confidence
  FROM cypher('nur', $$
    MATCH (ev:Event)
    RETURN ev.event_id AS event_id,
           ev.category AS category,
           ev.narrative AS narrative,
           ev.artifact_uid AS artifact_uid,
           ev.revision_id AS revision_id,
           ev.event_time AS event_time,
           ev.confidence AS confidence
  $$) AS (event_id agtype, category agtype, narrative agtype, artifact_uid agtype, revision_id agtype, event_time agtype, confidence agtype)
) TO STDOUT WITH (FORMAT csv, HEADER true);
SQL

docker exec -i postgres-v4 psql -U events -d events -v ON_ERROR_STOP=1 <<'SQL' | sed '1,2d' > temp/neo4j_import/acted_in.csv
LOAD 'age';
SET search_path = ag_catalog, public;
COPY (
  SELECT
    trim(both '"' from entity_id::text) AS entity_id,
    trim(both '"' from event_id::text) AS event_id,
    nullif(trim(both '"' from coalesce(role::text,'')), '') AS role
  FROM cypher('nur', $$
    MATCH (e:Entity)-[r:ACTED_IN]->(ev:Event)
    RETURN e.entity_id AS entity_id,
           ev.event_id AS event_id,
           r.role AS role
  $$) AS (entity_id agtype, event_id agtype, role agtype)
) TO STDOUT WITH (FORMAT csv, HEADER true);
SQL

docker exec -i postgres-v4 psql -U events -d events -v ON_ERROR_STOP=1 <<'SQL' | sed '1,2d' > temp/neo4j_import/about.csv
LOAD 'age';
SET search_path = ag_catalog, public;
COPY (
  SELECT
    trim(both '"' from event_id::text) AS event_id,
    trim(both '"' from entity_id::text) AS entity_id
  FROM cypher('nur', $$
    MATCH (ev:Event)-[:ABOUT]->(e:Entity)
    RETURN ev.event_id AS event_id,
           e.entity_id AS entity_id
  $$) AS (event_id agtype, entity_id agtype)
) TO STDOUT WITH (FORMAT csv, HEADER true);
SQL

docker exec -i postgres-v4 psql -U events -d events -v ON_ERROR_STOP=1 <<'SQL' | sed '1,2d' > temp/neo4j_import/possibly_same.csv
LOAD 'age';
SET search_path = ag_catalog, public;
COPY (
  SELECT
    trim(both '"' from entity_a_id::text) AS entity_a_id,
    trim(both '"' from entity_b_id::text) AS entity_b_id,
    (trim(both '"' from confidence::text)) AS confidence,
    nullif(trim(both '"' from coalesce(reason::text,'')), '') AS reason
  FROM cypher('nur', $$
    MATCH (a:Entity)-[r:POSSIBLY_SAME]->(b:Entity)
    RETURN a.entity_id AS entity_a_id,
           b.entity_id AS entity_b_id,
           r.confidence AS confidence,
           r.reason AS reason
  $$) AS (entity_a_id agtype, entity_b_id agtype, confidence agtype, reason agtype)
) TO STDOUT WITH (FORMAT csv, HEADER true);
SQL
```

### 2) Run Neo4j locally (Docker) for visualization

Start Neo4j with the CSVs mounted:

```bash
docker rm -f neo4j-local >/dev/null 2>&1 || true
docker run -d --name neo4j-local \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=none \
  -v "$PWD/temp/neo4j_import:/import" \
  neo4j:5
```

Open Neo4j Browser:
- `http://localhost:7474/browser/`

### 3) Import into Neo4j (from CSV)

```bash
docker exec -i neo4j-local cypher-shell -a bolt://localhost:7687 <<'CYPHER'
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///entities.csv' AS row
MERGE (e:Entity {entity_id: row.entity_id})
SET e.canonical_name = row.canonical_name,
    e.type = row.type,
    e.role = CASE WHEN row.role = '' THEN null ELSE row.role END,
    e.organization = CASE WHEN row.organization = '' THEN null ELSE row.organization END;

LOAD CSV WITH HEADERS FROM 'file:///events.csv' AS row
MERGE (ev:Event {event_id: row.event_id})
SET ev.category = row.category,
    ev.narrative = row.narrative,
    ev.artifact_uid = row.artifact_uid,
    ev.revision_id = row.revision_id,
    ev.event_time = CASE WHEN row.event_time = '' THEN null ELSE row.event_time END,
    ev.confidence = CASE WHEN row.confidence = '' THEN null ELSE toFloat(row.confidence) END;

LOAD CSV WITH HEADERS FROM 'file:///acted_in.csv' AS row
MATCH (e:Entity {entity_id: row.entity_id})
MATCH (ev:Event {event_id: row.event_id})
MERGE (e)-[r:ACTED_IN]->(ev)
SET r.role = CASE WHEN row.role = '' THEN null ELSE row.role END;

LOAD CSV WITH HEADERS FROM 'file:///about.csv' AS row
MATCH (ev:Event {event_id: row.event_id})
MATCH (e:Entity {entity_id: row.entity_id})
MERGE (ev)-[:ABOUT]->(e);

LOAD CSV WITH HEADERS FROM 'file:///possibly_same.csv' AS row
MATCH (a:Entity {entity_id: row.entity_a_id})
MATCH (b:Entity {entity_id: row.entity_b_id})
MERGE (a)-[r:POSSIBLY_SAME]->(b)
SET r.confidence = CASE WHEN row.confidence = '' THEN null ELSE toFloat(row.confidence) END,
    r.reason = CASE WHEN row.reason = '' THEN null ELSE row.reason END;
CYPHER
```

### 4) Visualize in Neo4j Browser

Run:

```cypher
MATCH (n)-[r]->(m)
RETURN n,r,m
LIMIT 50;
```

Confirm counts:

```cypher
MATCH (n) RETURN labels(n) AS labels, count(*) AS cnt;
MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt;
```

### Cleanup

```bash
docker rm -f neo4j-local
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
| `MCP_PORT` | 3000 | Internal container port (external: prod=3001, staging=3101, test=3201) |
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
