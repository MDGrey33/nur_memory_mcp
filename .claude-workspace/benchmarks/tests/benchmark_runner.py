"""
V7 Quality Benchmark Runner

Runs against live MCP services for full-fidelity evaluation.

Benchmarks three dimensions:
1. Event Extraction: Precision/Recall/F1 of event extraction from documents
2. Entity Extraction: Precision/Recall/F1 of entity extraction from documents
3. Retrieval: MRR/NDCG of document retrieval for queries
4. Graph Expansion: Connection precision/recall from entity graph traversal

Usage:
    python benchmark_runner.py              # Run benchmarks (live mode)
    python benchmark_runner.py --record     # Record ID mappings for retrieval evaluation

================================================================================
WARNING: DO NOT IMPLEMENT REPLAY/FIXTURE MODE
================================================================================
A replay mode using cached fixtures was previously implemented and removed.
It caused misleading benchmark comparisons because:
1. Cached extraction results became stale as the system evolved
2. Live vs replay comparisons showed false regressions
3. It provided no meaningful value for quality measurement

If you need faster benchmarks for CI, consider:
- Running a subset of queries (--max-queries)
- Using a smaller corpus
- Caching embeddings (not extraction results)

DO NOT re-implement fixture-based replay without explicit user instruction.
================================================================================
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

# Add parent directories to path for imports
BENCHMARK_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BENCHMARK_ROOT / 'metrics'))

from extraction_metrics import (
    evaluate_extraction,
    evaluate_entity_extraction,
    aggregate_results as agg_extraction,
    ExtractionResult
)
from retrieval_metrics import (
    evaluate_retrieval,
    aggregate_retrieval_results,
    evaluate_graph_expansion,
    RetrievalResult
)


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark execution."""
    record: bool = False
    corpus_path: Path = field(default_factory=lambda: BENCHMARK_ROOT / 'corpus')
    ground_truth_path: Path = field(default_factory=lambda: BENCHMARK_ROOT / 'ground_truth')
    queries_path: Path = field(default_factory=lambda: BENCHMARK_ROOT / 'queries' / 'queries.json')
    fixtures_path: Path = field(default_factory=lambda: BENCHMARK_ROOT / 'fixtures')
    reports_path: Path = field(default_factory=lambda: BENCHMARK_ROOT / 'reports')

    # Thresholds for pass/fail
    min_extraction_f1: float = 0.70
    min_entity_f1: float = 0.70
    min_retrieval_mrr: float = 0.60
    min_retrieval_ndcg: float = 0.65
    min_graph_f1: float = 0.60


class IDMappingStore:
    """Manages artifact_id -> corpus_path mappings for retrieval evaluation."""

    def __init__(self, fixtures_path: Path):
        self.fixtures_path = fixtures_path
        self.id_mapping_file = fixtures_path / 'id_mapping.json'
        fixtures_path.mkdir(parents=True, exist_ok=True)
        self.id_mapping = self._load_id_mapping()

    def _load_id_mapping(self) -> dict:
        """Load artifact_id -> corpus_path mapping."""
        if self.id_mapping_file.exists():
            with open(self.id_mapping_file) as f:
                return json.load(f)
        return {}

    def save_id_mapping(self, artifact_id: str, corpus_path: str):
        """Save an artifact_id -> corpus_path mapping."""
        self.id_mapping[artifact_id] = corpus_path
        with open(self.id_mapping_file, 'w') as f:
            json.dump(self.id_mapping, f, indent=2)

    def translate_id(self, artifact_id: str) -> str:
        """Translate artifact_id to corpus_path, or return original if not found."""
        return self.id_mapping.get(artifact_id, artifact_id)


class LiveMCPClient:
    """Live MCP client - calls actual MCP services via Streamable HTTP (SSE)."""

    # Map corpus paths to valid V6 contexts
    CONTEXT_MAP = {
        'meetings': 'meeting',
        'emails': 'email',
        'decisions': 'decision',
        'conversations': 'chat',
    }

    def __init__(self, mcp_url: str = None):
        # Use MCP_URL env var, or default to port 3001
        if mcp_url is None:
            mcp_url = os.environ.get('MCP_URL', 'http://localhost:3001')
        self.mcp_url = mcp_url.rstrip('/')
        self.session_id = None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _doc_id_to_context(self, doc_id: str) -> str:
        """Convert doc_id path to valid V6 context."""
        # doc_id format: "meetings/meeting_001.txt"
        parts = doc_id.split('/')
        if parts:
            corpus_type = parts[0]
            return self.CONTEXT_MAP.get(corpus_type, 'document')
        return 'document'

    def _parse_sse_response(self, text: str) -> dict:
        """Parse SSE response to extract JSON-RPC result."""
        # SSE format: "event: message\ndata: {...}\n\n"
        for line in text.split('\n'):
            if line.startswith('data: '):
                try:
                    return json.loads(line[6:])
                except json.JSONDecodeError:
                    pass
        return {}

    async def _initialize_session(self):
        """Initialize MCP session if not already done."""
        if self.session_id:
            return

        import httpx

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                f"{self.mcp_url}/mcp/",
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
                        "clientInfo": {"name": "benchmark-runner", "version": "1.0.0"}
                    }
                },
                timeout=30.0
            )

            self.session_id = response.headers.get('mcp-session-id')
            result = self._parse_sse_response(response.text)

            if 'error' in result:
                raise ValueError(f"MCP initialization failed: {result['error']}")

    async def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool via SSE streaming."""
        import httpx

        await self._initialize_session()

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream'
        }
        if self.session_id:
            headers['mcp-session-id'] = self.session_id

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                f"{self.mcp_url}/mcp/",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    }
                },
                timeout=120.0  # Longer timeout for extraction
            )

            return self._parse_sse_response(response.text)

    async def extract_events(self, content: str, doc_id: str) -> tuple[list[dict], str]:
        """
        Store content via remember() and wait for event extraction.

        Note: V6 remember() queues events asynchronously. For benchmarking,
        we need to wait for extraction to complete and then fetch events.

        Returns:
            Tuple of (events, artifact_id) for ID mapping
        """
        import re

        # Map doc_id to valid V6 context
        context = self._doc_id_to_context(doc_id)

        # Store the content
        result = await self._call_tool("remember", {
            "content": content,
            "context": context
        })

        if 'error' in result:
            raise ValueError(f"remember() failed: {result['error']}")

        # Get the artifact ID from response
        tool_result = result.get('result', {})
        if isinstance(tool_result, dict):
            content_list = tool_result.get('content', [])
            if content_list and isinstance(content_list[0], dict):
                text = content_list[0].get('text', '')
                # Parse artifact ID from response text
                match = re.search(r'(art_[a-zA-Z0-9]+)', text)
                if match:
                    artifact_id = match.group(1)
                    # Wait for extraction and fetch events
                    events = await self._wait_and_fetch_events(artifact_id)
                    return events, artifact_id

        return [], ""

    async def _wait_and_fetch_events(self, artifact_id: str, max_wait: int = 90) -> list[dict]:
        """Wait for event extraction to complete and return events.

        V9 Fix: Increased max_wait from 30 to 90 iterations (180 seconds).
        Multi-chunk documents with LLM extraction can take 60-120+ seconds.
        Also checks job status via status() tool for better feedback.
        """
        events = []

        for i in range(max_wait):
            await asyncio.sleep(2)  # Poll every 2 seconds

            # V9: Check job status first for better feedback
            if i % 5 == 0:  # Every 10 seconds, check status
                try:
                    status_result = await self._call_tool("status", {"artifact_id": artifact_id})
                    status_data = self._parse_tool_result(status_result)
                    job_status = status_data.get("job_status", {})

                    if job_status:
                        job_state = job_status.get("status", "UNKNOWN")
                        if job_state == "FAILED":
                            error = job_status.get("error_message", "Unknown error")
                            print(f"      [{artifact_id}] extraction FAILED: {error}", flush=True)
                            return []
                        elif job_state == "COMPLETED":
                            print(f"      [{artifact_id}] job completed, fetching events...", flush=True)
                            # Job done, fetch events and return
                            events = await self._fetch_events_from_recall(artifact_id)
                            if events:
                                print(f"      [{artifact_id}] found {len(events)} events!", flush=True)
                            return events
                        else:
                            print(f"      [{artifact_id}] waiting... {i*2}s (job_status={job_state})", flush=True)
                    else:
                        print(f"      [{artifact_id}] waiting... {i*2}s", flush=True)
                except Exception as e:
                    print(f"      [{artifact_id}] waiting... {i*2}s (status check failed: {e})", flush=True)

            # Also try to fetch events directly (they may appear before job marked complete)
            events = await self._fetch_events_from_recall(artifact_id)
            if events:
                print(f"      [{artifact_id}] found {len(events)} events!", flush=True)
                # Wait a bit more for any stragglers, then re-fetch
                await asyncio.sleep(3)
                events = await self._fetch_events_from_recall(artifact_id)
                return events

        # Timeout - return whatever we have
        print(f"      [{artifact_id}] TIMEOUT after {max_wait*2}s", flush=True)
        return events

    async def _fetch_events_from_recall(self, artifact_id: str) -> list[dict]:
        """Fetch events for an artifact via recall() tool."""
        result = await self._call_tool("recall", {
            "id": artifact_id,
            "include_events": True
        })

        data = self._parse_tool_result(result)
        results = data.get('results', [])
        if results and isinstance(results[0], dict):
            return results[0].get('events', [])
        return []

    def _parse_tool_result(self, result: dict) -> dict:
        """Parse JSON from tool result content."""
        tool_result = result.get('result', {})
        if isinstance(tool_result, dict):
            content_list = tool_result.get('content', [])
            if content_list:
                text = content_list[0].get('text', '')
                try:
                    if text.startswith('{'):
                        return json.loads(text)
                except json.JSONDecodeError:
                    pass
        return {}

    async def extract_entities(self, content: str, doc_id: str) -> list[dict]:
        """
        Extract entities from content.

        V7.3: Uses actual actors/subjects from extracted events instead of regex.
        Entity data is in event['actors'] and event['subject'] fields.
        """
        import re

        # Map doc_id to valid V6 context
        context = self._doc_id_to_context(doc_id)

        # First ensure content is stored
        result = await self._call_tool("remember", {
            "content": content,
            "context": context
        })

        if 'error' in result:
            raise ValueError(f"remember() failed: {result['error']}")

        # Get the artifact ID
        tool_result = result.get('result', {})
        artifact_id = None
        if isinstance(tool_result, dict):
            content_list = tool_result.get('content', [])
            if content_list and isinstance(content_list[0], dict):
                text = content_list[0].get('text', '')
                match = re.search(r'(art_[a-zA-Z0-9]+)', text)
                if match:
                    artifact_id = match.group(1)

        if not artifact_id:
            return []

        # Wait for extraction to complete (V9: use same timeout as event extraction)
        events = await self._wait_and_fetch_events(artifact_id, max_wait=45)

        # V7.3: Extract entities from actual actors/subjects fields (not regex)
        entities = []
        seen_names = set()

        for event in events:
            # Extract from actors field: [{"ref": "name", "role": "..."}]
            actors = event.get('actors', [])
            if isinstance(actors, str):
                try:
                    actors = json.loads(actors)
                except json.JSONDecodeError:
                    actors = []
            if isinstance(actors, list):
                for actor in actors:
                    if isinstance(actor, dict):
                        name = actor.get('ref', '') or actor.get('name', '')
                        if name and name not in seen_names:
                            seen_names.add(name)
                            entities.append({
                                'name': name,
                                'type': 'PERSON'  # Actors are typically people
                            })

            # Extract from subject field: {"type": "...", "ref": "name"}
            subject = event.get('subject', {})
            if isinstance(subject, str):
                try:
                    subject = json.loads(subject)
                except json.JSONDecodeError:
                    subject = {}
            if isinstance(subject, dict):
                name = subject.get('ref', '') or subject.get('name', '')
                subj_type = subject.get('type', 'other').upper()
                # Map subject types to entity types
                type_mapping = {
                    'PERSON': 'PERSON',
                    'PROJECT': 'PROJECT',
                    'ORGANIZATION': 'ORGANIZATION',
                    'OBJECT': 'OBJECT',
                    'OTHER': 'OTHER'
                }
                entity_type = type_mapping.get(subj_type, 'OTHER')
                if name and name not in seen_names:
                    seen_names.add(name)
                    entities.append({
                        'name': name,
                        'type': entity_type
                    })

        return entities

    async def recall(self, query: str, query_id: str) -> list[str]:
        """Call recall() and return document IDs."""
        result = await self._call_tool("recall", {
            "query": query,
            "limit": 10
        })

        doc_ids = []
        tool_result = result.get('result', {})
        if isinstance(tool_result, dict):
            content_list = tool_result.get('content', [])
            if content_list:
                text = content_list[0].get('text', '')
                try:
                    data = json.loads(text) if text.startswith('{') else {}
                    # V6 format: results is the main array
                    results = data.get('results', [])
                    for item in results:
                        doc_id = item.get('id', '') or item.get('artifact_uid', '')
                        if doc_id:
                            doc_ids.append(doc_id)
                except json.JSONDecodeError:
                    pass

        return doc_ids

    async def graph_expand(self, seed_entity: str, query_id: str) -> tuple[list[str], list[str]]:
        """
        Perform graph expansion from a seed entity.

        Uses recall() with expand=true to discover connected entities.
        """
        result = await self._call_tool("recall", {
            "query": seed_entity,
            "expand": True,
            "graph_budget": 20,
            "limit": 10,
            "include_entities": True
        })

        connections = []
        docs = []
        tool_result = result.get('result', {})
        if isinstance(tool_result, dict):
            content_list = tool_result.get('content', [])
            if content_list:
                text = content_list[0].get('text', '')
                try:
                    data = json.loads(text) if text.startswith('{') else {}
                    # V6 format: entities and related arrays
                    entities = data.get('entities', [])
                    for entity in entities:
                        name = entity.get('name', '') or entity.get('id', '')
                        if name:
                            connections.append(name)

                    # related contains connected documents
                    related = data.get('related', [])
                    for item in related:
                        doc_id = item.get('id', '') or item.get('artifact_uid', '')
                        if doc_id and doc_id not in docs:
                            docs.append(doc_id)

                    # Also include direct results
                    results = data.get('results', [])
                    for item in results:
                        doc_id = item.get('id', '') or item.get('artifact_uid', '')
                        if doc_id and doc_id not in docs:
                            docs.append(doc_id)
                except json.JSONDecodeError:
                    pass

        return connections, docs


class BenchmarkRunner:
    """Main benchmark execution engine."""

    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.id_store = IDMappingStore(config.fixtures_path)
        self.client = LiveMCPClient()
        self.errors = []

    def load_ground_truth(self) -> tuple[dict, dict, dict]:
        """Load ground truth events, entities, and graph connections."""
        events_file = self.config.ground_truth_path / 'events.json'
        entities_file = self.config.ground_truth_path / 'entities.json'
        graph_file = self.config.ground_truth_path / 'graph_connections.json'

        with open(events_file) as f:
            events = json.load(f)

        with open(entities_file) as f:
            entities = json.load(f)

        graph = {}
        if graph_file.exists():
            with open(graph_file) as f:
                graph = json.load(f)

        return events, entities, graph

    def load_queries(self) -> list[dict]:
        """Load benchmark queries."""
        with open(self.config.queries_path) as f:
            data = json.load(f)
        return data['queries']

    def load_document(self, doc_path: str) -> str:
        """Load document content."""
        full_path = self.config.corpus_path / doc_path
        with open(full_path) as f:
            return f.read()

    async def run_extraction_benchmarks(self, events_truth: dict) -> dict:
        """Run event extraction quality benchmarks."""
        results = []
        documents = events_truth.get('documents', {})
        errors = []

        for doc_id, doc_truth in documents.items():
            print(f"  Evaluating event extraction: {doc_id}", flush=True)

            try:
                content = self.load_document(doc_id)
                predicted_events, artifact_id = await self.client.extract_events(content, doc_id)

                if self.config.record and artifact_id:
                    self.id_store.save_id_mapping(artifact_id, doc_id)

                result = evaluate_extraction(
                    predicted_events,
                    doc_truth['events'],
                    require_category_match=False  # V7.3: Dynamic categories - match by narrative only
                )
                print(f"    -> {doc_id}: {len(predicted_events)} extracted, F1={result.f1:.2f}", flush=True)
                results.append({
                    'doc_id': doc_id,
                    'precision': result.precision,
                    'recall': result.recall,
                    'f1': result.f1,
                    'tp': result.true_positives,
                    'fp': result.false_positives,
                    'fn': result.false_negatives
                })
            except Exception as e:
                error_msg = f"{doc_id}: {e}"
                print(f"    ERROR: {e}")
                errors.append(error_msg)
                results.append({
                    'doc_id': doc_id,
                    'error': str(e)
                })

        # Aggregate results (only from successful evaluations)
        valid_results = [r for r in results if 'error' not in r]

        if not valid_results:
            return {
                'per_document': results,
                'aggregated': {'precision': 0, 'recall': 0, 'f1': 0},
                'pass': False,
                'errors': errors
            }

        extraction_results = [
            ExtractionResult(
                precision=r['precision'],
                recall=r['recall'],
                f1=r['f1'],
                true_positives=r['tp'],
                false_positives=r['fp'],
                false_negatives=r['fn'],
                matched_pairs=[],
                unmatched_predicted=[],
                unmatched_ground_truth=[]
            )
            for r in valid_results
        ]

        aggregated = agg_extraction(extraction_results)

        return {
            'per_document': results,
            'aggregated': aggregated,
            'pass': aggregated.get('f1', 0) >= self.config.min_extraction_f1 and not errors,
            'errors': errors
        }

    async def run_entity_benchmarks(self, entities_truth: dict) -> dict:
        """Run entity extraction quality benchmarks."""
        results = []
        documents = entities_truth.get('documents', {})
        errors = []

        for doc_id, doc_truth in documents.items():
            print(f"  Evaluating entity extraction: {doc_id}", flush=True)

            try:
                content = self.load_document(doc_id)
                predicted_entities = await self.client.extract_entities(content, doc_id)

                result = evaluate_entity_extraction(
                    predicted_entities,
                    doc_truth['entities']
                )
                results.append({
                    'doc_id': doc_id,
                    'precision': result.precision,
                    'recall': result.recall,
                    'f1': result.f1,
                    'tp': result.true_positives,
                    'fp': result.false_positives,
                    'fn': result.false_negatives
                })
            except Exception as e:
                error_msg = f"{doc_id}: {e}"
                print(f"    ERROR: {e}")
                errors.append(error_msg)
                results.append({
                    'doc_id': doc_id,
                    'error': str(e)
                })

        # Aggregate results
        valid_results = [r for r in results if 'error' not in r]

        if not valid_results:
            return {
                'per_document': results,
                'aggregated': {'precision': 0, 'recall': 0, 'f1': 0},
                'pass': False,
                'errors': errors
            }

        extraction_results = [
            ExtractionResult(
                precision=r['precision'],
                recall=r['recall'],
                f1=r['f1'],
                true_positives=r['tp'],
                false_positives=r['fp'],
                false_negatives=r['fn'],
                matched_pairs=[],
                unmatched_predicted=[],
                unmatched_ground_truth=[]
            )
            for r in valid_results
        ]

        aggregated = agg_extraction(extraction_results)

        return {
            'per_document': results,
            'aggregated': aggregated,
            'pass': aggregated.get('f1', 0) >= self.config.min_entity_f1 and not errors,
            'errors': errors
        }

    async def run_retrieval_benchmarks(self, queries: list[dict]) -> dict:
        """Run retrieval quality benchmarks."""
        results = []
        errors = []

        for query in queries:
            query_id = query['id']
            query_text = query['query']
            print(f"  Evaluating retrieval: {query_id}", flush=True)

            try:
                retrieved = await self.client.recall(query_text, query_id)

                # Translate artifact IDs to corpus paths for evaluation
                translated_retrieved = [
                    self.id_store.translate_id(doc_id)
                    for doc_id in retrieved
                ]

                # Build relevance judgments dict
                relevance = {}
                for doc in query.get('relevant_documents', []):
                    relevance[doc['doc']] = doc['relevance']

                result = evaluate_retrieval(translated_retrieved, relevance)
                results.append({
                    'query_id': query_id,
                    'mrr': result.mrr,
                    'ndcg': result.ndcg,
                    'ndcg_at_5': result.ndcg_at_5,
                    'precision_at_3': result.precision_at_3,
                    'recall_at_5': result.recall_at_5,
                    'first_relevant_rank': result.first_relevant_rank
                })
            except Exception as e:
                error_msg = f"{query_id}: {e}"
                print(f"    ERROR: {e}")
                errors.append(error_msg)
                results.append({
                    'query_id': query_id,
                    'error': str(e)
                })

        # Aggregate (only from successful evaluations)
        valid_results = [r for r in results if 'error' not in r]

        if not valid_results:
            return {
                'per_query': results,
                'aggregated': {'mrr': 0, 'ndcg': 0},
                'pass_mrr': False,
                'pass_ndcg': False,
                'errors': errors
            }

        retrieval_results = [
            RetrievalResult(
                mrr=r['mrr'],
                ndcg=r['ndcg'],
                ndcg_at_3=0,
                ndcg_at_5=r['ndcg_at_5'],
                precision_at_1=0,
                precision_at_3=r['precision_at_3'],
                precision_at_5=0,
                recall_at_5=r['recall_at_5'],
                recall_at_10=0,
                first_relevant_rank=r['first_relevant_rank'],
                num_retrieved=0,
                num_relevant=0,
                relevant_retrieved=0
            )
            for r in valid_results
        ]

        aggregated = aggregate_retrieval_results(retrieval_results)

        return {
            'per_query': results,
            'aggregated': aggregated,
            'pass_mrr': aggregated.get('mrr', 0) >= self.config.min_retrieval_mrr and not errors,
            'pass_ndcg': aggregated.get('ndcg', 0) >= self.config.min_retrieval_ndcg and not errors,
            'errors': errors
        }

    async def run_graph_benchmarks(self, graph_truth: dict, entities_truth: dict = None) -> dict:
        """Run graph expansion quality benchmarks."""
        benchmark_queries = graph_truth.get('benchmark_queries', [])
        if not benchmark_queries:
            return {
                'per_query': [],
                'aggregated': {},
                'pass': True,
                'errors': [],
                'skipped': True
            }

        # Build name → ID mapping from entities ground truth
        # This allows matching "Bob Smith" to "ent_bob"
        name_to_id = {}
        if entities_truth:
            for entity_list in entities_truth.get('global_entities', {}).values():
                for entity in entity_list:
                    name = entity.get('name', '')
                    ent_id = entity.get('id', '')
                    if name and ent_id:
                        # Map full name and normalized variants
                        name_to_id[name.lower()] = ent_id
                        # Also map first name only (e.g., "Bob" -> "ent_bob")
                        first_name = name.split()[0].lower() if name else ''
                        if first_name:
                            name_to_id[first_name] = ent_id

        results = []
        errors = []

        for query in benchmark_queries:
            query_id = query['id']
            # Use the natural language query for recall, not the entity ID
            query_text = query.get('query', '')
            seed = query.get('seed', query.get('seed_from', ''))
            # If no query provided, translate seed to name using our mapping
            if not query_text and seed:
                seed_lower = seed.replace('ent_', '').lower()
                # Try to find full name from mapping (reverse lookup)
                for name, ent_id in name_to_id.items():
                    if ent_id == seed:
                        query_text = name.title()  # Use the name as query
                        break
                if not query_text:
                    query_text = seed  # Fallback to seed ID
            print(f"  Evaluating graph expansion: {query_id}", flush=True)

            try:
                connections, docs = await self.client.graph_expand(query_text, query_id)

                # Translate artifact IDs to corpus paths
                translated_docs = [
                    self.id_store.translate_id(doc_id)
                    for doc_id in docs
                ]

                # Translate entity names to IDs for comparison
                # e.g., "Bob Smith" -> "ent_bob"
                translated_connections = set()
                for conn in connections:
                    conn_lower = conn.lower()
                    if conn_lower in name_to_id:
                        translated_connections.add(name_to_id[conn_lower])
                    else:
                        # Try first name only
                        first_name = conn.split()[0].lower() if conn else ''
                        if first_name in name_to_id:
                            translated_connections.add(name_to_id[first_name])
                        else:
                            translated_connections.add(conn)  # Keep original if no match

                # Evaluate connection quality
                expected_connections = set(query.get('expected_connections', []))
                expected_docs = set(query.get('expected_docs', []))

                conn_result = evaluate_graph_expansion(
                    translated_connections,
                    expected_connections
                )
                doc_result = evaluate_graph_expansion(
                    set(translated_docs),
                    expected_docs
                )

                results.append({
                    'query_id': query_id,
                    'connection_precision': conn_result['precision'],
                    'connection_recall': conn_result['recall'],
                    'connection_f1': conn_result['f1'],
                    'doc_precision': doc_result['precision'],
                    'doc_recall': doc_result['recall'],
                    'doc_f1': doc_result['f1']
                })
            except Exception as e:
                error_msg = f"{query_id}: {e}"
                print(f"    ERROR: {e}")
                errors.append(error_msg)
                results.append({
                    'query_id': query_id,
                    'error': str(e)
                })

        # Aggregate
        valid_results = [r for r in results if 'error' not in r]

        if not valid_results:
            return {
                'per_query': results,
                'aggregated': {'connection_f1': 0, 'doc_f1': 0},
                'pass': False,
                'errors': errors
            }

        n = len(valid_results)
        aggregated = {
            'connection_precision': sum(r['connection_precision'] for r in valid_results) / n,
            'connection_recall': sum(r['connection_recall'] for r in valid_results) / n,
            'connection_f1': sum(r['connection_f1'] for r in valid_results) / n,
            'doc_precision': sum(r['doc_precision'] for r in valid_results) / n,
            'doc_recall': sum(r['doc_recall'] for r in valid_results) / n,
            'doc_f1': sum(r['doc_f1'] for r in valid_results) / n,
            'num_queries': n
        }

        avg_f1 = (aggregated['connection_f1'] + aggregated['doc_f1']) / 2

        return {
            'per_query': results,
            'aggregated': aggregated,
            'pass': avg_f1 >= self.config.min_graph_f1 and not errors,
            'errors': errors
        }

    async def run(self) -> dict:
        """Run all benchmarks and generate report."""
        print(f"\n{'='*60}")
        print(f"V7 Quality Benchmark Suite")
        print(f"Mode: LIVE")
        print(f"{'='*60}\n")

        events_truth, entities_truth, graph_truth = self.load_ground_truth()
        queries = self.load_queries()

        print("Running event extraction benchmarks...")
        extraction_results = await self.run_extraction_benchmarks(events_truth)

        print("\nRunning entity extraction benchmarks...")
        entity_results = await self.run_entity_benchmarks(entities_truth)

        print("\nRunning retrieval benchmarks...")
        retrieval_results = await self.run_retrieval_benchmarks(queries)

        print("\nRunning graph expansion benchmarks...")
        graph_results = await self.run_graph_benchmarks(graph_truth, entities_truth)

        # Collect all errors
        all_errors = (
            extraction_results.get('errors', []) +
            entity_results.get('errors', []) +
            retrieval_results.get('errors', []) +
            graph_results.get('errors', [])
        )

        # Build report
        report = {
            'timestamp': datetime.now().isoformat(),
            'mode': 'live',
            'extraction': extraction_results,
            'entities': entity_results,
            'retrieval': retrieval_results,
            'graph': graph_results,
            'overall_pass': (
                extraction_results.get('pass', False) and
                entity_results.get('pass', False) and
                retrieval_results.get('pass_mrr', False) and
                retrieval_results.get('pass_ndcg', False) and
                graph_results.get('pass', False) and
                len(all_errors) == 0
            ),
            'errors': all_errors
        }

        # Save report
        self.config.reports_path.mkdir(parents=True, exist_ok=True)
        report_file = self.config.reports_path / f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)

        # Print summary
        print(f"\n{'='*60}")
        print("RESULTS SUMMARY")
        print(f"{'='*60}")

        print(f"\nEvent Extraction Metrics:")
        agg = extraction_results.get('aggregated', {})
        print(f"  Precision: {agg.get('precision', 0):.3f}")
        print(f"  Recall:    {agg.get('recall', 0):.3f}")
        print(f"  F1:        {agg.get('f1', 0):.3f}")
        print(f"  Pass:      {'OK' if extraction_results.get('pass') else 'FAIL'}")

        print(f"\nEntity Extraction Metrics:")
        agg = entity_results.get('aggregated', {})
        print(f"  Precision: {agg.get('precision', 0):.3f}")
        print(f"  Recall:    {agg.get('recall', 0):.3f}")
        print(f"  F1:        {agg.get('f1', 0):.3f}")
        print(f"  Pass:      {'OK' if entity_results.get('pass') else 'FAIL'}")

        print(f"\nRetrieval Metrics:")
        agg = retrieval_results.get('aggregated', {})
        print(f"  MRR:       {agg.get('mrr', 0):.3f}")
        print(f"  NDCG:      {agg.get('ndcg', 0):.3f}")
        print(f"  NDCG@5:    {agg.get('ndcg_at_5', 0):.3f}")
        print(f"  Pass MRR:  {'OK' if retrieval_results.get('pass_mrr') else 'FAIL'}")
        print(f"  Pass NDCG: {'OK' if retrieval_results.get('pass_ndcg') else 'FAIL'}")

        print(f"\nGraph Expansion Metrics:")
        if graph_results.get('skipped'):
            print(f"  (Skipped - no graph queries defined)")
        else:
            agg = graph_results.get('aggregated', {})
            print(f"  Conn P:    {agg.get('connection_precision', 0):.3f}")
            print(f"  Conn R:    {agg.get('connection_recall', 0):.3f}")
            print(f"  Conn F1:   {agg.get('connection_f1', 0):.3f}")
            print(f"  Doc F1:    {agg.get('doc_f1', 0):.3f}")
            print(f"  Pass:      {'OK' if graph_results.get('pass') else 'FAIL'}")

        if all_errors:
            print(f"\nErrors ({len(all_errors)}):")
            for err in all_errors[:5]:
                print(f"  - {err}")
            if len(all_errors) > 5:
                print(f"  ... and {len(all_errors) - 5} more")

        print(f"\n{'='*60}")
        print(f"OVERALL: {'PASS' if report['overall_pass'] else 'FAIL'}")
        print(f"{'='*60}")
        print(f"\nReport saved to: {report_file}")

        return report


def main():
    parser = argparse.ArgumentParser(description='V7 Quality Benchmark Runner')
    parser.add_argument('--record', action='store_true',
                        help='Record ID mappings for retrieval evaluation')
    parser.add_argument('--min-extraction-f1', type=float, default=0.70,
                        help='Minimum extraction F1 threshold')
    parser.add_argument('--min-entity-f1', type=float, default=0.70,
                        help='Minimum entity F1 threshold')
    parser.add_argument('--min-retrieval-mrr', type=float, default=0.60,
                        help='Minimum retrieval MRR threshold')
    parser.add_argument('--min-graph-f1', type=float, default=0.60,
                        help='Minimum graph expansion F1 threshold')

    args = parser.parse_args()

    config = BenchmarkConfig(
        record=args.record,
        min_extraction_f1=args.min_extraction_f1,
        min_entity_f1=args.min_entity_f1,
        min_retrieval_mrr=args.min_retrieval_mrr,
        min_graph_f1=args.min_graph_f1
    )

    runner = BenchmarkRunner(config)
    report = asyncio.run(runner.run())

    # Exit with appropriate code for CI
    sys.exit(0 if report['overall_pass'] else 1)


if __name__ == '__main__':
    main()
