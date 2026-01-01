"""
MCP Memory Server v5.0 - Streamable HTTP Transport

A Model Context Protocol server that provides persistent memory and artifact storage
with OpenAI embeddings, token-window chunking, hybrid retrieval, semantic event extraction,
and graph-backed context expansion.

V5 Features (Simplified Interface):
- 4 new tools: remember(), recall(), forget(), status()
- Unified content storage (content + chunks collections)
- Content-based ID generation (art_ + SHA256[:12])
- Idempotent deduplication by content hash
- Conversation turn event gating (< 100 tokens skip extraction)
- Graph expansion via Postgres joins (no AGE dependency)

V4 Features:
- Graph-backed context expansion (Apache AGE)
- Entity resolution with deduplication
- 1-hop graph traversal for related context

V3 Features:
- Semantic event extraction from artifacts using LLM
- PostgreSQL storage for events, revisions, and job queue
- Async event worker for background processing
- Evidence linking to source text

Usage:
    python server.py

Configuration via .env file (see .env.example)
"""

# Version and build info
__version__ = "5.0.0-alpha"

import os
import logging
import hashlib
from datetime import datetime, date
from uuid import uuid4
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
    get_memory_collection,
    get_history_collection,
    get_artifacts_collection,
    get_artifact_chunks_collection,
    get_artifact_by_source,
    get_chunks_by_artifact,
    delete_artifact_cascade,
    # V5 collections
    get_content_collection,
    get_chunks_collection,
    get_content_by_id,
    get_v5_chunks_by_content,
    delete_v5_content_cascade
)
from storage.models import Chunk
from utils.errors import (
    ValidationError,
    EmbeddingError,
    StorageError,
    NotFoundError
)

# V3: Postgres and event extraction imports
from storage.postgres_client import PostgresClient
from services.job_queue_service import JobQueueService
from tools.event_tools import event_search, event_get, event_list_for_revision

# V5: GraphService import removed - graph expansion uses Postgres SQL joins
# Legacy import commented out for reference:
# from services.graph_service import GraphService

# Setup logging
logger = logging.getLogger("mcp-memory")

# ============================================================================
# V4: hybrid_search expand_options (static capability metadata)
# ============================================================================

HYBRID_SEARCH_EXPAND_OPTIONS = [
    {
        "name": "include_memory",
        "type": "boolean",
        "default": False,
        "description": "Also search durable memories (preferences/facts) and include them in results.",
        "effect": "Adds Chroma 'memories' collection to the search and merges with RRF.",
    },
    {
        "name": "expand_neighbors",
        "type": "boolean",
        "default": False,
        "description": "For chunk hits, include ±1 adjacent chunks to provide more surrounding context.",
        "effect": "Returns combined chunk text separated by [CHUNK BOUNDARY] markers.",
    },
    {
        "name": "include_events",
        "type": "boolean",
        "default": True,
        "description": "Include semantic events from PostgreSQL in the merged results.",
        "effect": "Adds Postgres event search (FTS) results to the output.",
    },
    {
        "name": "graph_expand",
        "type": "boolean",
        "default": True,
        "description": "Add a related context pack (1 hop) using the graph to surface connected events and entities.",
        "effect": "Populates related_context[] and entities[].",
    },
    {
        "name": "graph_filters",
        "type": "string[]",
        "default": ["Decision", "Commitment", "QualityRisk"],
        "description": "Limit graph-expanded events to these categories.",
        "constraints": "Only valid when graph_expand=true.",
    },
    {
        "name": "graph_budget",
        "type": "integer",
        "default": 10,
        "description": "Maximum number of related context items to add.",
        "constraints": "Valid range: 0–50. Only used when graph_expand=true.",
    },
    {
        "name": "include_entities",
        "type": "boolean",
        "default": True,
        "description": "Include canonical entities involved in primary + related results.",
        "constraints": "Only meaningful when graph_expand=true.",
    },
    {
        "name": "include_revision_diff",
        "type": "boolean",
        "default": False,
        "description": "If the top hit maps to an artifact revision, include a compact diff vs the previous revision.",
        "constraints": "Optional feature; only used when graph_expand=true and a previous revision exists.",
    },
]

# Create FastMCP server
mcp = FastMCP(f"MCP Memory v{__version__}")

# Global services (initialized in lifespan)
config = None
embedding_service: Optional[EmbeddingService] = None
chunking_service: Optional[ChunkingService] = None
retrieval_service: Optional[RetrievalService] = None
privacy_service: Optional[PrivacyFilterService] = None
chroma_manager: Optional[ChromaClientManager] = None

# V3: Postgres and job queue
pg_client: Optional[PostgresClient] = None
job_queue_service: Optional[JobQueueService] = None

# V5: Graph service disabled (graph expansion uses Postgres SQL joins)
graph_service: Optional[Any] = None  # Legacy type, kept for backward compatibility


# ============================================================================
# EXISTING TOOLS (Updated for v2)
# ============================================================================

@mcp.tool()
def memory_store(
    content: str,
    type: str,
    confidence: float,
    conversation_id: Optional[str] = None
) -> str:
    """
    Store a memory for long-term recall.

    Args:
        content: The memory content (e.g., 'User prefers dark mode')
        type: Category - one of: preference, fact, project, decision
        confidence: How confident (0.0-1.0) this is worth remembering
        conversation_id: Optional conversation context
    """
    try:
        # Validate inputs
        if not content or len(content) > 10000:
            return "Error: Content must be between 1 and 10,000 characters"

        if type not in ["preference", "fact", "project", "decision"]:
            return f"Error: Invalid type '{type}'. Must be one of: preference, fact, project, decision"

        if not 0.0 <= confidence <= 1.0:
            return "Error: Confidence must be between 0.0 and 1.0"

        # Generate embedding
        embedding = embedding_service.generate_embedding(content)

        # Generate memory ID
        memory_id = f"mem_{uuid4().hex[:12]}"

        # Get token count
        token_count = chunking_service.count_tokens(content)

        # Store in memory collection
        collection = get_memory_collection(chroma_manager.get_client())

        metadata = {
            "type": type,
            "confidence": confidence,
            "ts": datetime.utcnow().isoformat() + "Z",
            "embedding_provider": "openai",
            "embedding_model": config.openai_embed_model,
            "embedding_dimensions": config.openai_embed_dims,
            "token_count": token_count
        }

        if conversation_id:
            metadata["conversation_id"] = conversation_id

        collection.add(
            ids=[memory_id],
            documents=[content],
            embeddings=[embedding],
            metadatas=[metadata]
        )

        logger.info(f"Stored memory {memory_id}: type={type}, conf={confidence}")

        return f"Stored memory [{memory_id}]: {content[:60]}..."

    except ValidationError as e:
        return f"Validation error: {e}"
    except EmbeddingError as e:
        return f"Failed to generate embedding: {e}"
    except Exception as e:
        logger.error(f"memory_store error: {e}", exc_info=True)
        return f"Failed to store memory: {str(e)}"


@mcp.tool()
def memory_search(
    query: str,
    limit: int = 5,
    min_confidence: float = 0.0
) -> str:
    """
    Search stored facts and memories (not documents/events).

    Memories are explicit facts stored via memory_store (preferences, facts,
    decisions). For document content and events, use hybrid_search instead.

    Args:
        query: What to search for (e.g., 'user preferences')
        limit: Maximum results (1-20)
        min_confidence: Minimum confidence threshold (0.0-1.0)
    """
    try:
        # Validate inputs
        if not query or len(query) > 500:
            return "Error: Query must be between 1 and 500 characters"

        if not 1 <= limit <= 20:
            return "Error: Limit must be between 1 and 20"

        # Generate query embedding
        query_embedding = embedding_service.generate_embedding(query)

        # Search memory collection
        collection = get_memory_collection(chroma_manager.get_client())

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit
        )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        ids = results.get("ids", [[]])[0]

        if not docs:
            return "No memories found."

        # Format output
        output = []
        for doc, meta, mid in zip(docs, metas, ids):
            conf = meta.get("confidence", 1.0) if meta else 1.0
            if conf >= min_confidence:
                mtype = meta.get("type", "?") if meta else "?"
                output.append(f"[{mid}] ({mtype}, conf={conf}): {doc}")

        if not output:
            return f"No memories found with confidence >= {min_confidence}"

        return "\n".join(output)

    except EmbeddingError as e:
        return f"Failed to generate query embedding: {e}"
    except Exception as e:
        logger.error(f"memory_search error: {e}", exc_info=True)
        return f"Search failed: {str(e)}"


@mcp.tool()
def memory_list(
    type: Optional[str] = None,
    limit: int = 20
) -> str:
    """
    List all stored memories.

    Args:
        type: Filter by type (preference, fact, project, decision)
        limit: Maximum results (1-100)
    """
    try:
        if limit < 1 or limit > 100:
            return "Error: Limit must be between 1 and 100"

        collection = get_memory_collection(chroma_manager.get_client())
        results = collection.get(limit=limit)

        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])

        if not docs:
            return "No memories stored yet."

        output = []
        for doc, meta, mid in zip(docs, metas, ids):
            mtype = meta.get("type", "?") if meta else "?"
            conf = meta.get("confidence", "?") if meta else "?"

            if type and mtype != type:
                continue

            output.append(f"[{mid}] ({mtype}, conf={conf}): {doc[:80]}")

        if not output:
            return f"No memories found with type '{type}'"

        return f"Found {len(output)} memories:\n" + "\n".join(output)

    except Exception as e:
        logger.error(f"memory_list error: {e}", exc_info=True)
        return f"Failed to list memories: {str(e)}"


@mcp.tool()
def memory_delete(memory_id: str) -> str:
    """
    Delete a specific memory by ID.

    Args:
        memory_id: The ID of the memory to delete (e.g., mem_abc123)
    """
    try:
        if not memory_id.startswith("mem_"):
            return "Error: Invalid memory_id format. Must start with 'mem_'"

        collection = get_memory_collection(chroma_manager.get_client())
        collection.delete(ids=[memory_id])

        logger.info(f"Deleted memory {memory_id}")
        return f"Deleted memory: {memory_id}"

    except Exception as e:
        logger.error(f"memory_delete error: {e}", exc_info=True)
        return f"Failed to delete memory: {str(e)}"


@mcp.tool()
def history_append(
    conversation_id: str,
    role: str,
    content: str,
    turn_index: int
) -> str:
    """
    Append a message to conversation history.

    Args:
        conversation_id: Unique conversation identifier
        role: Who sent it (user, assistant, system)
        content: The message content
        turn_index: Turn number (0, 1, 2, ...)
    """
    try:
        # Validate inputs
        if not conversation_id or len(conversation_id) > 100:
            return "Error: conversation_id must be between 1 and 100 characters"

        if role not in ["user", "assistant", "system"]:
            return f"Error: Invalid role '{role}'. Must be one of: user, assistant, system"

        if not content or len(content) > 50000:
            return "Error: Content must be between 1 and 50,000 characters"

        if turn_index < 0:
            return "Error: turn_index must be >= 0"

        # Generate embedding
        embedding = embedding_service.generate_embedding(f"{role}: {content}")

        # Generate document ID
        doc_id = f"{conversation_id}_turn_{turn_index}"

        # Get token count
        token_count = chunking_service.count_tokens(content)

        # Store in history collection
        collection = get_history_collection(chroma_manager.get_client())

        collection.add(
            ids=[doc_id],
            documents=[f"{role}: {content}"],
            embeddings=[embedding],
            metadatas=[{
                "conversation_id": conversation_id,
                "role": role,
                "turn_index": turn_index,
                "ts": datetime.utcnow().isoformat() + "Z",
                "embedding_provider": "openai",
                "embedding_model": config.openai_embed_model,
                "embedding_dimensions": config.openai_embed_dims,
                "token_count": token_count
            }]
        )

        logger.info(f"Appended turn {turn_index} to {conversation_id}")
        return f"Appended turn {turn_index} to {conversation_id}"

    except EmbeddingError as e:
        return f"Failed to generate embedding: {e}"
    except Exception as e:
        logger.error(f"history_append error: {e}", exc_info=True)
        return f"Failed to append history: {str(e)}"


@mcp.tool()
def history_get(
    conversation_id: str,
    limit: int = 16
) -> str:
    """
    Get recent conversation history.

    Args:
        conversation_id: Conversation to retrieve
        limit: Number of recent turns (1-50)
    """
    try:
        if not conversation_id:
            return "Error: conversation_id is required"

        if limit < 1 or limit > 50:
            return "Error: Limit must be between 1 and 50"

        collection = get_history_collection(chroma_manager.get_client())

        results = collection.get(
            where={"conversation_id": conversation_id},
            limit=200
        )

        docs = results.get("documents", [])
        metas = results.get("metadatas", [])

        if not docs:
            return "No history found for this conversation."

        # Sort by turn_index
        turns = list(zip(docs, metas))
        turns.sort(key=lambda x: x[1].get("turn_index", 0) if x[1] else 0)

        # Return last N turns
        output = [doc for doc, _ in turns[-limit:]]
        return "\n".join(output)

    except Exception as e:
        logger.error(f"history_get error: {e}", exc_info=True)
        return f"Failed to get history: {str(e)}"


# ============================================================================
# NEW TOOLS (v2)
# ============================================================================

def parse_date_string(date_str: Optional[str]) -> Optional[date]:
    """Convert a date string (YYYY-MM-DD) to a Python date object for Postgres."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


@mcp.tool()
async def artifact_ingest(
    artifact_type: str,
    source_system: str,
    content: str,
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    title: Optional[str] = None,
    author: Optional[str] = None,
    participants: Optional[List[str]] = None,
    ts: Optional[str] = None,
    sensitivity: str = "normal",
    visibility_scope: str = "me",
    retention_policy: str = "forever",
    # Source metadata for authority/credibility reasoning
    document_date: Optional[str] = None,
    source_type: Optional[str] = None,
    document_status: Optional[str] = None,
    author_title: Optional[str] = None,
    distribution_scope: Optional[str] = None
) -> dict:
    """
    Ingest documents, emails, chats with automatic chunking.

    Args:
        artifact_type: Source type (email, doc, chat, transcript, note)
        source_system: Origin system (gmail, slack, drive, manual)
        content: Full text content
        source_id: Unique ID in source system (for deduplication)
        source_url: Link to original
        title: Subject line or title
        author: Primary author
        participants: List of all participants
        ts: Event timestamp (ISO8601)
        sensitivity: Privacy level (normal, sensitive, highly_sensitive)
        visibility_scope: Who can see (me, team, org, custom)
        retention_policy: Retention rule (forever, 1y, until_resolved, custom)

        Source metadata for reasoning (all optional):
        document_date: Actual date of document/meeting (YYYY-MM-DD), not ingestion date
        source_type: email, slack, meeting_notes, document, policy, contract, chat, transcript, wiki, ticket
        document_status: draft, final, approved, superseded, archived
        author_title: Role/title of author (e.g., "Engineering Manager", "CEO")
        distribution_scope: private, team, department, company, public
    """
    try:
        # Validate inputs
        if artifact_type not in ["email", "doc", "chat", "transcript", "note"]:
            return {"error": f"Invalid artifact_type: {artifact_type}. Must be one of: email, doc, chat, transcript, note"}

        if not content or len(content) > 10000000:
            return {"error": "Content must be between 1 and 10,000,000 characters"}

        if sensitivity not in ["normal", "sensitive", "highly_sensitive"]:
            return {"error": f"Invalid sensitivity: {sensitivity}"}

        if visibility_scope not in ["me", "team", "org", "custom"]:
            return {"error": f"Invalid visibility_scope: {visibility_scope}"}

        # Validate source metadata fields
        valid_source_types = ["email", "slack", "meeting_notes", "document", "policy", "contract", "chat", "transcript", "wiki", "ticket"]
        if source_type and source_type not in valid_source_types:
            return {"error": f"Invalid source_type: {source_type}. Must be one of: {', '.join(valid_source_types)}"}

        valid_doc_statuses = ["draft", "final", "approved", "superseded", "archived"]
        if document_status and document_status not in valid_doc_statuses:
            return {"error": f"Invalid document_status: {document_status}. Must be one of: {', '.join(valid_doc_statuses)}"}

        valid_distribution_scopes = ["private", "team", "department", "company", "public"]
        if distribution_scope and distribution_scope not in valid_distribution_scopes:
            return {"error": f"Invalid distribution_scope: {distribution_scope}. Must be one of: {', '.join(valid_distribution_scopes)}"}

        # Compute content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Generate artifact_id
        if source_id:
            artifact_id = "art_" + hashlib.sha256(
                f"{source_system}:{source_id}".encode()
            ).hexdigest()[:8]
        else:
            artifact_id = "art_" + content_hash[:8]

        # Check for duplicate
        existing = get_artifact_by_source(
            chroma_manager.get_client(),
            source_system,
            source_id
        ) if source_id else None

        if existing:
            existing_hash = existing.get("metadata", {}).get("content_hash")
            if existing_hash == content_hash:
                # No changes - return existing
                #
                # V3/V4 BACKFILL:
                # If this artifact was ingested before Postgres was configured, it can exist in Chroma
                # without an artifact_revision row. That prevents event extraction, event_search, and
                # graph expansion from working for this artifact.
                #
                # Re-ingesting an unchanged artifact should backfill Postgres metadata and enqueue
                # extraction if missing (idempotent).
                logger.info(f"Artifact {artifact_id} unchanged, skipping Chroma ingestion")

                artifact_uid = "uid_" + hashlib.sha256(
                    f"{source_system}:{source_id}".encode()
                ).hexdigest()[:16] if source_id else "uid_" + uuid4().hex[:16]
                revision_id = "rev_" + content_hash[:16]

                job_id = None
                job_status = None

                if pg_client and job_queue_service:
                    try:
                        existing_meta = existing.get("metadata", {}) or {}

                        def _norm_enum(value: Optional[str]) -> Optional[str]:
                            """Normalize empty strings to None for Postgres CHECK-constrained columns."""
                            if value is None:
                                return None
                            v = str(value).strip()
                            return v if v else None

                        # Prefer metadata persisted in Chroma for backfill correctness
                        is_chunked = bool(existing_meta.get("is_chunked", False))
                        chunk_count = int(existing_meta.get("num_chunks", 0) or 0)
                        token_count = int(existing_meta.get("token_count", 0) or chunking_service.count_tokens(content))
                        title_val = title if title is not None else existing_meta.get("title", "") or ""

                        # Check whether revision exists in Postgres
                        rev_row = None
                        try:
                            rev_row = await pg_client.fetch_one(
                                """
                                SELECT 1
                                FROM artifact_revision
                                WHERE artifact_uid = $1 AND revision_id = $2
                                LIMIT 1
                                """,
                                artifact_uid,
                                revision_id
                            )
                        except Exception:
                            rev_row = None

                        if not rev_row:
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
                                        artifact_type,
                                        source_system,
                                        source_id or "",
                                        content_hash,
                                        token_count,
                                        is_chunked,
                                        chunk_count,
                                    )
                                )
                            ])

                        # Enqueue extraction (idempotent)
                        job_uuid = await job_queue_service.enqueue_job(artifact_uid, revision_id)
                        if job_uuid:
                            job_id = str(job_uuid)
                            job_status = "PENDING"

                    except Exception as e:
                        logger.warning(f"V3 backfill failed for unchanged artifact {artifact_id}: {e}")

                return {
                    "artifact_id": artifact_id,
                    "artifact_uid": artifact_uid,
                    "revision_id": revision_id,
                    "is_chunked": existing.get("metadata", {}).get("is_chunked", False),
                    "num_chunks": existing.get("metadata", {}).get("num_chunks", 0),
                    "stored_ids": [artifact_id],
                    "status": "unchanged",
                    "job_id": job_id,
                    "job_status": job_status
                }
            else:
                # Content changed - delete old version
                logger.info(f"Artifact {artifact_id} content changed, deleting old version")
                delete_artifact_cascade(chroma_manager.get_client(), artifact_id)

        # Decide: chunk or store whole
        should_chunk, token_count = chunking_service.should_chunk(content)

        # Common metadata
        base_metadata = {
            "artifact_type": artifact_type,
            "source_system": source_system,
            "source_id": source_id or "",
            "source_url": source_url or "",
            "title": title or "",
            "author": author or "",
            "participants": ",".join(participants) if participants else "",
            "content_hash": content_hash,
            "token_count": token_count,
            "ts": ts or datetime.utcnow().isoformat() + "Z",
            "sensitivity": sensitivity,
            "visibility_scope": visibility_scope,
            "retention_policy": retention_policy,
            "embedding_provider": "openai",
            "embedding_model": config.openai_embed_model,
            "embedding_dimensions": config.openai_embed_dims,
            "ingested_at": datetime.utcnow().isoformat() + "Z",
            # Source metadata for authority/credibility reasoning
            "document_date": document_date or "",
            "source_type": source_type or "",
            "document_status": document_status or "",
            "author_title": author_title or "",
            "distribution_scope": distribution_scope or ""
        }

        # V3: Generate stable artifact_uid and revision_id
        if source_id:
            artifact_uid = "uid_" + hashlib.sha256(
                f"{source_system}:{source_id}".encode()
            ).hexdigest()[:16]
        else:
            artifact_uid = "uid_" + uuid4().hex[:16]

        revision_id = "rev_" + content_hash[:16]

        if not should_chunk:
            # Store as single artifact
            logger.info(f"Ingesting unchunked artifact {artifact_id}: {token_count} tokens")

            embedding = embedding_service.generate_embedding(content)

            artifacts_collection = get_artifacts_collection(chroma_manager.get_client())

            artifacts_collection.add(
                ids=[artifact_id],
                documents=[content],
                embeddings=[embedding],
                metadatas=[{
                    **base_metadata,
                    "is_chunked": False,
                    "num_chunks": 0
                }]
            )

            # V3: Write to Postgres and enqueue job
            job_id = None
            job_status = None
            if pg_client and job_queue_service:
                try:
                    # Write revision to Postgres
                    await pg_client.transaction([
                        # Mark old revisions as not latest
                        (
                            "UPDATE artifact_revision SET is_latest = false WHERE artifact_uid = $1 AND is_latest = true",
                            (artifact_uid,)
                        ),
                        # Insert new revision (include artifact_id for worker to fetch from ChromaDB)
                        (
                            """INSERT INTO artifact_revision
                               (artifact_uid, revision_id, artifact_id, artifact_type, source_system, source_id, content_hash, token_count, is_chunked, chunk_count)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                               ON CONFLICT (artifact_uid, revision_id) DO NOTHING""",
                            (artifact_uid, revision_id, artifact_id, artifact_type, source_system, source_id or "", content_hash, token_count, False, 0)
                        )
                    ])

                    # Enqueue event extraction job
                    job_uuid = await job_queue_service.enqueue_job(artifact_uid, revision_id)
                    if job_uuid:
                        job_id = str(job_uuid)
                        job_status = "PENDING"
                        logger.info(f"V3: Enqueued job {job_id} for {artifact_uid}/{revision_id}")

                except Exception as e:
                    logger.warning(f"V3: Failed to write to Postgres: {e}")

            return {
                "artifact_id": artifact_id,
                "artifact_uid": artifact_uid,
                "revision_id": revision_id,
                "is_chunked": False,
                "num_chunks": 0,
                "stored_ids": [artifact_id],
                "job_id": job_id,
                "job_status": job_status
            }

        else:
            # Chunk and store
            logger.info(f"Ingesting chunked artifact {artifact_id}: {token_count} tokens")

            chunks = chunking_service.chunk_text(content, artifact_id)

            # TWO-PHASE ATOMIC WRITE
            # Phase 1: Generate ALL embeddings first
            logger.info(f"Phase 1: Generating embeddings for {len(chunks)} chunks")
            chunk_contents = [chunk.content for chunk in chunks]

            try:
                embeddings = embedding_service.generate_embeddings_batch(chunk_contents)
            except EmbeddingError as e:
                logger.error(f"Two-phase write aborted: {e}")
                return {"error": f"Failed to generate embeddings: {e}"}

            # Phase 2: Write to DB (only if ALL embeddings succeeded)
            logger.info(f"Phase 2: Writing artifact and {len(chunks)} chunks to database")

            artifacts_collection = get_artifacts_collection(chroma_manager.get_client())
            chunks_collection = get_artifact_chunks_collection(chroma_manager.get_client())

            # Store artifact metadata (with placeholder embedding for chunked docs)
            # Generate embedding for title/metadata summary to enable artifact-level search
            artifact_summary = f"{title or 'Untitled'}: {artifact_type} from {source_system}"
            artifact_embedding = embedding_service.generate_embedding(artifact_summary)

            artifacts_collection.add(
                ids=[artifact_id],
                documents=[artifact_summary],
                embeddings=[artifact_embedding],
                metadatas=[{
                    **base_metadata,
                    "is_chunked": True,
                    "num_chunks": len(chunks)
                }]
            )

            # Store all chunks
            chunk_ids = []
            for chunk, embedding in zip(chunks, embeddings):
                chunks_collection.add(
                    ids=[chunk.chunk_id],
                    documents=[chunk.content],
                    embeddings=[embedding],
                    metadatas=[{
                        "artifact_id": artifact_id,
                        "chunk_index": chunk.chunk_index,
                        "start_char": chunk.start_char,
                        "end_char": chunk.end_char,
                        "token_count": chunk.token_count,
                        "content_hash": chunk.content_hash,
                        "ts": base_metadata["ts"],
                        "sensitivity": sensitivity,
                        "visibility_scope": visibility_scope,
                        "retention_policy": retention_policy,
                        "embedding_provider": "openai",
                        "embedding_model": config.openai_embed_model,
                        "embedding_dimensions": config.openai_embed_dims
                    }]
                )
                chunk_ids.append(chunk.chunk_id)

            logger.info(f"Successfully ingested chunked artifact {artifact_id}")

            # V3: Write to Postgres and enqueue job
            job_id = None
            job_status = None
            if pg_client and job_queue_service:
                try:
                    # Write revision to Postgres (include artifact_id for worker to fetch from ChromaDB)
                    await pg_client.transaction([
                        # Mark old revisions as not latest
                        (
                            "UPDATE artifact_revision SET is_latest = false WHERE artifact_uid = $1 AND is_latest = true",
                            (artifact_uid,)
                        ),
                        # Insert new revision
                        (
                            """INSERT INTO artifact_revision
                               (artifact_uid, revision_id, artifact_id, artifact_type, source_system, source_id, content_hash, token_count, is_chunked, chunk_count)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                               ON CONFLICT (artifact_uid, revision_id) DO NOTHING""",
                            (artifact_uid, revision_id, artifact_id, artifact_type, source_system, source_id or "", content_hash, token_count, True, len(chunks))
                        )
                    ])

                    # Enqueue event extraction job
                    job_uuid = await job_queue_service.enqueue_job(artifact_uid, revision_id)
                    if job_uuid:
                        job_id = str(job_uuid)
                        job_status = "PENDING"
                        logger.info(f"V3: Enqueued job {job_id} for {artifact_uid}/{revision_id}")

                except Exception as e:
                    logger.warning(f"V3: Failed to write to Postgres: {e}")

            return {
                "artifact_id": artifact_id,
                "artifact_uid": artifact_uid,
                "revision_id": revision_id,
                "is_chunked": True,
                "num_chunks": len(chunks),
                "stored_ids": [artifact_id] + chunk_ids,
                "job_id": job_id,
                "job_status": job_status
            }

    except ValidationError as e:
        return {"error": f"Validation error: {e}"}
    except EmbeddingError as e:
        return {"error": f"Embedding error: {e}"}
    except Exception as e:
        logger.error(f"artifact_ingest error: {e}", exc_info=True)
        return {"error": f"Internal server error: {str(e)}"}


@mcp.tool()
def artifact_search(
    query: str,
    limit: int = 5,
    artifact_type: Optional[str] = None,
    source_system: Optional[str] = None,
    sensitivity: Optional[str] = None,
    expand_neighbors: bool = False
) -> str:
    """
    Search document content with metadata filters.

    Use when you need to filter by artifact_type, source_system, or sensitivity.
    For general discovery, use hybrid_search instead (includes events).

    Args:
        query: Search query
        limit: Maximum results (1-50)
        artifact_type: Filter by type (email, document, meeting_notes, etc.)
        source_system: Filter by source (gmail, slack, notion, etc.)
        sensitivity: Filter by sensitivity level
        expand_neighbors: Include ±1 chunks for context
    """
    try:
        if not query or len(query) > 500:
            return "Error: Query must be between 1 and 500 characters"

        if limit < 1 or limit > 50:
            return "Error: Limit must be between 1 and 50"

        # Build filters
        filters = {}
        if artifact_type:
            filters["artifact_type"] = artifact_type
        if source_system:
            filters["source_system"] = source_system
        if sensitivity:
            filters["sensitivity"] = sensitivity

        # Use retrieval service for hybrid search (artifacts + chunks only)
        results = retrieval_service.hybrid_search(
            query=query,
            limit=limit,
            include_memory=False,
            expand_neighbors=expand_neighbors,
            filters=filters if filters else None
        )

        if not results:
            return "No results found."

        # Format output
        output = ["Found {} results:\n".format(len(results))]

        for i, merged_result in enumerate(results, 1):
            result = merged_result.result
            metadata = result.metadata

            result_type = "chunk" if result.is_chunk else "artifact"
            title = metadata.get("title", "Untitled")
            artifact_type_val = metadata.get("artifact_type", "unknown")
            source = metadata.get("source_system", "unknown")
            sensitivity_val = metadata.get("sensitivity", "normal")

            # Get snippet
            snippet = result.content[:200].replace("\n", " ")
            if len(result.content) > 200:
                snippet += "..."

            output.append(f"[{i}] {result_type}: {result.id} (RRF score: {merged_result.rrf_score:.3f})")
            output.append(f"    Title: {title}")
            output.append(f"    Type: {artifact_type_val} | Source: {source} | Sensitivity: {sensitivity_val}")
            output.append(f"    Snippet: {snippet}")

            source_url = metadata.get("source_url")
            if source_url:
                output.append(f"    Evidence: {source_url}")

            output.append("")  # Blank line

        return "\n".join(output)

    except Exception as e:
        logger.error(f"artifact_search error: {e}", exc_info=True)
        return f"Search failed: {str(e)}"


@mcp.tool()
def artifact_get(
    artifact_id: str,
    include_content: bool = False,
    include_chunks: bool = False
) -> dict:
    """
    Retrieve artifact metadata and optionally content.

    Args:
        artifact_id: Artifact ID (e.g., art_abc123)
        include_content: Return full content
        include_chunks: Return chunk list
    """
    try:
        if not artifact_id.startswith("art_"):
            return {"error": "Invalid artifact_id format. Must start with 'art_'"}

        artifacts_collection = get_artifacts_collection(chroma_manager.get_client())

        # Fetch artifact
        results = artifacts_collection.get(ids=[artifact_id])

        if not results or not results.get("ids"):
            return {"error": f"Artifact {artifact_id} not found"}

        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        artifact_content = documents[0] if documents else ""
        metadata = metadatas[0] if metadatas else {}

        is_chunked = metadata.get("is_chunked", False)

        response = {
            "artifact_id": artifact_id,
            "metadata": metadata
        }

        # Add content if requested
        if include_content:
            if not is_chunked:
                response["content"] = artifact_content
            else:
                # Reconstruct from chunks
                chunks_data = get_chunks_by_artifact(
                    chroma_manager.get_client(),
                    artifact_id
                )

                reconstructed = "\n".join([c["content"] for c in chunks_data])
                response["content"] = reconstructed

        # Add chunk list if requested
        if include_chunks and is_chunked:
            chunks_data = get_chunks_by_artifact(
                chroma_manager.get_client(),
                artifact_id
            )

            response["chunks"] = [
                {
                    "chunk_id": c["chunk_id"],
                    "chunk_index": c["metadata"]["chunk_index"],
                    "start_char": c["metadata"]["start_char"],
                    "end_char": c["metadata"]["end_char"],
                    "token_count": c["metadata"]["token_count"]
                }
                for c in chunks_data
            ]

        return response

    except Exception as e:
        logger.error(f"artifact_get error: {e}", exc_info=True)
        return {"error": f"Failed to get artifact: {str(e)}"}


@mcp.tool()
def artifact_delete(artifact_id: str) -> str:
    """
    Delete artifact and cascade to chunks.

    Args:
        artifact_id: Artifact ID to delete (e.g., art_abc123)
    """
    try:
        if not artifact_id.startswith("art_"):
            return "Error: Invalid artifact_id format. Must start with 'art_'"

        # Check if artifact exists
        artifacts_collection = get_artifacts_collection(chroma_manager.get_client())
        results = artifacts_collection.get(ids=[artifact_id])

        if not results or not results.get("ids"):
            return f"Error: Artifact {artifact_id} not found"

        # Delete artifact and chunks
        deleted_count = delete_artifact_cascade(
            chroma_manager.get_client(),
            artifact_id
        )

        logger.info(f"Deleted artifact {artifact_id} ({deleted_count} total items)")

        return f"Deleted artifact {artifact_id} and {deleted_count - 1} chunks"

    except Exception as e:
        logger.error(f"artifact_delete error: {e}", exc_info=True)
        return f"Failed to delete artifact: {str(e)}"


@mcp.tool()
async def hybrid_search(
    query: str,
    limit: int = 5,
    include_memory: bool = False,
    include_events: bool = True,
    expand_neighbors: bool = False,
    # V4 graph expansion parameters
    graph_expand: bool = True,
    graph_budget: int = 10,
    # Default tuned for quality: anchor expansion on the top hit to avoid pulling unrelated context
    graph_seed_limit: int = 1,
    graph_depth: int = 1,
    # Default matches V4 brief; pass null to opt out (i.e., all categories).
    graph_filters: Optional[List[str]] = ["Decision", "Commitment", "QualityRisk"],
    include_entities: bool = True,
    # Optional feature flag (V4 brief): currently treated as no-op if enabled
    include_revision_diff: bool = False
) -> dict:
    """
    PRIMARY SEARCH - Start here for context discovery.

    Searches across artifacts AND semantic events with source metadata for
    credibility reasoning. Returns document content plus extracted events
    (commitments, decisions, risks, etc.) with evidence quotes.

    V4 ENHANCEMENT: Set graph_expand=true to discover related events through
    shared actors/subjects across documents. This enables "portable memory" -
    finding context you didn't explicitly search for but is connected.

    Use this first for broad discovery, then use specialized tools to drill down:
    - event_search: For structured filters (category, time range, specific artifact)
    - artifact_search: For document-specific filters (type, source, sensitivity)
    - memory_search: For stored facts/memories (different domain)

    Args:
        query: Natural language search query
        limit: Maximum results (1-50)
        include_memory: Also search stored memories
        include_events: Include semantic events with source context (recommended)
        expand_neighbors: Include ±1 chunks for more context
        graph_expand: V4 - Enable graph-based context expansion (finds related events via shared actors/subjects)
        graph_budget: V4 - Max additional related items from graph expansion (1-50, default 10)
        graph_seed_limit: V4 - How many primary results to use as expansion seeds (1-20, default 5)
        graph_depth: V4 - Graph traversal depth (currently only 1 supported)
        graph_filters: V4 - Category filters for graph expansion (null = all categories)
        include_entities: V4 - Include entity information in response when graph_expand=true
    """
    try:
        if not query or len(query) > 500:
            return "Error: Query must be between 1 and 500 characters"

        if limit < 1 or limit > 50:
            return "Error: Limit must be between 1 and 50"

        # V4 validation (only applies when graph_expand=true).
        # Keep expand_options static and returned on every call (see HYBRID_SEARCH_EXPAND_OPTIONS).
        if graph_expand:
            if graph_budget < 0 or graph_budget > 50:
                return "Error: graph_budget must be between 0 and 50"
            if graph_seed_limit < 1 or graph_seed_limit > 20:
                return "Error: graph_seed_limit must be between 1 and 20"
            if graph_depth != 1:
                return "Error: graph_depth currently only supports 1"

            if graph_filters is not None:
                if not isinstance(graph_filters, list) or any(not isinstance(x, str) for x in graph_filters):
                    return "Error: graph_filters must be null or a list[str]"
                # Validate categories match the canonical event category set
                from tools.event_tools import EVENT_CATEGORIES
                invalid = [c for c in graph_filters if c not in EVENT_CATEGORIES]
                if invalid:
                    return f"Error: graph_filters contains invalid categories: {', '.join(invalid)}"

        # V3: Search semantic events in Postgres (used both for primary_results and
        # as preferred graph expansion seeds when available).
        event_results: List[dict] = []
        seed_event_ids = []
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
                    # Convert to UUIDs for graph expansion seeds (higher precision than vector->revision mapping),
                    # but choose seeds by lexical relevance to the query to avoid off-topic expansions when the
                    # event search uses OR fallback (e.g., "risk" matches many events).
                    from uuid import UUID
                    import re

                    def _anchor_tokens(q: str) -> List[str]:
                        toks = re.findall(r"[a-z0-9]+", (q or "").lower())
                        stop = {
                            "the","a","an","and","or","of","to","in","on","for","by","with","at","from",
                            "is","are","was","were","be","been","it","this","that","as"
                        }
                        out = []
                        for t in toks:
                            if t in stop:
                                continue
                            if t.isdigit() or len(t) >= 4:
                                out.append(t)
                        # unique in order
                        seen=set(); uniq=[]
                        for t in out:
                            if t not in seen:
                                uniq.append(t); seen.add(t)
                        return uniq

                    anchors = _anchor_tokens(query)
                    min_overlap = 2 if len(anchors) >= 5 else 1

                    scored = []
                    for ev in event_results:
                        narr = (ev.get("narrative") or "")
                        text = narr.lower()
                        overlap = sum(1 for t in anchors if t in text)
                        conf = float(ev.get("confidence") or 0.0)
                        scored.append((overlap, conf, ev))

                    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
                    for overlap, _conf, ev in scored:
                        if overlap < min_overlap:
                            continue
                        eid = ev.get("event_id")
                        if not eid:
                            continue
                        try:
                            seed_event_ids.append(UUID(str(eid).replace("evt_", "")))
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Event search failed: {e}")

        # V4: Use hybrid_search_v4 for graph expansion support.
        # If include_events=true and event search found matches, we seed graph expansion
        # from those event IDs to keep related_context anchored to the query.
        v4_result = await retrieval_service.hybrid_search_v4(
            query=query,
            limit=limit,
            include_memory=include_memory,
            expand_neighbors=expand_neighbors,
            graph_expand=graph_expand,
            graph_depth=graph_depth,
            graph_budget=graph_budget,
            graph_seed_limit=graph_seed_limit,
            graph_filters={"categories": graph_filters} if graph_filters is not None else None,
            include_entities=include_entities,
            seed_event_ids=seed_event_ids if seed_event_ids else None,
        )

        # Build stable JSON output per v4.md
        v4_dict = v4_result.to_dict()
        primary_results = v4_dict.get("primary_results", [])

        # Append event search results as additional primary_results (keeps current behavior of
        # searching both vector DB and event store, while returning a single structured payload).
        for ev in event_results:
            primary_results.append({
                "type": "event",
                "id": ev.get("event_id"),
                "category": ev.get("category"),
                "narrative": ev.get("narrative"),
                "event_time": ev.get("event_time"),
                "confidence": ev.get("confidence"),
                "source": ev.get("source"),
                "evidence": ev.get("evidence", [])
            })

        # Behavior requirement: expand_options is static capability metadata and must not depend on results.
        # Return it on every call so the assistant can offer follow-up expansions.
        expand_options = HYBRID_SEARCH_EXPAND_OPTIONS

        return {
            "primary_results": primary_results,
            "related_context": v4_dict.get("related_context", []) if graph_expand else [],
            "entities": (v4_dict.get("entities", []) if include_entities else []) if graph_expand else [],
            "expand_options": expand_options,
        }

    except Exception as e:
        logger.error(f"hybrid_search error: {e}", exc_info=True)
        return {"error": f"Search failed: {str(e)}"}


@mcp.tool()
def embedding_health() -> dict:
    """Check OpenAI API status and configuration."""
    try:
        # Get model info
        model_info = embedding_service.get_model_info()

        # Run health check
        health = embedding_service.health_check()

        # Combine results
        return {
            **model_info,
            **health,
            "api_key_configured": bool(config.openai_api_key)
        }

    except Exception as e:
        logger.error(f"embedding_health error: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# ============================================================================
# V3 TOOLS - Semantic Events
# ============================================================================

async def resolve_artifact_uid(identifier: str) -> Optional[str]:
    """
    Resolve an artifact identifier to artifact_uid.

    Accepts either:
    - artifact_id (art_xxx) - looks up artifact_uid from Postgres
    - artifact_uid (uid_xxx) - returns as-is

    Returns None if not found.
    """
    if not pg_client:
        return None

    # If already a uid_, return as-is
    if identifier.startswith("uid_"):
        return identifier

    # If art_, look up the uid from Postgres
    if identifier.startswith("art_"):
        try:
            result = await pg_client.fetch_one(
                "SELECT artifact_uid FROM artifact_revision WHERE artifact_id = $1 AND is_latest = true",
                identifier
            )
            if result:
                return result["artifact_uid"]
        except Exception as e:
            logger.warning(f"Failed to resolve artifact_uid for {identifier}: {e}")

    return None


@mcp.tool()
async def event_search_tool(
    query: Optional[str] = None,
    limit: int = 20,
    category: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    artifact_id: Optional[str] = None,
    include_evidence: bool = True
) -> dict:
    """
    Search events with structured filters (category, time, artifact).

    Use for targeted queries like "all commitments from last week" or
    "decisions from the board meeting". For general discovery, start
    with hybrid_search instead.

    Returns events with source metadata (document_date, source_type,
    author_title, etc.) for credibility reasoning.

    Args:
        query: Full-text search on event narratives (optional)
        limit: Maximum results (1-100)
        category: Commitment, Execution, Decision, Collaboration, QualityRisk, Feedback, Change, Stakeholder
        time_from: Filter events after this time (ISO8601)
        time_to: Filter events before this time (ISO8601)
        artifact_id: Filter to specific artifact (accepts art_xxx or uid_xxx)
        include_evidence: Include evidence quotes linking to source text
    """
    if not pg_client:
        return {"error": "V3 features unavailable - PostgreSQL not configured", "error_code": "V3_UNAVAILABLE"}

    # Resolve artifact_id to artifact_uid if provided
    resolved_uid = None
    if artifact_id:
        resolved_uid = await resolve_artifact_uid(artifact_id)
        if not resolved_uid:
            return {"error": f"Artifact {artifact_id} not found", "error_code": "NOT_FOUND"}

    return await event_search(
        pg_client,
        query=query,
        limit=limit,
        category=category,
        time_from=time_from,
        time_to=time_to,
        artifact_uid=resolved_uid,
        include_evidence=include_evidence
    )


@mcp.tool()
async def event_get_tool(event_id: str) -> dict:
    """
    Get a single semantic event by ID with all evidence.

    Args:
        event_id: Event UUID (with or without evt_ prefix)
    """
    if not pg_client:
        return {"error": "V3 features unavailable - PostgreSQL not configured", "error_code": "V3_UNAVAILABLE"}

    return await event_get(pg_client, event_id)


@mcp.tool()
async def event_list_for_artifact(
    artifact_id: str,
    revision_id: Optional[str] = None,
    include_evidence: bool = False
) -> dict:
    """
    List all semantic events for an artifact revision.

    Args:
        artifact_id: Artifact identifier (accepts art_xxx or uid_xxx)
        revision_id: Specific revision (defaults to latest)
        include_evidence: Include evidence quotes
    """
    if not pg_client:
        return {"error": "V3 features unavailable - PostgreSQL not configured", "error_code": "V3_UNAVAILABLE"}

    # Resolve to artifact_uid
    resolved_uid = await resolve_artifact_uid(artifact_id)
    if not resolved_uid:
        return {"error": f"Artifact {artifact_id} not found", "error_code": "NOT_FOUND"}

    return await event_list_for_revision(
        pg_client,
        artifact_uid=resolved_uid,
        revision_id=revision_id,
        include_evidence=include_evidence
    )


@mcp.tool()
async def event_reextract(
    artifact_id: str,
    revision_id: Optional[str] = None,
    force: bool = False
) -> dict:
    """
    Force re-extraction of events for an artifact revision.

    Args:
        artifact_id: Artifact identifier (accepts art_xxx or uid_xxx)
        revision_id: Specific revision (defaults to latest)
        force: If True, reset even if job is already DONE
    """
    if not pg_client or not job_queue_service:
        return {"error": "V3 features unavailable - PostgreSQL not configured", "error_code": "V3_UNAVAILABLE"}

    # Resolve to artifact_uid
    resolved_uid = await resolve_artifact_uid(artifact_id)
    if not resolved_uid:
        return {"error": f"Artifact {artifact_id} not found", "error_code": "NOT_FOUND"}

    try:
        return await job_queue_service.force_reextract(
            artifact_uid=resolved_uid,
            revision_id=revision_id,
            force=force
        )
    except Exception as e:
        logger.error(f"event_reextract error: {e}", exc_info=True)
        return {"error": str(e), "error_code": "INTERNAL_ERROR"}


@mcp.tool()
async def job_status(
    artifact_id: str,
    revision_id: Optional[str] = None
) -> dict:
    """
    Check event extraction job status for an artifact.

    Args:
        artifact_id: Artifact identifier (accepts art_xxx or uid_xxx)
        revision_id: Specific revision (defaults to latest)
    """
    if not pg_client or not job_queue_service:
        return {"error": "V3 features unavailable - PostgreSQL not configured", "error_code": "V3_UNAVAILABLE"}

    # Resolve to artifact_uid
    resolved_uid = await resolve_artifact_uid(artifact_id)
    if not resolved_uid:
        return {"error": f"Artifact {artifact_id} not found", "error_code": "NOT_FOUND"}

    try:
        result = await job_queue_service.get_job_status(
            artifact_uid=resolved_uid,
            revision_id=revision_id
        )

        if result is None:
            return {
                "error": f"No job found for {artifact_id}",
                "error_code": "NOT_FOUND"
            }

        return result

    except Exception as e:
        logger.error(f"job_status error: {e}", exc_info=True)
        return {"error": str(e), "error_code": "INTERNAL_ERROR"}


# ============================================================================
# V5 TOOLS - Simplified Interface
# ============================================================================

# Valid context types for V5 remember()
V5_VALID_CONTEXTS = [
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
        if context and context not in V5_VALID_CONTEXTS:
            return {"error": f"Invalid context '{context}'. Must be one of: {', '.join(V5_VALID_CONTEXTS)}"}

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
            logger.info(f"V5 remember: Content {artifact_id} already exists, upserting metadata")
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

            # Store each chunk in V5 chunks collection with full metadata
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
            logger.info(f"V5 remember: Chunked content {artifact_id} into {num_chunks} chunks")
        else:
            metadata["is_chunked"] = False
            metadata["num_chunks"] = 0

        # Store main content in V5 content collection
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
            logger.info(f"V5 remember: Skipping event extraction for short conversation turn ({token_count} tokens)")

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
                    logger.info(f"V5 remember: Enqueued extraction job {job_id} for {artifact_id}")

            except Exception as e:
                logger.warning(f"V5 remember: Failed to queue event extraction: {e}")

        # Generate summary
        summary = content[:100] + "..." if len(content) > 100 else content

        logger.info(f"V5 remember: Stored {artifact_id} ({context}, {token_count} tokens, chunked={is_chunked})")

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
        logger.error(f"V5 remember error: {e}", exc_info=True)
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
        min_importance: Minimum importance threshold (0.0-1.0)
        source: Filter by source system
        sensitivity: Filter by sensitivity level

    Returns:
        {
            results: [...],           # Primary matches
            related: [...],           # Graph-expanded context
            entities: [...],          # People/things mentioned
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
                        SELECT event_id, category, narrative, confidence, event_time
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
                            "event_time": str(row["event_time"]) if row["event_time"] else None
                        })
                except Exception as e:
                    logger.warning(f"V5 recall: Failed to fetch events: {e}")

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
                logger.error(f"V5 recall: Failed to get conversation history: {e}")
                return {"error": f"Failed to get conversation history: {str(e)}"}

        # Semantic search
        if query:
            if not query or len(query) > 500:
                return {"error": "Query must be between 1 and 500 characters"}

            # Use graph_filters default if not provided
            if graph_filters is None:
                graph_filters = ["Decision", "Commitment", "QualityRisk"]

            # V5: Use hybrid_search_v5 which searches V5 content collection
            v5_result = await retrieval_service.hybrid_search_v5(
                query=query,
                limit=limit,
                expand=expand,
                graph_budget=graph_budget,
                graph_filters={"categories": graph_filters} if graph_filters else None,
                include_entities=include_entities,
                context_filter=context,
                min_importance=min_importance,
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
                    logger.warning(f"V5 recall: Event search failed: {e}")

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

            return {
                "results": primary_results,
                "related": v4_dict.get("related_context", []) if expand else [],
                "entities": v4_dict.get("entities", []) if include_entities else [],
                "total_count": len(primary_results)
            }

        # No query, id, or conversation_id - return error
        return {"error": "Must provide query, id, or conversation_id"}

    except Exception as e:
        logger.error(f"V5 recall error: {e}", exc_info=True)
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
                    logger.warning(f"V5 forget: Failed to lookup event source: {e}")

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

        # Delete from V5 content collection and chunks
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

                logger.info(f"V5 forget: Deleted Postgres data for {artifact_uid}")

            except Exception as e:
                logger.warning(f"V5 forget: Failed to delete Postgres data: {e}")

        logger.info(f"V5 forget: Deleted {id} (content={chroma_deleted['content']}, chunks={chroma_deleted['chunks']}, events={events_deleted})")

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
        logger.error(f"V5 forget error: {e}", exc_info=True)
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
                "collections": ["content", "chunks"]  # V5 collections
            }
            if chroma_health.get("status") != "healthy":
                result["healthy"] = False

            # Get V5 collection counts
            try:
                client = chroma_manager.get_client()
                content_col = get_content_collection(client)
                chunks_col = get_chunks_collection(client)
                result["counts"]["content"] = content_col.count()
                result["counts"]["chunks"] = chunks_col.count()
            except Exception as e:
                logger.warning(f"V5 status: Failed to get collection counts: {e}")
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
                logger.warning(f"V5 status: Postgres error: {e}")
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

        # Graph expansion status (V4/V5 uses Postgres joins, not AGE)
        result["services"]["graph_expansion"] = {
            "status": "available" if pg_client else "unavailable",
            "backend": "postgres_joins"  # V5: no AGE dependency
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
                logger.warning(f"V5 status: Failed to get job status: {e}")

        return result

    except Exception as e:
        logger.error(f"V5 status error: {e}", exc_info=True)
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
    global pg_client, job_queue_service  # V3
    global graph_service  # V4

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

            # V3: Initialize job queue service
            job_queue_service = JobQueueService(pg_client, config.event_max_attempts)
            logger.info(f"  JobQueueService: OK (max attempts={config.event_max_attempts})")

            # V5: AGE GraphService disabled - graph expansion uses Postgres SQL joins
            # See retrieval_service._expand_from_events_sql() for V5 implementation
            graph_service = None
            logger.info("  GraphService: Disabled (V5 uses Postgres SQL joins for graph expansion)")

        except Exception as e:
            logger.warning(f"  PostgreSQL: UNAVAILABLE ({e}) - V3/V4 features disabled")
            pg_client = None
            job_queue_service = None
            graph_service = None

        # Initialize retrieval service (with V4 graph support if available)
        logger.info("Initializing RetrievalService...")
        retrieval_service = RetrievalService(
            embedding_service=embedding_service,
            chunking_service=chunking_service,
            chroma_client=chroma_manager.get_client(),
            k=config.rrf_constant,
            pg_client=pg_client,
            graph_service=graph_service
        )
        logger.info(f"  RetrievalService: OK (V4 graph_expand={'enabled' if graph_service else 'disabled'})")

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

    # V3: Add Postgres health
    if pg_client:
        health_data["postgres"] = await pg_client.health_check()
        health_data["v3_enabled"] = True
    else:
        health_data["v3_enabled"] = False

    # V4: Add graph health
    if graph_service:
        try:
            graph_health = await graph_service.get_health()
            health_data["graph"] = graph_health
            health_data["v4_enabled"] = True
        except Exception as e:
            health_data["graph"] = {"status": "error", "error": str(e)}
            health_data["v4_enabled"] = False
    else:
        health_data["v4_enabled"] = os.getenv("V4_GRAPH_ENABLED", "false").lower() == "true"

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
