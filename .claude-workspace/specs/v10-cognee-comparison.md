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

### Core API (Verified from source/docs)

```python
import cognee
from cognee.api.v1.search import SearchType
import os

# Configure via environment variables
os.environ["LLM_API_KEY"] = "sk-..."  # OpenAI key

# Add content (like our remember)
await cognee.add("text content", dataset_name="default")
await cognee.add(["list", "of", "texts"], dataset_name="default")

# Process/extract (builds knowledge graph with triplets)
await cognee.cognify()

# Optionally apply memory algorithms
await cognee.memify()

# Search (like our recall)
results = await cognee.search(
    query_type=SearchType.CHUNKS,  # or GRAPH_COMPLETION, SUMMARIES, etc.
    query_text="search query",
    datasets=["default"],
    top_k=10
)

# Reset (like our forget - but global only)
await cognee.prune.prune_data()
await cognee.prune.prune_system(metadata=True)
```

### Cognee Search Types (from SearchType enum)

| Type | Description | Maps To |
|------|-------------|---------|
| `GRAPH_COMPLETION` | LLM Q&A using full graph context (default) | Our default recall with graph expansion |
| `RAG_COMPLETION` | Traditional RAG | Our basic semantic search |
| `CHUNKS` | Raw text chunk retrieval | Direct document retrieval |
| `SUMMARIES` | Pre-computed summaries | N/A |
| `CODE` | Syntax-aware code search | N/A |
| `CYPHER` | Direct graph queries | N/A |
| `CHUNKS_LEXICAL` | Token-based exact matching | N/A |

### Cognee Response Formats (by type)

**CHUNKS results:**
```python
# Each result has:
{
    "document_title": "source_doc.txt",  # Source document name
    "metadata": {"page": 1, "section": "intro"},  # Optional metadata
    "text": "The actual paragraph content..."  # Chunk text
}
```

**SUMMARIES results:**
```python
{
    "title": "Document Title",
    "text": "Pre-generated summary of the document..."
}
```

**GRAPH_COMPLETION results:**
```python
# Returns LLM-generated answer strings based on graph context
"Cognee is a library that turns documents into AI memory..."
```

### Key Differences from Our System

| Aspect | Our System | Cognee |
|--------|-----------|--------|
| **Data Model** | Semantic events (category, actors, subject) | Triplets (source-relation-object) |
| **IDs** | `art_xxx` deterministic hash | Document titles |
| **Deletion** | Granular per-document | Global prune only |
| **Search Result** | JSON with structured fields | Varies by SearchType |
| **Entities** | Extracted from event actors/subjects | Graph nodes |

### Comparison Implications

**Comparable metrics:**
- **Retrieval MRR/NDCG** - Both systems can rank documents by relevance

**Not directly comparable:**
- **Extraction F1** - We extract events, Cognee extracts triplets (different structure)
- **Entity F1** - Different extraction approaches
- **Graph F1** - Different graph models

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
    query: str = None,
    id: str = None,
    limit: int = 10,
    include_events: bool = True,
    include_entities: bool = True,
    expand: bool = True
) -> dict:
    """
    Search Cognee for relevant content.

    Args:
        query: Natural language search query
        id: Direct lookup by ID (not well supported by Cognee)
        limit: Maximum results to return
        include_events: Include extracted events (mapped from triplets)
        include_entities: Include extracted entities
        expand: Use graph expansion (GRAPH_COMPLETION vs CHUNKS)

    Returns:
        dict with results, events (empty - see note), entities
    """
    start = datetime.now()

    try:
        # Search Cognee using CHUNKS for retrieval benchmarks
        # CHUNKS returns document chunks with titles (comparable to our retrieval)
        chunk_results = await adapter.search_chunks(query or "", limit=limit)

        # Build results in our format
        results = []
        for chunk in chunk_results:
            results.append({
                "id": chunk["id"],
                "content": chunk["text"],
                "metadata": chunk["metadata"],
                # Note: Cognee doesn't return similarity scores in CHUNKS mode
                "similarity": 0.0
            })

        elapsed = (datetime.now() - start).total_seconds() * 1000

        # NOTE: Cognee doesn't extract "events" like we do
        # It extracts triplets (subject-relation-object) which are different
        # We return empty events for benchmark compatibility
        return {
            "results": results[:limit],
            "events": [],  # Cognee uses triplets, not events
            "entities": [],  # Would need separate graph query
            "related": [],
            "stats": {
                "total_results": len(results),
                "query_time_ms": round(elapsed, 2),
                "note": "Cognee extracts triplets not events - event metrics not comparable"
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
Verified against Cognee 0.1.x API (Jan 2026).
"""

import os
import hashlib
from typing import Optional, List
import cognee
from cognee.api.v1.search import SearchType


class CogneeAdapter:
    """Wraps Cognee API with consistent interface."""

    def __init__(self):
        self._initialized = False
        self._dataset = "mcp_memory"
        # Track content -> title mapping for ID translation
        self._content_registry: dict[str, dict] = {}

    async def _ensure_initialized(self):
        """Initialize Cognee on first use."""
        if self._initialized:
            return

        # Cognee uses environment variables for config
        # LLM_API_KEY is used by Cognee for OpenAI
        if not os.getenv("LLM_API_KEY"):
            os.environ["LLM_API_KEY"] = os.getenv("OPENAI_API_KEY", "")

        self._initialized = True

    def generate_id(self, content: str) -> str:
        """Generate deterministic ID for content (matches our art_xxx format)."""
        hash_val = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"art_{hash_val}"

    async def add(self, content: str, title: str = None, metadata: dict = None) -> dict:
        """Add content to Cognee."""
        await self._ensure_initialized()

        # Generate title for tracking (Cognee uses document titles as IDs)
        if not title:
            title = f"doc_{self.generate_id(content)}"

        # Cognee.add() accepts text or list of texts
        await cognee.add(
            content,
            dataset_name=self._dataset
        )

        # Track for ID translation
        content_id = self.generate_id(content)
        self._content_registry[content_id] = {
            "title": title,
            "content_preview": content[:100]
        }

        return {"status": "added", "title": title}

    async def cognify(self) -> dict:
        """Run Cognee extraction pipeline (builds knowledge graph)."""
        await self._ensure_initialized()

        # This builds the knowledge graph with triplets
        await cognee.cognify()

        # Cognify doesn't return stats directly
        return {
            "status": "processed",
            "nodes": 0,  # Stats not directly available
            "edges": 0
        }

    async def search(
        self,
        query: str,
        limit: int = 10,
        search_type: SearchType = SearchType.CHUNKS
    ) -> list:
        """Search Cognee - returns list of chunk objects."""
        await self._ensure_initialized()

        results = await cognee.search(
            query_type=search_type,
            query_text=query,
            datasets=[self._dataset],
            top_k=limit
        )

        return list(results) if results else []

    async def search_chunks(self, query: str, limit: int = 10) -> List[dict]:
        """
        Search for document chunks - best for retrieval benchmarks.

        Returns: List of dicts with {document_title, text, metadata}
        """
        results = await self.search(query, limit, SearchType.CHUNKS)

        normalized = []
        for r in results:
            # CHUNKS results have document_title, text, metadata
            if hasattr(r, "document_title"):
                normalized.append({
                    "id": self._title_to_id(r.document_title),
                    "document_title": r.document_title,
                    "text": getattr(r, "text", ""),
                    "metadata": getattr(r, "metadata", {})
                })
            elif isinstance(r, dict):
                title = r.get("document_title", "unknown")
                normalized.append({
                    "id": self._title_to_id(title),
                    "document_title": title,
                    "text": r.get("text", ""),
                    "metadata": r.get("metadata", {})
                })

        return normalized

    async def search_graph(self, query: str) -> str:
        """
        Search using graph completion - returns LLM-generated answer.

        GRAPH_COMPLETION returns text strings, not structured data.
        """
        results = await self.search(query, limit=1, search_type=SearchType.GRAPH_COMPLETION)

        if results:
            # GRAPH_COMPLETION returns answer strings
            return str(results[0]) if results else ""
        return ""

    def _title_to_id(self, title: str) -> str:
        """Convert document title to our art_xxx ID format."""
        # Try to find in registry first
        for content_id, data in self._content_registry.items():
            if data.get("title") == title:
                return content_id

        # Generate from title if not found
        hash_val = hashlib.sha256(title.encode()).hexdigest()[:12]
        return f"art_{hash_val}"

    async def get_status(self) -> dict:
        """Get Cognee status."""
        await self._ensure_initialized()

        return {
            "version": getattr(cognee, "__version__", "unknown"),
            "dataset": self._dataset,
            "tracked_documents": len(self._content_registry)
        }

    async def reset(self) -> dict:
        """Reset Cognee data (global - affects all data)."""
        await self._ensure_initialized()

        await cognee.prune.prune_data()
        await cognee.prune.prune_system(metadata=True)
        self._content_registry.clear()

        return {"status": "reset"}
```

### File 4: src/config.py

```python
"""
Configuration for Cognee MCP server.
"""

import os

# Server config
MCP_PORT = int(os.getenv("MCP_PORT", "3002"))

# Cognee uses LLM_API_KEY env var
# Set it from OPENAI_API_KEY if not present
if not os.getenv("LLM_API_KEY"):
    os.environ["LLM_API_KEY"] = os.getenv("OPENAI_API_KEY", "")
```

---

## Benchmark Compatibility Analysis

### What's Comparable

| Benchmark | Comparable? | Rationale |
|-----------|-------------|-----------|
| **Retrieval MRR** | ✅ Yes | Both return ranked documents |
| **Retrieval NDCG** | ✅ Yes | Both return ranked documents |
| **Retrieval P@K/R@K** | ✅ Yes | Both return ranked documents |
| **Extraction F1** | ❌ No | We extract events, Cognee extracts triplets |
| **Entity F1** | ⚠️ Partial | Different extraction methods |
| **Graph F1** | ⚠️ Partial | Different graph models |

### Why Extraction Isn't Comparable

**Our system extracts events:**
```json
{
  "category": "Decision",
  "narrative": "Bob approved the Q1 budget",
  "actors": [{"ref": "Bob Smith", "role": "decider"}],
  "subject": {"type": "project", "ref": "Q1 Budget"}
}
```

**Cognee extracts triplets:**
```
(Bob Smith) --[APPROVED]--> (Q1 Budget)
```

These are fundamentally different data structures optimized for different use cases.

### Recommended Comparison Strategy

1. **Primary comparison: Retrieval metrics only**
   - MRR, NDCG, P@K, R@K
   - Both systems can search and rank documents

2. **Secondary: Manual inspection**
   - Sample queries to compare answer quality
   - Graph traversal capabilities

3. **Skip: Extraction/Entity/Graph F1**
   - Different structures make numerical comparison meaningless

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

### File: benchmarks/compare_retrieval.py

```python
#!/usr/bin/env python3
"""
Retrieval-only benchmark comparison between MCP Memory and Cognee.

Only compares retrieval metrics (MRR, NDCG) which are directly comparable.
Extraction/Entity/Graph metrics are NOT comparable due to different data models.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BENCHMARK_ROOT = Path(__file__).parent
sys.path.insert(0, str(BENCHMARK_ROOT / 'tests'))
sys.path.insert(0, str(BENCHMARK_ROOT / 'metrics'))

from benchmark_runner import BenchmarkRunner, BenchmarkConfig


async def run_retrieval_comparison():
    """Run retrieval benchmarks only against both implementations."""

    results = {}

    servers = {
        "ours": "http://localhost:3001",
        "cognee": "http://localhost:3002"
    }

    for name, url in servers.items():
        print(f"\n{'='*60}")
        print(f"Running RETRIEVAL benchmarks against: {name.upper()} ({url})")
        print('='*60)

        os.environ['MCP_URL'] = url

        config = BenchmarkConfig()
        runner = BenchmarkRunner(config)

        try:
            # Only run retrieval benchmarks
            queries = runner.load_queries()
            retrieval_results = await runner.run_retrieval_benchmarks(queries)

            agg = retrieval_results.get('aggregated', {})
            results[name] = {
                "mrr": agg.get('mrr', 0),
                "ndcg": agg.get('ndcg', 0),
                "ndcg_at_5": agg.get('ndcg_at_5', 0),
                "per_query": retrieval_results.get('per_query', [])
            }

            print(f"\n{name.upper()} Retrieval Results:")
            print(f"  MRR:     {agg.get('mrr', 0):.3f}")
            print(f"  NDCG:    {agg.get('ndcg', 0):.3f}")
            print(f"  NDCG@5:  {agg.get('ndcg_at_5', 0):.3f}")

        except Exception as e:
            print(f"ERROR running {name}: {e}")
            import traceback
            traceback.print_exc()
            results[name] = {"error": str(e)}

    # Comparison
    print("\n" + "="*60)
    print("RETRIEVAL COMPARISON (Comparable Metrics Only)")
    print("="*60)

    print(f"\n{'Metric':<15} {'Ours':>10} {'Cognee':>10} {'Delta':>10} {'Winner':>10}")
    print("-" * 57)

    for metric in ['mrr', 'ndcg', 'ndcg_at_5']:
        ours = results.get('ours', {}).get(metric, 0)
        cognee = results.get('cognee', {}).get(metric, 0)
        delta = ours - cognee

        if delta > 0.01:
            winner = "Ours"
        elif delta < -0.01:
            winner = "Cognee"
        else:
            winner = "Tie"

        print(f"{metric:<15} {ours:>10.3f} {cognee:>10.3f} {delta:>+10.3f} {winner:>10}")

    # Save results
    output_file = BENCHMARK_ROOT / 'comparison_results' / f'retrieval_comparison_{datetime.now():%Y%m%d_%H%M%S}.json'
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "comparison_type": "retrieval_only",
            "note": "Only retrieval metrics are comparable. Extraction/Entity/Graph use different data models.",
            "results": results
        }, f, indent=2)

    print(f"\nResults saved to: {output_file}")

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print("\nNote: Only retrieval metrics (MRR, NDCG) are directly comparable.")
    print("Extraction F1, Entity F1, Graph F1 are NOT comparable because:")
    print("  - Our system extracts semantic events with actors/subjects")
    print("  - Cognee extracts triplets (subject-relation-object)")
    print("  - These are fundamentally different data structures")


if __name__ == "__main__":
    asyncio.run(run_retrieval_comparison())
```

---

## Execution Plan

### Step 1: Create Cognee Server (45 min)

```bash
# Create directory
mkdir -p .claude-workspace/implementation/cognee-server/src

# Create files (as specified above)
# - requirements.txt
# - src/server.py
# - src/cognee_adapter.py
# - src/config.py
# - Dockerfile
# - README.md
```

### Step 2: Test Cognee Server Standalone (15 min)

```bash
cd .claude-workspace/implementation/cognee-server

# Install
pip install -r requirements.txt

# Run (ensure OPENAI_API_KEY is set)
export OPENAI_API_KEY=sk-...
python src/server.py

# Test health (in another terminal)
curl http://localhost:3002/health

# Test remember tool via MCP
curl -X POST http://localhost:3002/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"remember","arguments":{"content":"Test content"}}}'
```

### Step 3: Load Corpus Into Both Systems (15 min)

```bash
# Reset both systems
curl http://localhost:3001/mcp/ -X POST -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"forget","arguments":{"id":"*","confirm":true}}}'

# Load corpus into our server
MCP_URL=http://localhost:3001 python benchmarks/tests/benchmark_runner.py --record

# Reset Cognee
curl http://localhost:3002/mcp/ -X POST -d '...' # reset call

# Load corpus into Cognee server
MCP_URL=http://localhost:3002 python benchmarks/tests/benchmark_runner.py --record
```

### Step 4: Run Retrieval Comparison (15 min)

```bash
cd .claude-workspace/benchmarks

# Run retrieval-only comparison (comparable metrics)
python compare_retrieval.py
```

### Step 5: Analyze Results (30 min)

Review comparison results:

| Outcome | Action |
|---------|--------|
| Cognee MRR/NDCG wins by >10% | Investigate Cognee's retrieval approach for adoption |
| Our MRR/NDCG wins by >10% | Continue custom development |
| Within 10% | Choose based on maintenance burden and feature needs |

**Important**: Extraction/Entity/Graph F1 scores are NOT comparable - different data models.

---

## Success Criteria

1. **Cognee server runs** - Responds to MCP protocol on port 3002
2. **Can store corpus** - Both servers ingest same benchmark documents
3. **Retrieval works** - Both servers return ranked results for queries
4. **Fair comparison** - Same corpus, same queries, retrieval metrics only
5. **Clear recommendation** - Data supports build-vs-adopt decision

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Cognee API differs from docs | ✅ Verified against source - using SearchType enum correctly |
| Response format mismatch | Use CHUNKS search type for retrieval (document_title/text format) |
| Cognee lacks granular delete | Document limitation, doesn't affect retrieval benchmarks |
| Different data models | Only compare retrieval metrics (MRR/NDCG) - extraction not comparable |
| ID format mismatch | Track content → title mapping in adapter for ID translation |

---

## Timeline

| Task | Effort |
|------|--------|
| Create Cognee server files | 45 min |
| Test Cognee server standalone | 15 min |
| Load corpus into both systems | 15 min |
| Run retrieval comparison | 15 min |
| Analyze results | 30 min |
| **Total** | **~2 hours** |

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
| 2026-01-14 | **Updated with verified Cognee API**: SearchType enum, CHUNKS response format, benchmark compatibility analysis |
| 2026-01-13 | Detailed implementation spec with code |
| 2026-01-13 | Created initial V10 spec |
