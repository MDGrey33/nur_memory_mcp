#!/usr/bin/env python3
"""
MS MARCO Retrieval Evaluation via MCP Memory Server

Tests the full MCP memory pipeline:
1. Ingest passages via remember()
2. Query via recall()
3. Measure retrieval quality (MRR@10, Precision@10)

Usage:
    python evaluate.py                    # Full evaluation
    python evaluate.py --max-queries 10   # Quick test
    python evaluate.py --skip-ingest      # Skip ingestion (use existing data)
"""

import os
import sys
import json
import time
import argparse
import re
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional

# Load environment from deployment .env files
def load_env_file(path: Path):
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key, value)

DEPLOY_DIR = Path(__file__).parent.parent.parent.parent / "deployment"
load_env_file(DEPLOY_DIR / ".env")
load_env_file(DEPLOY_DIR / ".env.prod")

# Add test adapters for MCP client
LIB_PATH = Path(__file__).parent.parent.parent.parent / "tests" / "v6" / "adapters"
sys.path.insert(0, str(LIB_PATH))

from mcp_client import MCPClient


@dataclass
class Passage:
    """A passage with its ID and text."""
    passage_id: str
    text: str
    art_id: Optional[str] = None  # MCP artifact ID after ingestion


@dataclass
class Query:
    """A query with ground truth."""
    query_id: str
    question: str
    positive_ids: Set[str]
    negative_ids: Set[str]


@dataclass
class EvalResult:
    """Results for a single query."""
    query_id: str
    mrr: float
    precision_at_10: float
    recall_at_10: float
    positive_retrieved: int
    total_positives: int


def load_dataset(path: str = "dev_small.json") -> List[Dict]:
    """Load the evaluation dataset."""
    dataset_path = Path(__file__).parent / path
    with open(dataset_path) as f:
        return json.load(f)


def extract_passages_from_prompt(prompt: str) -> Dict[str, str]:
    """Extract passage_id -> text from a prompt."""
    passages = {}

    # Pattern: [ID#NUM] text until next [ID#NUM] or end
    # Match passage ID and capture text until next bracket or end
    pattern = r'\[(\d+#\d+)\]\s*([^\[]+)'
    matches = re.findall(pattern, prompt, re.DOTALL)

    for passage_id, text in matches:
        text = text.strip()
        # Clean up - remove trailing "Contexts:" if present
        if text:
            passages[passage_id] = text

    return passages


def extract_question(prompt: str) -> str:
    """Extract question from prompt."""
    if 'Question:' in prompt:
        start = prompt.find('Question:') + 10
        end = prompt.find('\n', start)
        if end == -1:
            end = len(prompt)
        return prompt[start:end].strip()
    return prompt[:100]


def generate_art_id(content: str) -> str:
    """Generate the artifact ID that MCP will create for this content."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"art_{content_hash}"


def parse_dataset(data: List[Dict]) -> tuple[Dict[str, Passage], List[Query]]:
    """Parse dataset into passages and queries."""

    all_passages: Dict[str, Passage] = {}
    queries: List[Query] = []

    for row in data:
        query_id = row["query_id"]
        prompt = row["prompt"]
        positive_ids = set(row["positive_ids"])
        negative_ids = set(row["negative_ids"])

        # Extract question
        question = extract_question(prompt)

        # Extract passages
        passages = extract_passages_from_prompt(prompt)
        for pid, text in passages.items():
            if pid not in all_passages:
                all_passages[pid] = Passage(passage_id=pid, text=text)

        queries.append(Query(
            query_id=query_id,
            question=question,
            positive_ids=positive_ids,
            negative_ids=negative_ids
        ))

    return all_passages, queries


def ingest_passages(client: MCPClient, passages: Dict[str, Passage], batch_size: int = 10) -> Dict[str, str]:
    """
    Ingest passages into MCP memory.
    Returns mapping of passage_id -> art_id.
    """

    print(f"\nIngesting {len(passages)} passages...")

    passage_to_art: Dict[str, str] = {}
    passage_list = list(passages.values())

    start_time = time.time()
    errors = 0

    for i, passage in enumerate(passage_list):
        # Create content with passage ID as metadata
        content = f"[{passage.passage_id}] {passage.text}"

        response = client.call_tool("remember", {
            "content": content,
            "context": "fact",
            "title": f"Passage {passage.passage_id}",
            "source_id": passage.passage_id
        })

        if response.success and response.data:
            art_id = response.data.get("id")
            if art_id:
                passage_to_art[passage.passage_id] = art_id
                passage.art_id = art_id
        else:
            errors += 1

        # Progress
        if (i + 1) % 50 == 0 or (i + 1) == len(passage_list):
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            remaining = (len(passage_list) - i - 1) / rate if rate > 0 else 0
            print(f"  {i+1}/{len(passage_list)} passages ({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)")

    elapsed = time.time() - start_time
    print(f"  Done: {len(passage_to_art)} ingested, {errors} errors, {elapsed:.1f}s total")

    return passage_to_art


def run_queries(
    client: MCPClient,
    queries: List[Query],
    passage_to_art: Dict[str, str],
    k: int = 10
) -> List[EvalResult]:
    """Run queries and evaluate results."""

    print(f"\nRunning {len(queries)} queries...")

    # Reverse mapping: art_id -> passage_id
    art_to_passage = {v: k for k, v in passage_to_art.items()}

    results: List[EvalResult] = []
    start_time = time.time()

    for i, query in enumerate(queries):
        # Call recall
        response = client.call_tool("recall", {
            "query": query.question,
            "limit": k
        })

        if not response.success:
            results.append(EvalResult(
                query_id=query.query_id,
                mrr=0.0,
                precision_at_10=0.0,
                recall_at_10=0.0,
                positive_retrieved=0,
                total_positives=len(query.positive_ids)
            ))
            continue

        # Extract retrieved IDs
        retrieved_arts = []
        for item in response.data.get("results", []):
            art_id = item.get("id", "")
            if art_id:
                retrieved_arts.append(art_id)

        # Map back to passage IDs
        retrieved_passages = []
        for art_id in retrieved_arts[:k]:
            # Try direct mapping
            if art_id in art_to_passage:
                retrieved_passages.append(art_to_passage[art_id])
            else:
                # Try to extract passage ID from content
                for item in response.data.get("results", []):
                    if item.get("id") == art_id:
                        content = item.get("content", "")
                        match = re.search(r'\[(\d+#\d+)\]', content)
                        if match:
                            retrieved_passages.append(match.group(1))
                        break

        # Calculate MRR
        mrr = 0.0
        for rank, pid in enumerate(retrieved_passages, 1):
            if pid in query.positive_ids:
                mrr = 1.0 / rank
                break

        # Calculate Precision@k and Recall@k
        positive_retrieved = sum(1 for pid in retrieved_passages if pid in query.positive_ids)
        precision = positive_retrieved / k if k > 0 else 0
        recall = positive_retrieved / len(query.positive_ids) if query.positive_ids else 0

        results.append(EvalResult(
            query_id=query.query_id,
            mrr=mrr,
            precision_at_10=precision,
            recall_at_10=recall,
            positive_retrieved=positive_retrieved,
            total_positives=len(query.positive_ids)
        ))

        # Progress
        if (i + 1) % 20 == 0 or (i + 1) == len(queries):
            elapsed = time.time() - start_time
            print(f"  {i+1}/{len(queries)} queries ({elapsed:.0f}s)")

    return results


def cleanup_passages(client: MCPClient, passage_to_art: Dict[str, str]):
    """Remove ingested passages from MCP memory."""

    print(f"\nCleaning up {len(passage_to_art)} passages...")

    deleted = 0
    for passage_id, art_id in passage_to_art.items():
        response = client.call_tool("forget", {"id": art_id, "confirm": True})
        if response.success:
            deleted += 1

    print(f"  Deleted {deleted} passages")


def main():
    parser = argparse.ArgumentParser(description="MS MARCO MCP Evaluation")
    parser.add_argument("--max-queries", type=int, help="Limit queries to evaluate")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip ingestion (assumes data exists)")
    parser.add_argument("--no-cleanup", action="store_true", help="Don't delete passages after eval")
    parser.add_argument("--k", type=int, default=10, help="Top-k for evaluation (default: 10)")
    args = parser.parse_args()

    print("=" * 60)
    print("MS MARCO MCP Memory Evaluation")
    print("=" * 60)

    # Load and parse dataset
    data = load_dataset()
    print(f"Loaded {len(data)} queries from dev_small.json")

    passages, queries = parse_dataset(data)
    print(f"Parsed {len(passages)} unique passages")

    if args.max_queries:
        queries = queries[:args.max_queries]
        # Filter passages to only those referenced by selected queries
        needed_pids = set()
        for q in queries:
            needed_pids.update(q.positive_ids)
            needed_pids.update(q.negative_ids)
        passages = {k: v for k, v in passages.items() if k in needed_pids}
        print(f"Limited to {len(queries)} queries, {len(passages)} passages")

    # Connect to MCP
    print("\nConnecting to MCP server...")
    client = MCPClient()
    client.initialize()

    # Check server health
    status = client.call_tool("status", {})
    if not status.success or not status.data.get("healthy"):
        print("ERROR: MCP server not healthy")
        client.close()
        return
    print(f"  Server version: {status.data.get('version')}")

    passage_to_art = {}

    try:
        # Ingest passages
        if not args.skip_ingest:
            passage_to_art = ingest_passages(client, passages)

            # Save mapping for potential reuse
            mapping_path = Path(__file__).parent / "passage_mapping.json"
            with open(mapping_path, "w") as f:
                json.dump(passage_to_art, f)
            print(f"  Saved mapping to {mapping_path}")

            # Wait a moment for indexing
            print("  Waiting 2s for indexing...")
            time.sleep(2)
        else:
            # Load existing mapping
            mapping_path = Path(__file__).parent / "passage_mapping.json"
            if mapping_path.exists():
                with open(mapping_path) as f:
                    passage_to_art = json.load(f)
                print(f"Loaded {len(passage_to_art)} passage mappings")
            else:
                print("ERROR: No passage mapping found. Run without --skip-ingest first.")
                return

        # Run queries
        results = run_queries(client, queries, passage_to_art, k=args.k)

        # Aggregate metrics
        avg_mrr = sum(r.mrr for r in results) / len(results)
        avg_precision = sum(r.precision_at_10 for r in results) / len(results)
        avg_recall = sum(r.recall_at_10 for r in results) / len(results)
        hit_rate = sum(1 for r in results if r.mrr > 0) / len(results)

        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)
        print(f"Queries: {len(results)}")
        print(f"Passages: {len(passage_to_art)}")
        print()
        print(f"MRR@{args.k}: {avg_mrr:.4f}")
        print(f"Precision@{args.k}: {avg_precision:.4f}")
        print(f"Recall@{args.k}: {avg_recall:.4f}")
        print(f"Hit Rate@{args.k}: {hit_rate:.2%}")

        # Save results
        output = {
            "queries": len(results),
            "passages": len(passage_to_art),
            "k": args.k,
            "mrr": avg_mrr,
            "precision": avg_precision,
            "recall": avg_recall,
            "hit_rate": hit_rate,
            "per_query": [
                {
                    "query_id": r.query_id,
                    "mrr": r.mrr,
                    "precision": r.precision_at_10,
                    "recall": r.recall_at_10,
                    "positive_retrieved": r.positive_retrieved,
                    "total_positives": r.total_positives
                }
                for r in results
            ]
        }

        output_path = Path(__file__).parent / "results.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to {output_path}")

    finally:
        # Cleanup
        if not args.no_cleanup and passage_to_art and not args.skip_ingest:
            cleanup_passages(client, passage_to_art)

        client.close()


if __name__ == "__main__":
    main()
