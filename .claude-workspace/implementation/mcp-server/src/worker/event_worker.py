"""
V6 Event worker - async event extraction with entity resolution.

Job types:
- extract_events: Extract semantic events from artifact text

Polls Postgres for PENDING jobs, claims them atomically, processes using LLM,
and writes results back to Postgres. Graph expansion uses SQL joins (no AGE).
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID, uuid4
import httpx

from config import Config
from storage.postgres_client import PostgresClient
from storage.chroma_client import ChromaClientManager
from services.event_extraction_service import EventExtractionService
from services.job_queue_service import JobQueueService
from services.entity_resolution_service import (
    EntityResolutionService,
    ExtractedEntity,
    ContextClues
)
from services.embedding_service import EmbeddingService

logger = logging.getLogger("event_worker")


class EventWorker:
    """V6 event extraction worker with entity resolution."""

    def __init__(self, config: Config, enable_v4: bool = True):
        """
        Initialize event worker.

        Args:
            config: Configuration object
            enable_v4: Enable entity resolution features
        """
        self.config = config
        self.worker_id = config.worker_id or f"worker-{uuid4().hex[:8]}"
        self.poll_interval_ms = config.poll_interval_ms
        self.running = False
        self.enable_v4 = enable_v4

        # Initialize services (will connect in run())
        self.pg_client: Optional[PostgresClient] = None
        self.chroma_manager: Optional[ChromaClientManager] = None
        self.extraction_service: Optional[EventExtractionService] = None
        self.job_service: Optional[JobQueueService] = None

        # Entity resolution services
        self.embedding_service: Optional[EmbeddingService] = None
        self.entity_resolution_service: Optional[EntityResolutionService] = None

    async def initialize(self) -> None:
        """Initialize all services."""
        logger.info("Initializing worker services...")

        # Postgres client
        self.pg_client = PostgresClient(
            dsn=self.config.events_db_dsn,
            min_pool_size=self.config.postgres_pool_min,
            max_pool_size=self.config.postgres_pool_max
        )
        await self.pg_client.connect()

        # Check Postgres health
        pg_health = await self.pg_client.health_check()
        if pg_health["status"] != "healthy":
            raise RuntimeError(f"Postgres unhealthy: {pg_health.get('error')}")

        logger.info("  Postgres: OK")

        # ChromaDB client (for reading artifact text)
        self.chroma_manager = ChromaClientManager(
            host=self.config.chroma_host,
            port=self.config.chroma_port
        )

        chroma_health = self.chroma_manager.health_check()
        if chroma_health["status"] != "healthy":
            raise RuntimeError(f"ChromaDB unhealthy: {chroma_health.get('error')}")

        logger.info("  ChromaDB: OK")

        # Event extraction service
        self.extraction_service = EventExtractionService(
            api_key=self.config.openai_api_key,
            model=self.config.openai_event_model,
            temperature=0.0,
            timeout=60
        )
        logger.info("  Event Extraction Service: OK")

        # Job queue service
        self.job_service = JobQueueService(
            pg_client=self.pg_client,
            max_attempts=self.config.event_max_attempts
        )
        logger.info("  Job Queue Service: OK")

        # V4 services
        if self.enable_v4:
            # Embedding service (for entity context embeddings)
            self.embedding_service = EmbeddingService(
                api_key=self.config.openai_api_key,
                model=getattr(self.config, 'openai_embedding_model', 'text-embedding-3-large'),
                dimensions=3072
            )
            logger.info("  Embedding Service: OK")

            # Entity resolution service
            self.entity_resolution_service = EntityResolutionService(
                pg_client=self.pg_client,
                embedding_service=self.embedding_service,
                openai_api_key=self.config.openai_api_key,
                similarity_threshold=0.85,
                max_candidates=5,
                model=getattr(self.config, 'openai_entity_model', 'gpt-4o-mini')
            )
            logger.info("  Entity Resolution Service: OK")

        logger.info("Worker services initialized")

    async def shutdown(self) -> None:
        """Shutdown all services."""
        logger.info("Shutting down worker services...")

        if self.pg_client:
            await self.pg_client.close()

        logger.info("Worker services shut down")

    async def run(self) -> None:
        """Run worker main loop."""
        await self.initialize()

        self.running = True
        logger.info(f"Worker {self.worker_id} started. Polling every {self.poll_interval_ms}ms")

        try:
            while self.running:
                try:
                    await self.process_one_job()
                except Exception as e:
                    logger.error(f"Error processing job: {e}", exc_info=True)

                # Sleep until next poll
                await asyncio.sleep(self.poll_interval_ms / 1000.0)

        except KeyboardInterrupt:
            logger.info("Worker interrupted")
        finally:
            await self.shutdown()

    async def process_one_job(self) -> None:
        """Process one job from the queue (V3 compatible)."""
        # Try to claim an extract_events job first
        # NOTE (V4): claim_job() historically claimed ANY pending job, including graph_upsert.
        # We must claim extract_events explicitly to avoid stealing graph_upsert jobs.
        job = await self.job_service.claim_job_by_type(self.worker_id, "extract_events")

        if job:
            await self._process_extract_events_job(job)
            return

        # V6: graph_upsert jobs are disabled - graph expansion uses Postgres SQL joins
        # Legacy graph_upsert jobs in queue will be ignored and eventually expire
        pass

    async def _process_extract_events_job(self, job: Dict[str, Any]) -> None:
        """Process an extract_events job."""
        job_id = UUID(job["job_id"])
        artifact_uid = job["artifact_uid"]
        revision_id = job["revision_id"]

        logger.info(f"Processing extract_events job {job_id}: {artifact_uid}/{revision_id}")

        try:
            # Load artifact revision
            revision = await self.pg_client.fetch_one(
                """
                SELECT * FROM artifact_revision
                WHERE artifact_uid = $1 AND revision_id = $2
                """,
                artifact_uid,
                revision_id
            )

            if not revision:
                raise ValueError(f"Revision not found: {artifact_uid}/{revision_id}")

            # Fetch artifact text from ChromaDB
            artifact_id = revision["artifact_id"]
            is_chunked = revision["is_chunked"]
            chunk_count = revision["chunk_count"]
            doc_title = revision.get("title", artifact_uid)

            logger.info(f"Fetching artifact text (chunked={is_chunked}, chunks={chunk_count})")

            if not is_chunked:
                # Fetch whole artifact
                text = await self.fetch_artifact_text(artifact_id)
                chunk_texts = [(text, 0, artifact_id, 0)]
            else:
                # Fetch all chunks
                chunk_texts = await self.fetch_chunk_texts(artifact_id, chunk_count)

            # V4: Extract events AND entities from each chunk
            if self.enable_v4 and self.entity_resolution_service:
                await self._process_extraction_v4(
                    job_id=job_id,
                    artifact_uid=artifact_uid,
                    revision_id=revision_id,
                    chunk_texts=chunk_texts,
                    doc_title=doc_title
                )
            else:
                # V3 fallback: Extract events only
                await self._process_extraction_v3(
                    job_id=job_id,
                    artifact_uid=artifact_uid,
                    revision_id=revision_id,
                    chunk_texts=chunk_texts
                )

            # Mark job done
            await self.job_service.mark_job_done(job_id)
            logger.info(f"Job {job_id} completed successfully")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            await self._mark_job_failed(job_id, e)

    async def _process_extraction_v3(
        self,
        job_id: UUID,
        artifact_uid: str,
        revision_id: str,
        chunk_texts: List[Tuple]
    ) -> None:
        """V3 extraction: events only."""
        chunk_events = []
        for chunk_text, chunk_index, chunk_id, start_char in chunk_texts:
            events = self.extraction_service.extract_from_chunk(
                chunk_text=chunk_text,
                chunk_index=chunk_index,
                chunk_id=chunk_id,
                start_char=start_char
            )
            chunk_events.append(events)

        # Canonicalize events across chunks (Prompt B)
        canonical_events = self.extraction_service.canonicalize_events(chunk_events)

        # Validate events
        valid_events = [
            event for event in canonical_events
            if self.extraction_service.validate_event(event)
        ]

        logger.info(f"Extracted {len(valid_events)} valid events (V3)")

        # Write events atomically
        await self.job_service.write_events_atomic(
            artifact_uid=artifact_uid,
            revision_id=revision_id,
            extraction_run_id=job_id,
            events=valid_events
        )

    async def _process_extraction_v4(
        self,
        job_id: UUID,
        artifact_uid: str,
        revision_id: str,
        chunk_texts: List[Tuple],
        doc_title: str
    ) -> None:
        """V8 extraction: events + entities + relationships with resolution."""
        chunk_events = []
        chunk_entities = []
        chunk_relationships = []

        for chunk_text, chunk_index, chunk_id, start_char in chunk_texts:
            events, entities, relationships = self.extraction_service.extract_from_chunk_v4(
                chunk_text=chunk_text,
                chunk_index=chunk_index,
                chunk_id=chunk_id,
                start_char=start_char
            )
            chunk_events.append(events)
            chunk_entities.append(entities)
            chunk_relationships.append(relationships)

        # Canonicalize events across chunks (Prompt B)
        canonical_events = self.extraction_service.canonicalize_events(chunk_events)

        # Validate events
        valid_events = [
            event for event in canonical_events
            if self.extraction_service.validate_event(event)
        ]

        # Deduplicate entities across chunks
        deduped_entities = self.extraction_service.deduplicate_entities(chunk_entities)

        # V8: Deduplicate relationships across chunks
        deduped_relationships = self.extraction_service.deduplicate_relationships(chunk_relationships)

        logger.info(f"Extracted {len(valid_events)} events, {len(deduped_entities)} entities, {len(deduped_relationships)} relationships (V8)")

        # Resolve entities to canonical IDs
        # Map multiple surface forms/aliases to resolved entity IDs so we can reliably
        # link event actors/subjects to entity IDs (and produce ABOUT edges).
        #
        # Keys are lowercased strings (canonical_suggestion, surface_form, aliases_in_doc).
        entity_map: Dict[str, UUID] = {}
        for entity_dict in deduped_entities:
            try:
                extracted = ExtractedEntity.from_dict(entity_dict)
                result = await self.entity_resolution_service.resolve_extracted_entity(
                    extracted=extracted,
                    artifact_uid=artifact_uid,
                    revision_id=revision_id,
                    doc_title=doc_title
                )
                # Canonical suggestion
                if extracted.canonical_suggestion:
                    entity_map[extracted.canonical_suggestion.lower()] = result.entity_id
                # Surface form
                if extracted.surface_form:
                    entity_map[extracted.surface_form.lower()] = result.entity_id
                # Aliases observed in doc/chunk
                for alias in extracted.aliases_in_doc or []:
                    if alias:
                        entity_map[alias.lower()] = result.entity_id
            except Exception as e:
                logger.warning(f"Entity resolution failed for '{entity_dict.get('surface_form')}': {e}")

        # Build entity-event mapping
        entity_event_map: Dict[str, List[Dict[str, Any]]] = {}

        for idx, event in enumerate(valid_events):
            event_entities = []

            # Map actors to resolved entity IDs
            for actor in event.get("actors", []):
                actor_ref = actor.get("ref", "").lower()
                if actor_ref in entity_map:
                    event_entities.append({
                        "entity_id": entity_map[actor_ref],
                        "role": actor.get("role", "other"),
                        "is_actor": True
                    })

            # Map subject to resolved entity ID
            subject = event.get("subject", {})
            subject_ref = subject.get("ref", "").lower()
            if subject_ref in entity_map:
                event_entities.append({
                    "entity_id": entity_map[subject_ref],
                    "is_actor": False
                })

            if event_entities:
                entity_event_map[str(idx)] = event_entities

        # Write events with entity relationships
        # V6: graph_upsert disabled - expansion uses Postgres joins (no AGE)
        await self.job_service.write_events_atomic_v4(
            artifact_uid=artifact_uid,
            revision_id=revision_id,
            extraction_run_id=job_id,
            events=valid_events,
            entity_event_map=entity_event_map,
            enqueue_graph_upsert=False  # V6: AGE graph removed
        )

        # V8: Store explicit edges between entities
        edges_stored = 0
        for rel in deduped_relationships:
            source_name = rel.get("source_entity", "").lower()
            target_name = rel.get("target_entity", "").lower()

            # Lookup entity IDs
            source_id = entity_map.get(source_name)
            target_id = entity_map.get(target_name)

            if source_id and target_id and source_id != target_id:
                try:
                    await self.pg_client.execute(
                        """
                        INSERT INTO entity_edge (
                            source_entity_id, target_entity_id, relationship_type,
                            artifact_uid, revision_id, confidence, evidence_quote
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (source_entity_id, target_entity_id, relationship_type, artifact_uid)
                        DO UPDATE SET
                            confidence = GREATEST(entity_edge.confidence, EXCLUDED.confidence),
                            evidence_quote = COALESCE(EXCLUDED.evidence_quote, entity_edge.evidence_quote)
                        """,
                        source_id,
                        target_id,
                        rel.get("relationship_type", "RELATES_TO"),
                        artifact_uid,
                        revision_id,
                        rel.get("confidence", 0.8),
                        rel.get("evidence_quote")
                    )
                    edges_stored += 1
                except Exception as e:
                    logger.warning(f"Failed to store edge {source_name} -> {target_name}: {e}")
            else:
                if not source_id:
                    logger.debug(f"Edge source entity not found: {source_name}")
                if not target_id:
                    logger.debug(f"Edge target entity not found: {target_name}")

        logger.info(f"Stored {edges_stored} explicit edges (V8)")

    async def _mark_job_failed(self, job_id: UUID, error: Exception) -> None:
        """Mark a job as failed with appropriate retry logic."""
        error_code = type(error).__name__
        error_message = str(error)

        # Retryable errors: OpenAI rate limit, network timeouts
        retryable = any([
            "rate" in error_message.lower(),
            "timeout" in error_message.lower(),
            "connection" in error_message.lower(),
            isinstance(error, (httpx.TimeoutException, httpx.ConnectError))
        ])

        await self.job_service.mark_job_failed(
            job_id=job_id,
            error_code=error_code,
            error_message=error_message,
            retry=retryable
        )

    async def fetch_artifact_text(self, artifact_id: str) -> str:
        """
        Fetch artifact text from ChromaDB (V6 content collection).

        Args:
            artifact_id: Artifact ID (art_xxx format)

        Returns:
            Full artifact text
        """
        client = self.chroma_manager.get_client()
        from storage.collections import get_content_by_id

        result = get_content_by_id(client, artifact_id)
        if result and result.get("content"):
            return result["content"]

        raise ValueError(f"Artifact {artifact_id} not found in content collection")

    async def fetch_chunk_texts(
        self,
        artifact_id: str,
        chunk_count: int
    ) -> List[tuple]:
        """
        Fetch all chunk texts from ChromaDB (V6 chunks collection).

        Args:
            artifact_id: Artifact ID (art_xxx format)
            chunk_count: Number of chunks

        Returns:
            List of (text, chunk_index, chunk_id, start_char) tuples
        """
        client = self.chroma_manager.get_client()
        from storage.collections import get_v5_chunks_by_content

        chunks = get_v5_chunks_by_content(client, artifact_id)

        if len(chunks) != chunk_count:
            logger.warning(f"Expected {chunk_count} chunks, found {len(chunks)}")

        # Sort by chunk_index (already sorted by helper, but ensure)
        chunks.sort(key=lambda c: c["metadata"].get("chunk_index", 0))

        result = []
        for chunk in chunks:
            result.append((
                chunk["content"],
                chunk["metadata"].get("chunk_index", 0),
                chunk["chunk_id"],
                chunk["metadata"].get("start_char", 0)
            ))

        return result
