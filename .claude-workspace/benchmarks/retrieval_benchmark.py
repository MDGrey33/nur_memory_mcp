#!/usr/bin/env python3
"""
Performance benchmark for retrieval operations.
Measures latency, DB queries, and throughput.
"""

import asyncio
import time
import statistics
import json
import os
import sys
import httpx

MCP_URL = os.getenv("MCP_URL", "http://localhost:3001")

# Test queries of varying complexity
QUERIES = [
    "What did Alice decide?",
    "Who is working on the API?",
    "What are Bob's commitments?",
    "Tell me about the caching layer project",
    "What risks were identified in the meetings?",
]

NUM_ITERATIONS = 10


class MCPClient:
    """Minimal MCP client for benchmarking."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session_id = None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _parse_sse(self, text: str) -> dict:
        for line in text.split('\n'):
            if line.startswith('data: '):
                try:
                    return json.loads(line[6:])
                except:
                    pass
        return {}

    async def initialize(self) -> bool:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.post(
                f'{self.base_url}/mcp/',
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/event-stream'
                },
                json={
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "bench", "version": "1.0"}
                    }
                }
            )
            self.session_id = response.headers.get('mcp-session-id')
            return 'error' not in self._parse_sse(response.text)

    async def recall(self, query: str, expand: bool = True) -> tuple[dict, float]:
        """Call recall and return (result, latency_ms)."""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream'
        }
        if self.session_id:
            headers['mcp-session-id'] = self.session_id

        start = time.perf_counter()

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.post(
                f'{self.base_url}/mcp/',
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "tools/call",
                    "params": {
                        "name": "recall",
                        "arguments": {"query": query, "expand": expand, "limit": 10}
                    }
                }
            )

        latency_ms = (time.perf_counter() - start) * 1000
        result = self._parse_sse(response.text)

        return result, latency_ms


async def run_benchmark(url: str = None):
    """Run the benchmark suite."""
    global MCP_URL
    if url:
        MCP_URL = url

    print("=" * 60)
    print("RETRIEVAL PERFORMANCE BENCHMARK")
    print("=" * 60)
    print()

    mcp = MCPClient(MCP_URL)

    print(f"Connecting to {MCP_URL}...")
    if not await mcp.initialize():
        print("Failed to connect")
        return None
    print("Connected!")
    print()

    # Collect latencies
    all_latencies = []
    query_latencies = {q: [] for q in QUERIES}
    errors = 0

    print(f"Running {NUM_ITERATIONS} iterations per query...")
    print()

    for iteration in range(NUM_ITERATIONS):
        for query in QUERIES:
            try:
                _, latency = await mcp.recall(query, expand=True)
                all_latencies.append(latency)
                query_latencies[query].append(latency)
            except Exception as e:
                print(f"  Error on '{query[:30]}...': {e}")
                errors += 1

        print(f"  Iteration {iteration + 1}/{NUM_ITERATIONS} complete")

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print()

    metrics = {}

    # Overall stats
    if all_latencies:
        all_latencies.sort()
        p50 = all_latencies[len(all_latencies) // 2]
        p95 = all_latencies[int(len(all_latencies) * 0.95)]
        p99 = all_latencies[int(len(all_latencies) * 0.99)]

        print("Overall Latency (ms):")
        print(f"  Min:  {min(all_latencies):.1f}")
        print(f"  p50:  {p50:.1f}")
        print(f"  p95:  {p95:.1f}")
        print(f"  p99:  {p99:.1f}")
        print(f"  Max:  {max(all_latencies):.1f}")
        print(f"  Mean: {statistics.mean(all_latencies):.1f}")
        print()

        metrics = {
            "min_ms": round(min(all_latencies), 1),
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "p99_ms": round(p99, 1),
            "max_ms": round(max(all_latencies), 1),
            "mean_ms": round(statistics.mean(all_latencies), 1),
            "total_queries": len(all_latencies),
            "errors": errors
        }
    else:
        print("No successful queries!")
        metrics = {
            "min_ms": 0,
            "p50_ms": 0,
            "p95_ms": 0,
            "p99_ms": 0,
            "max_ms": 0,
            "mean_ms": 0,
            "total_queries": 0,
            "errors": errors
        }

    # Per-query stats
    print("Per-Query Latency (ms):")
    for query, latencies in query_latencies.items():
        if latencies:
            avg = statistics.mean(latencies)
            print(f"  {query[:40]:<40} avg: {avg:.1f}")

    print()
    print("=" * 60)

    # Output for easy parsing
    print()
    print("METRICS_JSON:")
    print(json.dumps(metrics, indent=2))

    return metrics


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Retrieval Performance Benchmark")
    parser.add_argument("--url", help="MCP server URL (default: http://localhost:3001)")
    parser.add_argument("--iterations", type=int, default=10, help="Number of iterations")
    args = parser.parse_args()

    global NUM_ITERATIONS
    if args.iterations:
        NUM_ITERATIONS = args.iterations

    try:
        metrics = asyncio.run(run_benchmark(url=args.url))
        sys.exit(0 if metrics and metrics.get("total_queries", 0) > 0 else 1)
    except KeyboardInterrupt:
        print("\nAborted")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
