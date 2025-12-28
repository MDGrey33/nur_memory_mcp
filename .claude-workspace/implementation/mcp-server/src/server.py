"""
MCP Memory Server v3.0 - Streamable HTTP Transport

A Model Context Protocol server that provides persistent memory and artifact storage
with OpenAI embeddings, token-window chunking, hybrid retrieval, and semantic event extraction.

V3 Features:
- Semantic event extraction from artifacts using LLM
- PostgreSQL storage for events, revisions, and job queue
- Async event worker for background processing
- Evidence linking to source text

Usage:
    python server.py

Configuration via .env file (see .env.example)
"""

import os
import logging
import hashlib
from datetime import datetime
from uuid import uuid4
from contextlib import asynccontextmanager
from typing import Optional, List

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
    delete_artifact_cascade
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

# Setup logging
logger = logging.getLogger("mcp-memory")

# Create FastMCP server
mcp = FastMCP("MCP Memory v3.0")

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
                logger.info(f"Artifact {artifact_id} unchanged, skipping ingestion")
                return {
                    "artifact_id": artifact_id,
                    "is_chunked": existing.get("metadata", {}).get("is_chunked", False),
                    "num_chunks": existing.get("metadata", {}).get("num_chunks", 0),
                    "stored_ids": [artifact_id],
                    "status": "unchanged"
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
                               (artifact_uid, revision_id, artifact_id, content_hash, token_count, is_chunked, chunk_count, is_latest, source_system, source_id, title,
                                document_date, source_type, document_status, author_title, distribution_scope)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, true, $8, $9, $10, $11, $12, $13, $14, $15)
                               ON CONFLICT (artifact_uid, revision_id) DO NOTHING""",
                            (artifact_uid, revision_id, artifact_id, content_hash, token_count, False, 0, source_system, source_id or "", title or "",
                             document_date, source_type, document_status, author_title, distribution_scope)
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
                               (artifact_uid, revision_id, artifact_id, content_hash, token_count, is_chunked, chunk_count, is_latest, source_system, source_id, title,
                                document_date, source_type, document_status, author_title, distribution_scope)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, true, $8, $9, $10, $11, $12, $13, $14, $15)
                               ON CONFLICT (artifact_uid, revision_id) DO NOTHING""",
                            (artifact_uid, revision_id, artifact_id, content_hash, token_count, True, len(chunks), source_system, source_id or "", title or "",
                             document_date, source_type, document_status, author_title, distribution_scope)
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
    expand_neighbors: bool = False
) -> str:
    """
    PRIMARY SEARCH - Start here for context discovery.

    Searches across artifacts AND semantic events with source metadata for
    credibility reasoning. Returns document content plus extracted events
    (commitments, decisions, risks, etc.) with evidence quotes.

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
    """
    try:
        if not query or len(query) > 500:
            return "Error: Query must be between 1 and 500 characters"

        if limit < 1 or limit > 50:
            return "Error: Limit must be between 1 and 50"

        # Use retrieval service for ChromaDB collections
        results = retrieval_service.hybrid_search(
            query=query,
            limit=limit,
            include_memory=include_memory,
            expand_neighbors=expand_neighbors
        )

        # Determine collections searched
        collections_searched = ["artifacts", "artifact_chunks"]
        if include_memory:
            collections_searched.append("memory")

        # V3: Also search semantic events in Postgres
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
                    collections_searched.append("events")
            except Exception as e:
                logger.warning(f"Event search failed: {e}")

        if not results and not event_results:
            return "No results found."

        # Format output
        total_results = len(results) + len(event_results)
        output = [f"Found {total_results} results (searched: {', '.join(collections_searched)}):\n"]

        result_num = 1

        # Output ChromaDB results
        for merged_result in results:
            result = merged_result.result
            metadata = result.metadata

            result_type = "chunk" if result.is_chunk else "artifact"
            if result.collection == "memory":
                result_type = "memory"

            output.append(f"[{result_num}] RRF score: {merged_result.rrf_score:.3f} (from: {', '.join(merged_result.collections)})")
            output.append(f"    Type: {result_type} | ID: {result.id}")

            if result.collection in ["artifacts", "artifact_chunks"]:
                title = metadata.get("title", "Untitled")
                source = metadata.get("source_system", "unknown")
                sensitivity = metadata.get("sensitivity", "normal")
                doc_date = metadata.get("document_date", "")
                doc_status = metadata.get("document_status", "")

                output.append(f"    Title: {title}")
                output.append(f"    Source: {source} | Sensitivity: {sensitivity}")
                if doc_date:
                    output.append(f"    Document Date: {doc_date}")
                if doc_status:
                    output.append(f"    Status: {doc_status}")

            # Snippet
            snippet = result.content[:200].replace("\n", " ")
            if len(result.content) > 200:
                snippet += "..."
            output.append(f"    Snippet: {snippet}")

            # Evidence URL
            source_url = metadata.get("source_url")
            if source_url:
                output.append(f"    Evidence: {source_url}")

            output.append("")  # Blank line
            result_num += 1

        # Output Event results (V3)
        for event in event_results:
            output.append(f"[{result_num}] Event: {event['category']} (confidence: {event['confidence']:.0%})")
            output.append(f"    Type: event | ID: {event['event_id']}")
            output.append(f"    Narrative: {event['narrative']}")

            # Event time
            if event.get("event_time"):
                output.append(f"    Event Time: {event['event_time']}")

            # Source context for authority reasoning
            source = event.get("source", {})
            if source.get("title"):
                output.append(f"    Source: {source.get('title')}")
            if source.get("document_date"):
                output.append(f"    Document Date: {source.get('document_date')}")
            if source.get("source_type"):
                output.append(f"    Source Type: {source.get('source_type')}")
            if source.get("document_status"):
                output.append(f"    Status: {source.get('document_status')}")
            if source.get("author_title"):
                output.append(f"    Author: {source.get('author_title')}")
            if source.get("distribution_scope"):
                output.append(f"    Distribution: {source.get('distribution_scope')}")

            # Evidence quote
            evidence = event.get("evidence", [])
            if evidence:
                quote = evidence[0].get("quote", "")[:100]
                if len(evidence[0].get("quote", "")) > 100:
                    quote += "..."
                output.append(f"    Evidence: \"{quote}\"")

            output.append("")  # Blank line
            result_num += 1

        return "\n".join(output)

    except Exception as e:
        logger.error(f"hybrid_search error: {e}", exc_info=True)
        return f"Search failed: {str(e)}"


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
# APPLICATION LIFECYCLE
# ============================================================================

session_manager: Optional[StreamableHTTPSessionManager] = None


@asynccontextmanager
async def lifespan(app):
    """Application lifespan - startup/shutdown."""
    global config, embedding_service, chunking_service, retrieval_service
    global privacy_service, chroma_manager, session_manager
    global pg_client, job_queue_service  # V3

    logger.info("=" * 60)
    logger.info("Starting MCP Memory Server v3.0")
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

        # Initialize retrieval service
        logger.info("Initializing RetrievalService...")
        retrieval_service = RetrievalService(
            embedding_service=embedding_service,
            chunking_service=chunking_service,
            chroma_client=chroma_manager.get_client(),
            k=config.rrf_constant
        )
        logger.info("  RetrievalService: OK")

        # Initialize privacy service (placeholder)
        logger.info("Initializing PrivacyFilterService...")
        privacy_service = PrivacyFilterService()
        logger.info("  PrivacyFilterService: OK (v2 placeholder)")

        # V3: Initialize Postgres client
        logger.info("Initializing PostgreSQL (V3)...")
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

        except Exception as e:
            logger.warning(f"  PostgreSQL: UNAVAILABLE ({e}) - V3 features disabled")
            pg_client = None
            job_queue_service = None

        # Create session manager
        session_manager = StreamableHTTPSessionManager(
            app=mcp._mcp_server,
            json_response=False,
            stateless=False,
        )

        # Run session manager
        async with session_manager.run():
            logger.info("=" * 60)
            logger.info(f"MCP Memory Server v3.0 ready at http://0.0.0.0:{config.mcp_port}/mcp/")
            logger.info("=" * 60)
            yield

    except Exception as e:
        logger.error(f"Failed to start server: {e}", exc_info=True)
        raise

    logger.info("MCP Memory Server v3.0 stopped")


async def health(request):
    """Health check endpoint."""
    health_data = {
        "status": "ok",
        "service": "mcp-memory",
        "version": "3.0.0"
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

    logger.info(f"Starting MCP Memory Server v3.0 on port {port}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=os.getenv("LOG_LEVEL", "INFO").lower(),
    )
