"""
MCP Memory Server v6.1 - Simplified Interface

A Model Context Protocol server with 4 tools for persistent memory and context:
- remember() - Store content with automatic chunking, embedding, and event extraction
- recall() - Find content with semantic search and graph expansion
- forget() - Delete content with cascade (chunks, events, entities)
- status() - Check system health and job status

Features:
- Unified content storage (content + chunks collections in ChromaDB)
- Content-based ID generation (art_ + SHA256[:12]) for deduplication
- Semantic event extraction (decisions, commitments, risks, etc.)
- Graph expansion via PostgreSQL joins for related context discovery
- Entity resolution for people, organizations, and projects

Usage:
    python server.py

Configuration via .env file (see .env.example)
"""

# Version and build info
__version__ = "6.1.0"

import os
import logging
import hashlib
from datetime import datetime, date
from contextlib import asynccontextmanager
from typing import Optional, List, Any

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse, RedirectResponse
from starlette.middleware import Middleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from dotenv import load_dotenv

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

# Load environment variables
load_dotenv()

# Import configuration and services
from config import load_config, validate_config
from services.embedding_service import EmbeddingService
from services.chunking_service import ChunkingService
from services.retrieval_service import RetrievalService
from services.privacy_service import PrivacyFilterService
from storage.chroma_client import ChromaClientManager
from storage.collections import (
    get_content_collection,
    get_chunks_collection,
    get_content_by_id,
    get_v5_chunks_by_content,
    delete_v5_content_cascade
)
from utils.errors import (
    ValidationError,
    EmbeddingError,
)

# V3: Postgres and event extraction imports
from storage.postgres_client import PostgresClient
from services.job_queue_service import JobQueueService
from tools.event_tools import event_search, event_get

# Graph expansion uses Postgres SQL joins (no external graph database)

# Setup logging
logger = logging.getLogger("mcp-memory")

# Create FastMCP server
mcp = FastMCP(f"MCP Memory v{__version__}")

# Global services (initialized in lifespan)
config = None
embedding_service: Optional[EmbeddingService] = None
chunking_service: Optional[ChunkingService] = None
retrieval_service: Optional[RetrievalService] = None
privacy_service: Optional[PrivacyFilterService] = None
chroma_manager: Optional[ChromaClientManager] = None

# V6: Postgres for events and graph expansion via SQL joins
pg_client: Optional[PostgresClient] = None
job_queue_service: Optional[JobQueueService] = None


def parse_date_string(date_str: Optional[str]) -> Optional[date]:
    """Convert a date string (YYYY-MM-DD) to a Python date object for Postgres."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


# ============================================================================
# V6 TOOLS - Simplified Interface (4 tools)
# ============================================================================

# Valid context types for content storage
V6_VALID_CONTEXTS = [
    # Document types (chunked, full extraction)
    "meeting",      # Meeting notes
    "email",        # Email content
    "document",     # General documents
    "chat",         # Chat logs
    "transcript",   # Transcripts
    "note",         # Notes (can be small or large)
    # Memory types (small, single-chunk)
    "preference",   # User preferences
    "fact",         # Known facts
    "decision",     # Decisions made
    "project",      # Project information
    # Conversation (timestamped turns)
    "conversation", # Conversation turns
]


@mcp.tool()
async def remember(
    content: str,
    context: Optional[str] = None,
    source: Optional[str] = None,
    importance: float = 0.5,
    title: Optional[str] = None,
    author: Optional[str] = None,
    participants: Optional[List[str]] = None,
    date: Optional[str] = None,
    # Conversation tracking
    conversation_id: Optional[str] = None,
    turn_index: Optional[int] = None,
    role: Optional[str] = None,
    # Advanced metadata
    sensitivity: str = "normal",
    visibility_scope: str = "me",
    retention_policy: str = "forever",
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    # Source metadata for credibility reasoning
    document_date: Optional[str] = None,
    source_type: Optional[str] = None,
    document_status: Optional[str] = None,
    author_title: Optional[str] = None,
    distribution_scope: Optional[str] = None,
) -> dict:
    """
    Store content for long-term recall.

    Everything stored is automatically:
    - Chunked if large (>900 tokens)
    - Embedded for semantic search
    - Analyzed for events (decisions, commitments, etc.)
    - Added to the knowledge graph

    Args:
        content: What to remember (text, up to 10MB)
        context: Type of content (meeting, email, note, preference, fact, conversation)
        source: Where it came from (gmail, slack, manual, user)
        importance: Priority for retrieval (0.0-1.0)
        title: Optional title/subject
        author: Who created it
        participants: People involved
        date: When it happened (ISO8601)
        conversation_id: Conversation identifier (required for context="conversation")
        turn_index: Turn number in conversation (required for context="conversation")
        role: Speaker role in conversation (user, assistant, system)
        sensitivity: Privacy level (normal, sensitive, highly_sensitive)
        visibility_scope: Who can see (me, team, org, custom)
        retention_policy: How long to keep (forever, 1y, until_resolved, custom)
        source_id: Unique ID in source system (for deduplication)
        source_url: Link to original document

    Returns:
        {id, summary, events_queued, context}

    Examples:
        remember("User prefers dark mode")
        remember("Meeting notes...", context="meeting", source="slack")
        remember(email_body, context="email", author="alice@example.com")
        remember("Hello!", context="conversation", conversation_id="conv_123", turn_index=0, role="user")
    """
    try:
        # Validate content
        if not content or len(content) > 10000000:
            return {"error": "Content must be between 1 and 10,000,000 characters"}

        # Validate context
        if context and context not in V6_VALID_CONTEXTS:
            return {"error": f"Invalid context '{context}'. Must be one of: {', '.join(V6_VALID_CONTEXTS)}"}

        # Default context
        if not context:
            context = "note"

        # Validate conversation requirements
        if context == "conversation":
            if conversation_id is None or turn_index is None:
                return {"error": "context='conversation' requires conversation_id and turn_index"}
            if role and role not in ["user", "assistant", "system"]:
                return {"error": f"Invalid role '{role}'. Must be one of: user, assistant, system"}

        # Validate importance
        if not 0.0 <= importance <= 1.0:
            return {"error": "importance must be between 0.0 and 1.0"}

        # Validate sensitivity
        if sensitivity not in ["normal", "sensitive", "highly_sensitive"]:
            return {"error": f"Invalid sensitivity '{sensitivity}'"}

        # Validate visibility_scope
        if visibility_scope not in ["me", "team", "org", "custom"]:
            return {"error": f"Invalid visibility_scope '{visibility_scope}'"}

        # Generate content-based ID: art_ + SHA256(content)[:12]
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        artifact_id = f"art_{content_hash}"

        # Check for existing content (idempotent deduplication)
        client = chroma_manager.get_client()
        existing = get_content_by_id(client, artifact_id)

        if existing:
            # Same content already exists - upsert metadata
            logger.info(f"V6 remember: Content {artifact_id} already exists, upserting metadata")
            content_col = get_content_collection(client)

            # Merge metadata
            existing_meta = existing.get("metadata", {})
            updated_meta = {
                **existing_meta,
                "ingested_at": datetime.utcnow().isoformat() + "Z",
                "importance": importance,
            }
            if title:
                updated_meta["title"] = title
            if author:
                updated_meta["author"] = author
            if source:
                updated_meta["source_system"] = source

            content_col.update(
                ids=[artifact_id],
                metadatas=[updated_meta]
            )

            return {
                "id": artifact_id,
                "summary": f"Updated existing content ({context})",
                "events_queued": False,
                "context": context,
                "status": "unchanged"
            }

        # Generate embedding
        embedding = embedding_service.generate_embedding(content)

        # Count tokens for chunking decision
        token_count = chunking_service.count_tokens(content)

        # Build metadata
        metadata = {
            "context": context,
            "source_system": source or "manual",
            "importance": importance,
            "sensitivity": sensitivity,
            "visibility_scope": visibility_scope,
            "retention_policy": retention_policy,
            "ingested_at": datetime.utcnow().isoformat() + "Z",
            "token_count": token_count,
            "content_hash": content_hash,
            "embedding_provider": "openai",
            "embedding_model": config.openai_embed_model,
            "embedding_dimensions": config.openai_embed_dims,
        }

        # Add optional fields
        if title:
            metadata["title"] = title
        if author:
            metadata["author"] = author
        if participants:
            metadata["participants"] = ",".join(participants)
        if date:
            metadata["ts"] = date
        if source_id:
            metadata["source_id"] = source_id
        if source_url:
            metadata["source_url"] = source_url
        if document_date:
            metadata["document_date"] = document_date
        if source_type:
            metadata["source_type"] = source_type
        if document_status:
            metadata["document_status"] = document_status
        if author_title:
            metadata["author_title"] = author_title
        if distribution_scope:
            metadata["distribution_scope"] = distribution_scope

        # Conversation-specific metadata
        if context == "conversation":
            metadata["conversation_id"] = conversation_id
            metadata["turn_index"] = turn_index
            if role:
                metadata["role"] = role

        # Chunk if needed (use ChunkingService threshold, default 1200 tokens)
        should_chunk_result, _ = chunking_service.should_chunk(content)
        is_chunked = should_chunk_result
        num_chunks = 0

        if is_chunked:
            # Chunk the content
            chunks = chunking_service.chunk_text(content, artifact_id)
            num_chunks = len(chunks)

            # Store each chunk in V6 chunks collection with full metadata
            # Including start_char/end_char for evidence pipeline
            chunks_col = get_chunks_collection(client)
            for chunk in chunks:
                # Use stable chunk_id from ChunkingService (includes content hash)
                chunk_embedding = embedding_service.generate_embedding(chunk.content)
                chunks_col.add(
                    ids=[chunk.chunk_id],
                    documents=[chunk.content],
                    metadatas=[{
                        "content_id": artifact_id,
                        "chunk_index": chunk.chunk_index,
                        "total_chunks": num_chunks,
                        "token_count": chunk.token_count,
                        "start_char": chunk.start_char,
                        "end_char": chunk.end_char,
                        "content_hash": chunk.content_hash,
                    }],
                    embeddings=[chunk_embedding]
                )

            metadata["is_chunked"] = True
            metadata["num_chunks"] = num_chunks
            logger.info(f"V6 remember: Chunked content {artifact_id} into {num_chunks} chunks")
        else:
            metadata["is_chunked"] = False
            metadata["num_chunks"] = 0

        # Store main content in V6 content collection
        content_col = get_content_collection(client)
        content_col.add(
            ids=[artifact_id],
            documents=[content],
            metadatas=[metadata],
            embeddings=[embedding]
        )

        # Queue event extraction (Decision 1: Semantic Unification)
        # Exception: Short conversation turns < 100 tokens skip extraction
        events_queued = False
        job_id = None

        should_extract = True
        if context == "conversation" and token_count < 100:
            should_extract = False
            logger.info(f"V6 remember: Skipping event extraction for short conversation turn ({token_count} tokens)")

        if should_extract and pg_client and job_queue_service:
            try:
                # Create artifact_uid and revision_id for Postgres
                artifact_uid = f"uid_{content_hash}"
                revision_id = f"rev_{content_hash}"

                # Write to Postgres artifact_revision
                await pg_client.transaction([
                    (
                        "UPDATE artifact_revision SET is_latest = false WHERE artifact_uid = $1 AND is_latest = true",
                        (artifact_uid,)
                    ),
                    (
                        """INSERT INTO artifact_revision
                           (artifact_uid, revision_id, artifact_id, artifact_type, source_system, source_id, content_hash, token_count, is_chunked, chunk_count)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                           ON CONFLICT (artifact_uid, revision_id) DO NOTHING""",
                        (
                            artifact_uid,
                            revision_id,
                            artifact_id,
                            context,  # Use context as artifact_type
                            source or "manual",
                            source_id or "",
                            content_hash,
                            token_count,
                            is_chunked,
                            num_chunks,
                        )
                    )
                ])

                # Enqueue event extraction job
                job_uuid = await job_queue_service.enqueue_job(artifact_uid, revision_id)
                if job_uuid:
                    job_id = str(job_uuid)
                    events_queued = True
                    logger.info(f"V6 remember: Enqueued extraction job {job_id} for {artifact_id}")

            except Exception as e:
                logger.warning(f"V6 remember: Failed to queue event extraction: {e}")

        # Generate summary
        summary = content[:100] + "..." if len(content) > 100 else content

        logger.info(f"V6 remember: Stored {artifact_id} ({context}, {token_count} tokens, chunked={is_chunked})")

        return {
            "id": artifact_id,
            "summary": summary,
            "events_queued": events_queued,
            "context": context,
            "is_chunked": is_chunked,
            "num_chunks": num_chunks,
            "token_count": token_count
        }

    except ValidationError as e:
        return {"error": f"Validation error: {e}"}
    except EmbeddingError as e:
        return {"error": f"Embedding error: {e}"}
    except Exception as e:
        logger.error(f"V6 remember error: {e}", exc_info=True)
        return {"error": f"Internal server error: {str(e)}"}


@mcp.tool()
async def recall(
    query: Optional[str] = None,
    id: Optional[str] = None,
    context: Optional[str] = None,
    limit: int = 10,
    expand: bool = True,
    include_events: bool = True,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    conversation_id: Optional[str] = None,
    # Advanced graph parameters
    graph_budget: int = 10,
    graph_filters: Optional[List[str]] = None,
    include_entities: bool = True,
    expand_neighbors: bool = False,
    # V9: Edge parameters
    edge_types: Optional[List[str]] = None,
    include_edges: bool = False,
    # Filtering
    min_importance: float = 0.0,
    source: Optional[str] = None,
    sensitivity: Optional[str] = None,
) -> dict:
    """
    Find and retrieve stored content.

    Can search semantically, get by ID, or list with filters.
    By default, includes related context from the knowledge graph.

    Args:
        query: What to search for (natural language)
        id: Specific content ID to retrieve
        context: Filter by type (meeting, email, preference, etc.)
        limit: Maximum results (default 10)
        expand: Include related content via graph (default True)
        include_events: Include extracted events (default True)
        date_from: Filter by date range start
        date_to: Filter by date range end
        conversation_id: Get specific conversation history
        graph_budget: Max related items from graph expansion (1-50)
        graph_filters: Event categories for graph expansion
        include_entities: Include entity information in response
        expand_neighbors: Include +/-1 adjacent chunks for context
        edge_types: Filter graph expansion by relationship types (e.g., ["MANAGES", "DECIDED"])
        include_edges: Include edge/relationship details in response
        min_importance: Minimum importance threshold (0.0-1.0)
        source: Filter by source system
        sensitivity: Filter by sensitivity level

    Returns:
        {
            results: [...],           # Primary matches
            related: [...],           # Graph-expanded context
            entities: [...],          # People/things mentioned
            edges: [...],             # Relationships (if include_edges=True)
            total_count: int
        }

    Examples:
        recall("user preferences")
        recall(id="art_abc123")
        recall(context="meeting", limit=5)
        recall("what did Alice decide?", expand=True)
        recall(conversation_id="conv_123", limit=20)
    """
    try:
        # Validate limit
        if limit < 1 or limit > 50:
            return {"error": "Limit must be between 1 and 50"}

        client = chroma_manager.get_client()

        # Direct ID lookup
        if id:
            # Handle event ID lookup
            if id.startswith("evt_"):
                if not pg_client:
                    return {"error": "Event lookup requires PostgreSQL", "error_code": "V3_UNAVAILABLE"}

                from tools.event_tools import event_get
                event_result = await event_get(pg_client, id)
                if "error" in event_result:
                    return event_result

                return {
                    "results": [event_result],
                    "related": [],
                    "entities": [],
                    "total_count": 1
                }

            # Handle content ID lookup (art_ only)
            if not id.startswith("art_"):
                return {"error": f"Invalid ID format. Use art_xxx or evt_xxx. Got: {id}"}

            content_data = get_content_by_id(client, id)
            if not content_data:
                return {"results": [], "related": [], "entities": [], "total_count": 0}

            # Get events for this content if requested
            events = []
            if include_events and pg_client:
                try:
                    content_hash = id.replace("art_", "")
                    artifact_uid = f"uid_{content_hash}"

                    event_rows = await pg_client.fetch_all(
                        """
                        SELECT event_id, category, narrative, confidence, event_time,
                               actors_json, subject_json
                        FROM semantic_event
                        WHERE artifact_uid = $1
                        ORDER BY event_time DESC
                        LIMIT 20
                        """,
                        artifact_uid
                    )
                    for row in event_rows:
                        events.append({
                            "event_id": f"evt_{row['event_id']}",
                            "category": row["category"],
                            "narrative": row["narrative"],
                            "confidence": float(row["confidence"]) if row["confidence"] else None,
                            "event_time": str(row["event_time"]) if row["event_time"] else None,
                            "actors": row["actors_json"],  # V7.3: Include actors for entity extraction
                            "subject": row["subject_json"]  # V7.3: Include subject for entity extraction
                        })
                except Exception as e:
                    logger.warning(f"V6 recall: Failed to fetch events: {e}")

            result = {
                "id": content_data["id"],
                "content": content_data["content"],
                "metadata": content_data["metadata"],
                "events": events
            }

            return {
                "results": [result],
                "related": [],
                "entities": [],
                "total_count": 1
            }

        # Conversation history retrieval (Decision 5: Structured return)
        if conversation_id:
            content_col = get_content_collection(client)

            try:
                results = content_col.get(
                    where={
                        "$and": [
                            {"context": "conversation"},
                            {"conversation_id": conversation_id},
                        ]
                    },
                    include=["documents", "metadatas"]
                )

                turns = []
                ids = results.get("ids", [])
                docs = results.get("documents", [])
                metas = results.get("metadatas", [])

                for doc_id, doc, meta in zip(ids, docs, metas):
                    turns.append({
                        "id": doc_id,
                        "role": meta.get("role", "user") if meta else "user",
                        "turn_index": meta.get("turn_index", 0) if meta else 0,
                        "ts": meta.get("ts", meta.get("ingested_at")) if meta else None,
                        "content": doc,
                    })

                # Sort by turn_index
                turns.sort(key=lambda t: t["turn_index"])

                # Apply limit
                if limit:
                    turns = turns[:limit]

                return {
                    "turns": turns,
                    "total_turns": len(turns),
                    "conversation_id": conversation_id,
                    "results": [],
                    "related": [],
                    "entities": []
                }

            except Exception as e:
                logger.error(f"V6 recall: Failed to get conversation history: {e}")
                return {"error": f"Failed to get conversation history: {str(e)}"}

        # Semantic search
        if query:
            if not query or len(query) > 500:
                return {"error": "Query must be between 1 and 500 characters"}

            # Use graph_filters default if not provided
            if graph_filters is None:
                graph_filters = ["Decision", "Commitment", "QualityRisk"]

            # V6: Use hybrid_search_v5 which searches V6 content collection
            # Build graph filters dict
            gf = {}
            if graph_filters:
                gf["categories"] = graph_filters
            if edge_types:
                gf["edge_types"] = edge_types

            v5_result = await retrieval_service.hybrid_search_v5(
                query=query,
                limit=limit,
                expand=expand,
                graph_budget=graph_budget,
                graph_filters=gf if gf else None,
                include_entities=include_entities,
                context_filter=context,
                min_importance=min_importance,
                date_from=date_from,
                date_to=date_to,
            )

            v4_dict = v5_result.to_dict()

            # Also search semantic events if requested
            event_results = []
            if include_events and pg_client:
                try:
                    from tools.event_tools import event_search
                    event_response = await event_search(
                        pg_client,
                        query=query,
                        limit=limit,
                        include_evidence=True
                    )
                    if "events" in event_response:
                        event_results = event_response["events"]
                except Exception as e:
                    logger.warning(f"V6 recall: Event search failed: {e}")

            # Combine results
            primary_results = v4_dict.get("primary_results", [])

            # Add events to results
            for ev in event_results:
                primary_results.append({
                    "type": "event",
                    "id": ev.get("event_id"),
                    "category": ev.get("category"),
                    "narrative": ev.get("narrative"),
                    "event_time": ev.get("event_time"),
                    "confidence": ev.get("confidence"),
                    "evidence": ev.get("evidence", [])
                })

            # V9: Fetch edges if requested
            edges = []
            if include_edges and pg_client:
                try:
                    # Get entity IDs from results
                    entity_ids = []
                    for ent in v4_dict.get("entities", []):
                        if ent.get("entity_id"):
                            entity_ids.append(ent["entity_id"])

                    if entity_ids:
                        # Build edge type filter
                        edge_type_clause = ""
                        params = entity_ids + entity_ids  # For source and target
                        if edge_types:
                            placeholders = ", ".join(f"${i}" for i in range(len(entity_ids) * 2 + 1, len(entity_ids) * 2 + 1 + len(edge_types)))
                            edge_type_clause = f"AND ee.relationship_type IN ({placeholders})"
                            params = params + edge_types

                        source_placeholders = ", ".join(f"${i}" for i in range(1, len(entity_ids) + 1))
                        target_placeholders = ", ".join(f"${i}" for i in range(len(entity_ids) + 1, len(entity_ids) * 2 + 1))

                        edge_rows = await pg_client.fetch_all(
                            f"""
                            SELECT
                                ee.edge_id,
                                ee.relationship_type,
                                ee.relationship_name,
                                ee.confidence,
                                ee.evidence_quote,
                                e1.canonical_name AS source_name,
                                e1.entity_type AS source_type,
                                e2.canonical_name AS target_name,
                                e2.entity_type AS target_type
                            FROM entity_edge ee
                            JOIN entity e1 ON e1.entity_id = ee.source_entity_id
                            JOIN entity e2 ON e2.entity_id = ee.target_entity_id
                            WHERE (ee.source_entity_id IN ({source_placeholders})
                                   OR ee.target_entity_id IN ({target_placeholders}))
                            {edge_type_clause}
                            ORDER BY ee.confidence DESC
                            LIMIT 50
                            """,
                            *params
                        )

                        for row in edge_rows:
                            edges.append({
                                "edge_id": str(row["edge_id"]),
                                "source": row["source_name"],
                                "source_type": row["source_type"],
                                "target": row["target_name"],
                                "target_type": row["target_type"],
                                "type": row["relationship_type"],
                                "name": row["relationship_name"],
                                "confidence": float(row["confidence"]) if row["confidence"] else None,
                                "evidence": row["evidence_quote"]
                            })
                except Exception as e:
                    logger.warning(f"V9 recall: Failed to fetch edges: {e}")

            result = {
                "results": primary_results,
                "related": v4_dict.get("related_context", []) if expand else [],
                "entities": v4_dict.get("entities", []) if include_entities else [],
                "total_count": len(primary_results)
            }

            if include_edges:
                result["edges"] = edges

            return result

        # No query, id, or conversation_id - return error
        return {"error": "Must provide query, id, or conversation_id"}

    except Exception as e:
        logger.error(f"V6 recall error: {e}", exc_info=True)
        return {"error": f"Search failed: {str(e)}"}


@mcp.tool()
async def forget(
    id: str,
    confirm: bool = False,
) -> dict:
    """
    Delete stored content.

    Removes content and all associated data (chunks, events, graph nodes).
    Requires confirm=True as a safety measure.

    Args:
        id: Content ID to delete (art_xxx only)
        confirm: Must be True to execute (safety)

    Returns:
        {deleted: bool, id: str, cascade: {chunks, events, entities}}

    Examples:
        forget(id="art_abc123", confirm=True)
    """
    try:
        # Safety check
        if not confirm:
            return {
                "error": "Must set confirm=True to delete",
                "hint": "This is a safety measure. Set confirm=True to proceed with deletion."
            }

        # Validate ID format (Decision 6: Single ID Family)
        if id.startswith("evt_"):
            # Get source artifact for guidance (Decision 4: Guide-to-Source)
            if pg_client:
                try:
                    # Extract UUID from evt_ prefix
                    event_uuid = id.replace("evt_", "")
                    result = await pg_client.fetch_one(
                        "SELECT artifact_uid FROM semantic_event WHERE event_id = $1",
                        event_uuid
                    )
                    if result:
                        source_uid = result["artifact_uid"]
                        # Convert uid_ to art_ format
                        source_art_id = f"art_{source_uid.replace('uid_', '')}"
                        return {
                            "error": f"Events are derived data. Delete source artifact '{source_art_id}' instead.",
                            "source_artifact_id": source_art_id,
                            "deleted": False
                        }
                except Exception as e:
                    logger.warning(f"V6 forget: Failed to lookup event source: {e}")

            return {
                "error": "Events are derived data. Delete the source artifact instead.",
                "deleted": False
            }

        if not id.startswith("art_"):
            return {"error": f"Invalid ID format. Use art_xxx. Got: {id}", "deleted": False}

        client = chroma_manager.get_client()

        # Check if content exists
        existing = get_content_by_id(client, id)
        if not existing:
            return {"error": f"Content not found: {id}", "deleted": False}

        # Delete from V6 content collection and chunks
        chroma_deleted = delete_v5_content_cascade(client, id)

        # Delete events and entities from PostgreSQL
        events_deleted = 0
        entities_deleted = 0

        if pg_client:
            try:
                content_hash = id.replace("art_", "")
                artifact_uid = f"uid_{content_hash}"

                # Delete events and related data
                # First, get event IDs for this artifact
                event_rows = await pg_client.fetch_all(
                    "SELECT event_id FROM semantic_event WHERE artifact_uid = $1",
                    artifact_uid
                )
                event_ids = [row["event_id"] for row in event_rows]

                if event_ids:
                    # Delete event_evidence
                    placeholders = ", ".join(f"${i+1}" for i in range(len(event_ids)))
                    await pg_client.execute(
                        f"DELETE FROM event_evidence WHERE event_id IN ({placeholders})",
                        *event_ids
                    )

                    # Delete event_actor
                    await pg_client.execute(
                        f"DELETE FROM event_actor WHERE event_id IN ({placeholders})",
                        *event_ids
                    )

                    # Delete event_subject
                    await pg_client.execute(
                        f"DELETE FROM event_subject WHERE event_id IN ({placeholders})",
                        *event_ids
                    )

                    # Delete semantic_event
                    result = await pg_client.execute(
                        f"DELETE FROM semantic_event WHERE event_id IN ({placeholders})",
                        *event_ids
                    )
                    events_deleted = len(event_ids)

                # Delete entity_mention for this artifact
                mention_result = await pg_client.execute(
                    "DELETE FROM entity_mention WHERE artifact_uid = $1",
                    artifact_uid
                )

                # Delete artifact_revision
                await pg_client.execute(
                    "DELETE FROM artifact_revision WHERE artifact_uid = $1",
                    artifact_uid
                )

                # Delete event_jobs
                await pg_client.execute(
                    "DELETE FROM event_jobs WHERE artifact_uid = $1",
                    artifact_uid
                )

                logger.info(f"V6 forget: Deleted Postgres data for {artifact_uid}")

            except Exception as e:
                logger.warning(f"V6 forget: Failed to delete Postgres data: {e}")

        logger.info(f"V6 forget: Deleted {id} (content={chroma_deleted['content']}, chunks={chroma_deleted['chunks']}, events={events_deleted})")

        return {
            "deleted": True,
            "id": id,
            "cascade": {
                "chunks": chroma_deleted["chunks"],
                "events": events_deleted,
                "entities": entities_deleted
            }
        }

    except Exception as e:
        logger.error(f"V6 forget error: {e}", exc_info=True)
        return {"error": f"Delete failed: {str(e)}", "deleted": False}


@mcp.tool()
async def status(
    artifact_id: Optional[str] = None,
) -> dict:
    """
    Get system health and statistics.

    Args:
        artifact_id: Optional - check extraction job status for specific artifact

    Returns:
        {
            version: str,
            environment: str,
            healthy: bool,
            services: {...},
            counts: {...},
            pending_jobs: int,
            job_status: {...}  # Only if artifact_id provided
        }
    """
    try:
        result = {
            "version": __version__,
            "environment": os.getenv("ENVIRONMENT", "development"),
            "healthy": True,
            "services": {},
            "counts": {},
            "pending_jobs": 0
        }

        # ChromaDB health
        if chroma_manager:
            chroma_health = chroma_manager.health_check()
            result["services"]["chromadb"] = {
                "status": chroma_health.get("status", "unknown"),
                "latency_ms": chroma_health.get("latency_ms"),
                "collections": ["content", "chunks"]  # V6 collections
            }
            if chroma_health.get("status") != "healthy":
                result["healthy"] = False

            # Get V6 collection counts
            try:
                client = chroma_manager.get_client()
                content_col = get_content_collection(client)
                chunks_col = get_chunks_collection(client)
                result["counts"]["content"] = content_col.count()
                result["counts"]["chunks"] = chunks_col.count()
            except Exception as e:
                logger.warning(f"V6 status: Failed to get collection counts: {e}")
                result["counts"]["content"] = 0
                result["counts"]["chunks"] = 0

        # Postgres health and counts
        if pg_client:
            try:
                pg_health = await pg_client.health_check()
                result["services"]["postgres"] = {
                    "status": pg_health.get("status", "unknown"),
                    "pool_size": pg_health.get("pool_size", 0)
                }
                if pg_health.get("status") != "healthy":
                    result["healthy"] = False

                # Get Postgres table counts
                artifact_count = await pg_client.fetch_one("SELECT COUNT(*) as count FROM artifact_revision")
                event_count = await pg_client.fetch_one("SELECT COUNT(*) as count FROM semantic_event")
                entity_count = await pg_client.fetch_one("SELECT COUNT(*) as count FROM entity")
                pending_count = await pg_client.fetch_one("SELECT COUNT(*) as count FROM event_jobs WHERE status = 'PENDING'")

                result["counts"]["artifacts"] = artifact_count["count"] if artifact_count else 0
                result["counts"]["events"] = event_count["count"] if event_count else 0
                result["counts"]["entities"] = entity_count["count"] if entity_count else 0
                result["pending_jobs"] = pending_count["count"] if pending_count else 0

            except Exception as e:
                logger.warning(f"V6 status: Postgres error: {e}")
                result["services"]["postgres"] = {"status": "error", "error": str(e)}
                result["healthy"] = False
        else:
            result["services"]["postgres"] = {"status": "unavailable"}

        # OpenAI health
        if embedding_service:
            embed_health = embedding_service.health_check()
            result["services"]["openai"] = {
                "status": embed_health.get("status", "unknown"),
                "model": config.openai_embed_model if config else "text-embedding-3-large"
            }
            if embed_health.get("status") != "healthy":
                result["healthy"] = False

        # Graph expansion status (V6 uses Postgres joins, not AGE)
        result["services"]["graph_expansion"] = {
            "status": "available" if pg_client else "unavailable",
            "backend": "postgres_joins"  # V6: no AGE dependency
        }

        # Job status for specific artifact if requested
        if artifact_id and pg_client and job_queue_service:
            try:
                resolved_uid = await resolve_artifact_uid(artifact_id)
                if resolved_uid:
                    job_status_result = await job_queue_service.get_job_status(
                        artifact_uid=resolved_uid
                    )
                    if job_status_result:
                        result["job_status"] = job_status_result
            except Exception as e:
                logger.warning(f"V6 status: Failed to get job status: {e}")

        return result

    except Exception as e:
        logger.error(f"V6 status error: {e}", exc_info=True)
        return {
            "version": __version__,
            "environment": os.getenv("ENVIRONMENT", "development"),
            "healthy": False,
            "error": str(e)
        }


# ============================================================================
# APPLICATION LIFECYCLE
# ============================================================================

session_manager: Optional[StreamableHTTPSessionManager] = None


@asynccontextmanager
async def lifespan(app):
    """Application lifespan - startup/shutdown."""
    global config, embedding_service, chunking_service, retrieval_service
    global privacy_service, chroma_manager, session_manager
    global pg_client, job_queue_service

    logger.info("=" * 60)
    logger.info(f"Starting MCP Memory Server v{__version__}")
    logger.info("=" * 60)

    try:
        # Load and validate configuration
        config = load_config()
        validate_config(config)

        logger.info(f"Configuration loaded:")
        logger.info(f"  OpenAI Model: {config.openai_embed_model} ({config.openai_embed_dims} dims)")
        logger.info(f"  ChromaDB: {config.chroma_host}:{config.chroma_port}")
        logger.info(f"  MCP Port: {config.mcp_port}")
        logger.info(f"  Chunking: max={config.single_piece_max_tokens}, target={config.chunk_target_tokens}, overlap={config.chunk_overlap_tokens}")

        # Initialize ChromaDB manager
        logger.info("Initializing ChromaDB...")
        chroma_manager = ChromaClientManager(
            host=config.chroma_host,
            port=config.chroma_port
        )

        chroma_health = chroma_manager.health_check()
        if chroma_health["status"] != "healthy":
            raise RuntimeError(f"ChromaDB unhealthy: {chroma_health.get('error')}")

        logger.info(f"  ChromaDB: OK (latency={chroma_health.get('latency_ms')}ms)")

        # Initialize embedding service
        logger.info("Initializing EmbeddingService...")
        embedding_service = EmbeddingService(
            api_key=config.openai_api_key,
            model=config.openai_embed_model,
            dimensions=config.openai_embed_dims,
            timeout=config.openai_timeout,
            max_retries=config.openai_max_retries,
            batch_size=config.openai_batch_size
        )

        # Health check embedding service
        embed_health = embedding_service.health_check()
        if embed_health["status"] != "healthy":
            raise RuntimeError(f"OpenAI API unhealthy: {embed_health.get('error')}")

        logger.info(f"  OpenAI API: OK (latency={embed_health.get('api_latency_ms')}ms)")

        # Initialize chunking service
        logger.info("Initializing ChunkingService...")
        chunking_service = ChunkingService(
            single_piece_max=config.single_piece_max_tokens,
            chunk_target=config.chunk_target_tokens,
            chunk_overlap=config.chunk_overlap_tokens
        )
        logger.info("  ChunkingService: OK")

        # Initialize privacy service (placeholder)
        logger.info("Initializing PrivacyFilterService...")
        privacy_service = PrivacyFilterService()
        logger.info("  PrivacyFilterService: OK (v2 placeholder)")

        # V3: Initialize Postgres client
        logger.info("Initializing PostgreSQL (V3/V4)...")
        try:
            pg_client = PostgresClient(
                dsn=config.events_db_dsn,
                min_pool_size=config.postgres_pool_min,
                max_pool_size=config.postgres_pool_max
            )
            await pg_client.connect()

            pg_health = await pg_client.health_check()
            if pg_health["status"] != "healthy":
                raise RuntimeError(f"Postgres unhealthy: {pg_health.get('error')}")

            logger.info(f"  PostgreSQL: OK (pool {config.postgres_pool_min}-{config.postgres_pool_max})")

            # Initialize job queue service
            job_queue_service = JobQueueService(pg_client, config.event_max_attempts)
            logger.info(f"  JobQueueService: OK (max attempts={config.event_max_attempts})")

        except Exception as e:
            logger.warning(f"  PostgreSQL: UNAVAILABLE ({e}) - event features disabled")
            pg_client = None
            job_queue_service = None

        # Initialize retrieval service (graph expansion via SQL joins)
        logger.info("Initializing RetrievalService...")
        retrieval_service = RetrievalService(
            embedding_service=embedding_service,
            chunking_service=chunking_service,
            chroma_client=chroma_manager.get_client(),
            k=config.rrf_constant,
            pg_client=pg_client
        )
        logger.info(f"  RetrievalService: OK (graph_expand={'enabled' if pg_client else 'disabled'})")

        # Create session manager
        session_manager = StreamableHTTPSessionManager(
            app=mcp._mcp_server,
            json_response=False,
            stateless=False,
        )

        # Run session manager
        async with session_manager.run():
            logger.info("=" * 60)
            logger.info(f"MCP Memory Server v{__version__} ready at http://0.0.0.0:{config.mcp_port}/mcp/")
            logger.info("=" * 60)
            yield

    except Exception as e:
        logger.error(f"Failed to start server: {e}", exc_info=True)
        raise

    logger.info(f"MCP Memory Server v{__version__} stopped")


async def health(request):
    """Health check endpoint."""
    health_data = {
        "status": "ok",
        "service": "mcp-memory",
        "version": __version__,
        "environment": os.getenv("ENVIRONMENT", "prod")
    }

    # Add detailed checks if services initialized
    if chroma_manager:
        health_data["chromadb"] = chroma_manager.health_check()

    if embedding_service:
        health_data["openai"] = embedding_service.health_check()

    # V6: Postgres for events and graph expansion
    if pg_client:
        health_data["postgres"] = await pg_client.health_check()
        health_data["graph_expand_enabled"] = True
    else:
        health_data["graph_expand_enabled"] = False

    return JSONResponse(health_data)

async def mcp_slash_redirect(request):
    """
    Handle /mcp without trailing slash.

    Some MCP clients (notably Claude Desktop / Claude connector validation) POST to
    `/mcp` even when configured with `/mcp/`. Starlette's Mount-based slash redirect
    can emit an absolute Location with an `http://` scheme when running behind
    proxies (e.g., ngrok) unless proxy headers are honored.

    We redirect *relatively* to `/mcp/` so the client keeps the original scheme/host.
    """
    return RedirectResponse(url="/mcp/", status_code=307)


class MCPHandler:
    """ASGI handler for MCP requests."""

    async def __call__(self, scope, receive, send):
        if session_manager:
            await session_manager.handle_request(scope, receive, send)
        else:
            response = JSONResponse({"error": "Server not ready"}, status_code=503)
            await response(scope, receive, send)


# Create Starlette app with MCP mounted
app = Starlette(
    debug=os.getenv("LOG_LEVEL") == "DEBUG",
    middleware=[
        # Honor X-Forwarded-Proto/Host from reverse proxies (e.g., ngrok) so any
        # generated URLs preserve https instead of downgrading to http.
        Middleware(ProxyHeadersMiddleware, trusted_hosts="*"),
    ],
    routes=[
        Route("/", health),
        Route("/health", health),
        # Avoid proxy-induced https->http redirects by handling /mcp explicitly
        Route("/mcp", mcp_slash_redirect, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Mount("/mcp", app=MCPHandler()),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    # Setup basic logging for startup
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Load config to get port
    try:
        cfg = load_config()
        port = cfg.mcp_port
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        port = 3000

    logger.info(f"Starting MCP Memory Server v{__version__} on port {port}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=os.getenv("LOG_LEVEL", "INFO").lower(),
    )
