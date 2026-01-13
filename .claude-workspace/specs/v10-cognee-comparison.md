# V10: Cognee Side-by-Side Comparison

**Version**: 10.0.0
**Status**: Planning
**Created**: 2026-01-13
**Depends on**: V9 quality gates (optional - can run in parallel)

---

## Executive Summary

Create a minimal MCP wrapper around the [Cognee](https://github.com/topoteretes/cognee) library that exposes the same `remember`/`recall` interface as our server. Use our existing benchmark harness (which already supports `MCP_URL` configuration) to run identical tests against both implementations and compare results.

**Effort**: 1-2 days
**Risk**: Low (isolated implementation, no changes to existing code)
**Outcome**: Data-driven decision on whether to adopt Cognee

---

## Architecture

### Side-by-Side Deployment

```
                    ┌─────────────────────────┐
                    │    Benchmark Harness    │
                    │    (existing code)      │
                    │                         │
                    │  MCP_URL configurable   │
                    └───────────┬─────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 │                 ▼
┌─────────────────────┐         │   ┌─────────────────────┐
│  MCP Memory Server  │         │   │  MCP Cognee Server  │
│  (Our Implementation)│         │   │  (Cognee Wrapper)   │
│                     │         │   │                     │
│  Port: 3001         │         │   │  Port: 3002         │
│                     │         │   │                     │
│  Tools:             │         │   │  Tools:             │
│  - remember()       │         │   │  - remember()       │
│  - recall()         │         │   │  - recall()         │
│  - forget()         │         │   │  - forget()         │
│  - status()         │         │   │  - status()         │
└──────────┬──────────┘         │   └──────────┬──────────┘
           │                    │              │
           ▼                    │              ▼
┌─────────────────────┐         │   ┌─────────────────────┐
│  ChromaDB           │         │   │  Cognee Storage     │
│  PostgreSQL         │         │   │  (SQLite/Postgres)  │
└─────────────────────┘         │   └─────────────────────┘
                                │
                    Same corpus, same queries,
                    same ground truth
```

### Why This Works

Our existing benchmarks already support configurable URLs:

```python
# outcome_eval.py
MCP_URL = os.getenv("MCP_URL", "http://localhost:3001")

# benchmark_runner.py
mcp_url = os.environ.get('MCP_URL', 'http://localhost:3001')

# retrieval_benchmark.py
MCP_URL = os.getenv("MCP_URL", "http://localhost:3001")
```

**Zero changes needed to benchmark code.**

---

## Cognee API Analysis

### Installation

```bash
pip install cognee
```

### Core API (from Cognee docs)

```python
import cognee

# Configure
cognee.config.llm_api_key = "sk-..."
cognee.config.set_llm_provider("openai")

# Add content (like our remember)
await cognee.add("text content", dataset_name="default")
await cognee.add(["list", "of", "texts"], dataset_name="default")

# Process/extract (builds knowledge graph)
await cognee.cognify()

# Search (like our recall)
results = await cognee.search(
    query_type="INSIGHTS",  # or "CHUNKS", "GRAPH_COMPLETION"
    query_text="search query",
    datasets=["default"]
)

# Reset (like our forget - but global)
await cognee.prune.prune_data()
await cognee.prune.prune_system(metadata=True)
```

### Cognee Search Types

| Type | Description | Maps To |
|------|-------------|---------|
| `INSIGHTS` | High-level knowledge answers | Our default recall |
| `CHUNKS` | Raw text chunks | Our `include_content=True` |
| `GRAPH_COMPLETION` | Graph traversal results | Our graph expansion |
| `SUMMARIES` | Document summaries | N/A |

### Cognee Response Format

```python
# cognee.search() returns list of results
[
    {
        "id": "...",
        "text": "...",           # Content
        "score": 0.85,           # Similarity
        "metadata": {...},
        # For graph results:
        "source_node": {...},
        "target_node": {...},
        "relationship": "..."
    }
]
```

---

## Implementation

### Directory Structure

```
.claude-workspace/implementation/cognee-server/
├── src/
│   ├── __init__.py
│   ├── server.py              # MCP server entry point
│   ├── cognee_adapter.py      # Cognee API wrapper
│   └── response_normalizer.py # Convert Cognee → Our format
├── requirements.txt
├── Dockerfile
└── README.md
```

### File 1: requirements.txt

```
cognee>=0.1.0
fastmcp>=0.1.0
httpx>=0.25.0
python-dotenv>=1.0.0
```

### File 2: src/server.py

```python
#!/usr/bin/env python3
"""
MCP Cognee Server - Wraps Cognee library with MCP interface.

Exposes same tools as our MCP Memory Server for A/B comparison.
"""

import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from cognee_adapter import CogneeAdapter
from response_normalizer import normalize_search_results

load_dotenv()

# Initialize
mcp = FastMCP("Cognee Memory")
adapter = CogneeAdapter()

# Track stored content for forget functionality
content_registry: dict[str, dict] = {}


@mcp.tool()
async def remember(
    content: str,
    context: str = None,
    metadata: dict = None
) -> dict:
    """
    Store content in Cognee with knowledge extraction.

    Args:
        content: The text content to store
        context: Optional context hint (meeting, email, etc.)
        metadata: Optional metadata dict

    Returns:
        dict with id, status, extraction summary
    """
    start = datetime.now()

    try:
        # Generate content ID
        content_id = adapter.generate_id(content)

        # Build metadata
        full_metadata = {
            "context": context,
            "stored_at": datetime.utcnow().isoformat(),
            **(metadata or {})
        }

        # Add to Cognee
        await adapter.add(content, metadata=full_metadata)

        # Run extraction (cognify)
        extraction_result = await adapter.cognify()

        # Track in registry
        content_registry[content_id] = {
            "content": content[:100],
            "metadata": full_metadata,
            "stored_at": datetime.utcnow().isoformat()
        }

        elapsed = (datetime.now() - start).total_seconds() * 1000

        return {
            "id": content_id,
            "status": "stored",
            "extraction": {
                "nodes_created": extraction_result.get("nodes", 0),
                "edges_created": extraction_result.get("edges", 0)
            },
            "processing_time_ms": round(elapsed, 2)
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@mcp.tool()
async def recall(
    query: str,
    limit: int = 10,
    min_similarity: float = 0.0,
    include_events: bool = True,
    include_entities: bool = True,
    edge_types: list[str] = None,
    include_edges: bool = False
) -> dict:
    """
    Search Cognee for relevant content.

    Args:
        query: Natural language search query
        limit: Maximum results to return
        min_similarity: Minimum similarity threshold (0.0-1.0)
        include_events: Include extracted events
        include_entities: Include extracted entities
        edge_types: Filter by relationship types
        include_edges: Include relationship details

    Returns:
        dict with results, events, entities, edges
    """
    start = datetime.now()

    try:
        # Search Cognee
        raw_results = await adapter.search(
            query=query,
            limit=limit,
            search_type="INSIGHTS"  # Use graph-aware search
        )

        # Get graph data if requested
        graph_data = None
        if include_entities or include_edges:
            graph_data = await adapter.get_graph_context(
                query=query,
                edge_types=edge_types
            )

        # Normalize to our response format
        normalized = normalize_search_results(
            raw_results=raw_results,
            graph_data=graph_data,
            min_similarity=min_similarity,
            include_events=include_events,
            include_entities=include_entities,
            include_edges=include_edges
        )

        elapsed = (datetime.now() - start).total_seconds() * 1000

        return {
            "results": normalized["results"][:limit],
            "events": normalized.get("events", []) if include_events else [],
            "entities": normalized.get("entities", []) if include_entities else [],
            "edges": normalized.get("edges", []) if include_edges else [],
            "stats": {
                "total_results": len(normalized["results"]),
                "query_time_ms": round(elapsed, 2)
            }
        }

    except Exception as e:
        return {
            "results": [],
            "error": str(e)
        }


@mcp.tool()
async def forget(content_id: str) -> dict:
    """
    Remove content from Cognee.

    Note: Cognee doesn't support granular deletion well.
    This is a best-effort implementation.

    Args:
        content_id: ID of content to remove

    Returns:
        dict with status
    """
    try:
        # Check if we know about this content
        if content_id not in content_registry:
            return {
                "status": "not_found",
                "message": f"Content {content_id} not found in registry"
            }

        # Cognee doesn't have granular delete - note this limitation
        # For fair comparison, we just mark as deleted in registry
        del content_registry[content_id]

        return {
            "status": "deleted",
            "id": content_id,
            "note": "Cognee lacks granular deletion - content may still appear in search"
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@mcp.tool()
async def status() -> dict:
    """
    Get Cognee server status and statistics.

    Returns:
        dict with health info and stats
    """
    try:
        # Get Cognee stats
        cognee_status = await adapter.get_status()

        return {
            "status": "healthy",
            "server": "cognee-mcp",
            "version": "10.0.0",
            "cognee_version": cognee_status.get("version", "unknown"),
            "storage": {
                "tracked_content": len(content_registry),
                "cognee_nodes": cognee_status.get("nodes", 0),
                "cognee_edges": cognee_status.get("edges", 0)
            },
            "capabilities": {
                "granular_delete": False,  # Cognee limitation
                "temporal_search": True,
                "graph_traversal": True
            }
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MCP_PORT", "3002"))
    print(f"Starting Cognee MCP server on port {port}")

    # Run with SSE transport
    mcp.run(transport="sse", port=port)
```

### File 3: src/cognee_adapter.py

```python
"""
Adapter layer for Cognee API.

Handles Cognee initialization, configuration, and API calls.
"""

import os
import hashlib
from typing import Optional
import cognee


class CogneeAdapter:
    """Wraps Cognee API with consistent interface."""

    def __init__(self):
        self._initialized = False
        self._dataset = "mcp_memory"

    async def _ensure_initialized(self):
        """Initialize Cognee on first use."""
        if self._initialized:
            return

        # Configure Cognee
        cognee.config.llm_api_key = os.getenv("OPENAI_API_KEY")
        cognee.config.set_llm_provider("openai")

        # Use SQLite for simplicity (can switch to Postgres)
        # cognee.config.set_vector_db_provider("lancedb")

        self._initialized = True

    def generate_id(self, content: str) -> str:
        """Generate deterministic ID for content."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def add(self, content: str, metadata: dict = None) -> dict:
        """Add content to Cognee."""
        await self._ensure_initialized()

        # Cognee.add() accepts text or list of texts
        await cognee.add(
            content,
            dataset_name=self._dataset
        )

        return {"status": "added"}

    async def cognify(self) -> dict:
        """Run Cognee extraction pipeline."""
        await self._ensure_initialized()

        # This builds the knowledge graph
        result = await cognee.cognify()

        # Parse result for stats
        return {
            "nodes": getattr(result, "node_count", 0),
            "edges": getattr(result, "edge_count", 0)
        }

    async def search(
        self,
        query: str,
        limit: int = 10,
        search_type: str = "INSIGHTS"
    ) -> list:
        """Search Cognee knowledge graph."""
        await self._ensure_initialized()

        results = await cognee.search(
            query_type=search_type,
            query_text=query,
            datasets=[self._dataset]
        )

        return results[:limit] if results else []

    async def get_graph_context(
        self,
        query: str,
        edge_types: list[str] = None
    ) -> dict:
        """Get graph nodes and edges related to query."""
        await self._ensure_initialized()

        # Use GRAPH_COMPLETION search type for graph traversal
        results = await cognee.search(
            query_type="GRAPH_COMPLETION",
            query_text=query,
            datasets=[self._dataset]
        )

        entities = []
        edges = []

        for r in results or []:
            # Extract entities from graph results
            if hasattr(r, "source_node"):
                entities.append({
                    "name": r.source_node.get("name", ""),
                    "type": r.source_node.get("type", ""),
                    "id": r.source_node.get("id", "")
                })
            if hasattr(r, "target_node"):
                entities.append({
                    "name": r.target_node.get("name", ""),
                    "type": r.target_node.get("type", ""),
                    "id": r.target_node.get("id", "")
                })
            if hasattr(r, "relationship"):
                edges.append({
                    "source": r.source_node.get("name", ""),
                    "target": r.target_node.get("name", ""),
                    "type": r.relationship
                })

        # Filter by edge types if specified
        if edge_types:
            edges = [e for e in edges if e["type"] in edge_types]

        # Deduplicate entities
        seen = set()
        unique_entities = []
        for e in entities:
            key = (e["name"], e["type"])
            if key not in seen:
                seen.add(key)
                unique_entities.append(e)

        return {
            "entities": unique_entities,
            "edges": edges
        }

    async def get_status(self) -> dict:
        """Get Cognee status."""
        await self._ensure_initialized()

        # Get basic stats
        try:
            # This may vary by Cognee version
            return {
                "version": getattr(cognee, "__version__", "unknown"),
                "nodes": 0,  # Would need graph query
                "edges": 0
            }
        except:
            return {"version": "unknown"}

    async def reset(self) -> dict:
        """Reset Cognee data."""
        await self._ensure_initialized()

        await cognee.prune.prune_data()

        return {"status": "reset"}
```

### File 4: src/response_normalizer.py

```python
"""
Normalize Cognee responses to match our MCP Memory format.

This ensures fair apples-to-apples comparison.
"""

from typing import Any


def normalize_search_results(
    raw_results: list,
    graph_data: dict = None,
    min_similarity: float = 0.0,
    include_events: bool = True,
    include_entities: bool = True,
    include_edges: bool = False
) -> dict:
    """
    Convert Cognee search results to our format.

    Our format:
    {
        "results": [{"id", "content", "similarity", "metadata"}],
        "events": [{"category", "description", "actors", "subjects"}],
        "entities": [{"name", "type", "mentions"}],
        "edges": [{"source", "target", "type", "confidence"}]
    }
    """

    # Normalize main results
    results = []
    for r in raw_results or []:
        # Handle different Cognee result formats
        if isinstance(r, dict):
            result = {
                "id": r.get("id", ""),
                "content": r.get("text", r.get("content", "")),
                "similarity": r.get("score", r.get("relevance", 0.0)),
                "metadata": r.get("metadata", {})
            }
        else:
            # Object format
            result = {
                "id": getattr(r, "id", ""),
                "content": getattr(r, "text", getattr(r, "content", "")),
                "similarity": getattr(r, "score", 0.0),
                "metadata": getattr(r, "metadata", {})
            }

        # Apply similarity filter
        if result["similarity"] >= min_similarity:
            results.append(result)

    # Sort by similarity
    results.sort(key=lambda x: x["similarity"], reverse=True)

    # Extract events from results (Cognee embeds these differently)
    events = []
    if include_events:
        events = extract_events_from_results(raw_results)

    # Get entities from graph data
    entities = []
    if include_entities and graph_data:
        entities = graph_data.get("entities", [])
        # Normalize entity format
        entities = [
            {
                "name": e.get("name", ""),
                "type": e.get("type", "Unknown"),
                "mentions": 1  # Cognee doesn't track mention count
            }
            for e in entities
        ]

    # Get edges from graph data
    edges = []
    if include_edges and graph_data:
        edges = graph_data.get("edges", [])
        # Normalize edge format
        edges = [
            {
                "source": e.get("source", ""),
                "target": e.get("target", ""),
                "type": e.get("type", "RELATED_TO"),
                "confidence": e.get("confidence", 0.8)
            }
            for e in edges
        ]

    return {
        "results": results,
        "events": events,
        "entities": entities,
        "edges": edges
    }


def extract_events_from_results(raw_results: list) -> list:
    """
    Extract event-like structures from Cognee results.

    Cognee doesn't have explicit "events" but we can infer
    from its knowledge graph nodes.
    """
    events = []

    for r in raw_results or []:
        # Check if this looks like an event node
        node_type = None
        if isinstance(r, dict):
            node_type = r.get("type", r.get("node_type", ""))
        else:
            node_type = getattr(r, "type", getattr(r, "node_type", ""))

        # Map Cognee node types to our event categories
        event_category = map_to_event_category(node_type)

        if event_category:
            content = r.get("text", "") if isinstance(r, dict) else getattr(r, "text", "")
            events.append({
                "category": event_category,
                "description": content[:200],
                "actors": [],  # Would need deeper graph traversal
                "subjects": [],
                "confidence": r.get("score", 0.8) if isinstance(r, dict) else getattr(r, "score", 0.8)
            })

    return events


def map_to_event_category(cognee_type: str) -> str:
    """Map Cognee node types to our event categories."""

    mapping = {
        "decision": "Decision",
        "commitment": "Commitment",
        "action": "Execution",
        "meeting": "Collaboration",
        "issue": "QualityRisk",
        "feedback": "Feedback",
        "change": "Change",
        "person": None,  # Not an event
        "organization": None,
        "project": None,
    }

    return mapping.get(cognee_type.lower(), None)
```

### File 5: Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV MCP_PORT=3002
ENV PYTHONUNBUFFERED=1

CMD ["python", "src/server.py"]
```

### File 6: README.md

```markdown
# MCP Cognee Server

Wraps the [Cognee](https://github.com/topoteretes/cognee) library with an MCP interface
identical to our custom MCP Memory Server. Used for A/B comparison benchmarks.

## Quick Start

```bash
# Set API key
export OPENAI_API_KEY=sk-...

# Install dependencies
pip install -r requirements.txt

# Run server
python src/server.py
```

Server runs on port 3002 by default.

## Comparison Benchmark

```bash
# Run against our server
MCP_URL=http://localhost:3001 python ../benchmarks/outcome_eval.py

# Run against Cognee server
MCP_URL=http://localhost:3002 python ../benchmarks/outcome_eval.py
```

## Limitations vs Our Implementation

| Feature | Our Server | Cognee Server |
|---------|------------|---------------|
| Granular delete | ✅ | ❌ |
| Event categories | ✅ 8 types | ⚠️ Inferred |
| Entity resolution | ✅ | ✅ |
| Graph traversal | ✅ SQL | ✅ Native |

## Port Configuration

| Service | Port |
|---------|------|
| MCP Memory (ours) | 3001 |
| MCP Cognee | 3002 |
```

---

## Benchmark Comparison Script

Create a simple comparison script:

### File: benchmarks/compare_implementations.sh

```bash
#!/bin/bash
#
# Compare MCP Memory vs Cognee implementations
#
# Usage: ./compare_implementations.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$SCRIPT_DIR/comparison_results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$RESULTS_DIR"

echo "=============================================="
echo "MCP Memory vs Cognee Comparison"
echo "=============================================="
echo ""

# Check servers are running
echo "Checking servers..."
if ! curl -s http://localhost:3001/health > /dev/null 2>&1; then
    echo "ERROR: MCP Memory server not running on port 3001"
    exit 1
fi

if ! curl -s http://localhost:3002/health > /dev/null 2>&1; then
    echo "ERROR: Cognee server not running on port 3002"
    exit 1
fi

echo "Both servers running."
echo ""

# Run outcome eval against our implementation
echo "=============================================="
echo "Testing OUR IMPLEMENTATION (port 3001)"
echo "=============================================="
MCP_URL=http://localhost:3001 python "$SCRIPT_DIR/outcome_eval.py" 2>&1 | tee "$RESULTS_DIR/ours_$TIMESTAMP.txt"
OUR_RESULT=$?

echo ""
echo "=============================================="
echo "Testing COGNEE (port 3002)"
echo "=============================================="
MCP_URL=http://localhost:3002 python "$SCRIPT_DIR/outcome_eval.py" 2>&1 | tee "$RESULTS_DIR/cognee_$TIMESTAMP.txt"
COGNEE_RESULT=$?

echo ""
echo "=============================================="
echo "COMPARISON SUMMARY"
echo "=============================================="
echo ""
echo "Results saved to:"
echo "  - $RESULTS_DIR/ours_$TIMESTAMP.txt"
echo "  - $RESULTS_DIR/cognee_$TIMESTAMP.txt"
echo ""

# Extract scores (basic parsing)
OUR_SCORE=$(grep -o "Score: [0-9.]*" "$RESULTS_DIR/ours_$TIMESTAMP.txt" | tail -1 | cut -d' ' -f2)
COGNEE_SCORE=$(grep -o "Score: [0-9.]*" "$RESULTS_DIR/cognee_$TIMESTAMP.txt" | tail -1 | cut -d' ' -f2)

echo "Our Implementation: $OUR_SCORE"
echo "Cognee:            $COGNEE_SCORE"
echo ""

# Determine winner
if [ -n "$OUR_SCORE" ] && [ -n "$COGNEE_SCORE" ]; then
    if (( $(echo "$OUR_SCORE > $COGNEE_SCORE" | bc -l) )); then
        echo "WINNER: Our Implementation"
    elif (( $(echo "$COGNEE_SCORE > $OUR_SCORE" | bc -l) )); then
        echo "WINNER: Cognee"
    else
        echo "RESULT: Tie"
    fi
fi
```

### File: benchmarks/compare_full.py

```python
#!/usr/bin/env python3
"""
Full benchmark comparison between MCP Memory and Cognee.

Runs the complete V7 benchmark suite against both implementations.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure we can import benchmark modules
BENCHMARK_ROOT = Path(__file__).parent
sys.path.insert(0, str(BENCHMARK_ROOT / 'tests'))
sys.path.insert(0, str(BENCHMARK_ROOT / 'metrics'))

from benchmark_runner import BenchmarkRunner, BenchmarkConfig


async def run_comparison():
    """Run benchmarks against both implementations."""

    results = {}

    servers = {
        "ours": "http://localhost:3001",
        "cognee": "http://localhost:3002"
    }

    for name, url in servers.items():
        print(f"\n{'='*60}")
        print(f"Running benchmarks against: {name.upper()} ({url})")
        print('='*60)

        os.environ['MCP_URL'] = url

        config = BenchmarkConfig()
        runner = BenchmarkRunner(mcp_url=url)

        try:
            result = await runner.run_all()
            results[name] = result

            print(f"\n{name.upper()} Results:")
            print(f"  Retrieval MRR:   {result.get('retrieval_mrr', 'N/A'):.3f}")
            print(f"  Retrieval NDCG:  {result.get('retrieval_ndcg', 'N/A'):.3f}")
            print(f"  Extraction F1:   {result.get('extraction_f1', 'N/A'):.3f}")
            print(f"  Entity F1:       {result.get('entity_f1', 'N/A'):.3f}")
            print(f"  Graph F1:        {result.get('graph_f1', 'N/A'):.3f}")

        except Exception as e:
            print(f"ERROR running {name}: {e}")
            results[name] = {"error": str(e)}

    # Comparison
    print("\n" + "="*60)
    print("COMPARISON")
    print("="*60)

    metrics = ['retrieval_mrr', 'retrieval_ndcg', 'extraction_f1', 'entity_f1', 'graph_f1']

    print(f"\n{'Metric':<20} {'Ours':>10} {'Cognee':>10} {'Winner':>10}")
    print("-" * 52)

    for metric in metrics:
        ours = results.get('ours', {}).get(metric, 0)
        cognee = results.get('cognee', {}).get(metric, 0)

        if ours > cognee:
            winner = "Ours"
        elif cognee > ours:
            winner = "Cognee"
        else:
            winner = "Tie"

        print(f"{metric:<20} {ours:>10.3f} {cognee:>10.3f} {winner:>10}")

    # Save results
    output_file = BENCHMARK_ROOT / 'comparison_results' / f'comparison_{datetime.now():%Y%m%d_%H%M%S}.json'
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "results": results
        }, f, indent=2)

    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(run_comparison())
```

---

## Execution Plan

### Step 1: Create Cognee Server (30 min)

```bash
# Create directory
mkdir -p .claude-workspace/implementation/cognee-server/src

# Create files (as specified above)
# - requirements.txt
# - src/server.py
# - src/cognee_adapter.py
# - src/response_normalizer.py
# - Dockerfile
# - README.md
```

### Step 2: Test Cognee Server (15 min)

```bash
cd .claude-workspace/implementation/cognee-server

# Install
pip install -r requirements.txt

# Run
export OPENAI_API_KEY=sk-...
python src/server.py

# Test (in another terminal)
curl http://localhost:3002/health
```

### Step 3: Run Comparison (15 min)

```bash
# Ensure both servers running
# Port 3001: Our server
# Port 3002: Cognee server

cd .claude-workspace/benchmarks

# Quick comparison
./compare_implementations.sh

# Full comparison
python compare_full.py
```

### Step 4: Analyze Results (30 min)

Review comparison results and decide:

| If... | Then... |
|-------|---------|
| Cognee wins by >10% | Consider adopting Cognee patterns or migrating |
| We win by >10% | Continue custom development |
| Within 10% | Choose based on maintenance burden |

---

## Success Criteria

1. **Cognee server runs** - Same 4 tools, same port pattern
2. **Benchmarks pass** - Both servers can complete outcome_eval.py
3. **Results comparable** - Same metrics, same format
4. **Clear decision** - Data supports next steps

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Cognee API differs from docs | Read source code, test incrementally |
| Response format mismatch | Normalize in adapter layer |
| Cognee lacks features (delete) | Document limitations, score fairly |
| Different LLM prompts | Note this affects extraction F1 |

---

## Timeline

| Task | Effort |
|------|--------|
| Create Cognee server files | 30 min |
| Test Cognee server | 15 min |
| Run comparison benchmarks | 15 min |
| Analyze results | 30 min |
| **Total** | **~1.5 hours** |

---

## References

- [Cognee GitHub](https://github.com/topoteretes/cognee)
- [Cognee Docs](https://docs.cognee.ai/)
- [Our Benchmarks](../benchmarks/README.md)
- [V7.3 Cognee Analysis](./v7.3-category-expansion-research.md#cognee-analysis-2026-01-10)

---

## Version History

| Date | Change |
|------|--------|
| 2026-01-13 | Detailed implementation spec with code |
| 2026-01-13 | Created initial V10 spec |
