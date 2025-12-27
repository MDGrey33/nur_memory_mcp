"""
Event worker main loop for async event extraction.

Polls Postgres for PENDING jobs, claims them atomically, extracts events using LLM,
and writes results back to Postgres.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
import httpx

from config import Config
from storage.postgres_client import PostgresClient
from storage.chroma_client import ChromaClientManager
from services.event_extraction_service import EventExtractionService
from services.job_queue_service import JobQueueService

logger = logging.getLogger("event_worker")


class EventWorker:
    """Async event extraction worker."""

    def __init__(self, config: Config):
        """
        Initialize event worker.

        Args:
            config: Configuration object
        """
        self.config = config
        self.worker_id = config.worker_id or f"worker-{uuid4().hex[:8]}"
        self.poll_interval_ms = config.poll_interval_ms
        self.running = False

        # Initialize services (will connect in run())
        self.pg_client: Optional[PostgresClient] = None
        self.chroma_manager: Optional[ChromaClientManager] = None
        self.extraction_service: Optional[EventExtractionService] = None
        self.job_service: Optional[JobQueueService] = None

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
        """Process one job from the queue."""
        # Claim a job
        job = await self.job_service.claim_job(self.worker_id)

        if not job:
            # No jobs available
            return

        job_id = UUID(job["job_id"])
        artifact_uid = job["artifact_uid"]
        revision_id = job["revision_id"]

        logger.info(f"Processing job {job_id}: {artifact_uid}/{revision_id}")

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

            logger.info(f"Fetching artifact text (chunked={is_chunked}, chunks={chunk_count})")

            if not is_chunked:
                # Fetch whole artifact
                text = await self.fetch_artifact_text(artifact_id)
                chunk_texts = [(text, 0, artifact_id, 0)]
            else:
                # Fetch all chunks
                chunk_texts = await self.fetch_chunk_texts(artifact_id, chunk_count)

            # Extract events from each chunk (Prompt A)
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

            logger.info(f"Extracted {len(valid_events)} valid events")

            # Write events atomically
            await self.job_service.write_events_atomic(
                artifact_uid=artifact_uid,
                revision_id=revision_id,
                extraction_run_id=job_id,
                events=valid_events
            )

            # Mark job done
            await self.job_service.mark_job_done(job_id)

            logger.info(f"Job {job_id} completed successfully")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)

            # Determine if error is retryable
            error_code = type(e).__name__
            error_message = str(e)

            # Retryable errors: OpenAI rate limit, network timeouts
            retryable = any([
                "rate" in error_message.lower(),
                "timeout" in error_message.lower(),
                "connection" in error_message.lower(),
                isinstance(e, (httpx.TimeoutException, httpx.ConnectError))
            ])

            await self.job_service.mark_job_failed(
                job_id=job_id,
                error_code=error_code,
                error_message=error_message,
                retry=retryable
            )

    async def fetch_artifact_text(self, artifact_id: str) -> str:
        """
        Fetch artifact text from ChromaDB.

        Args:
            artifact_id: Artifact ID

        Returns:
            Full artifact text
        """
        client = self.chroma_manager.get_client()
        from storage.collections import get_artifacts_collection

        collection = get_artifacts_collection(client)

        results = collection.get(ids=[artifact_id])

        if not results or not results.get("documents"):
            raise ValueError(f"Artifact {artifact_id} not found in ChromaDB")

        return results["documents"][0]

    async def fetch_chunk_texts(
        self,
        artifact_id: str,
        chunk_count: int
    ) -> List[tuple]:
        """
        Fetch all chunk texts from ChromaDB.

        Args:
            artifact_id: Artifact ID
            chunk_count: Number of chunks

        Returns:
            List of (text, chunk_index, chunk_id, start_char) tuples
        """
        client = self.chroma_manager.get_client()
        from storage.collections import get_chunks_by_artifact

        chunks = get_chunks_by_artifact(client, artifact_id)

        if len(chunks) != chunk_count:
            logger.warning(f"Expected {chunk_count} chunks, found {len(chunks)}")

        # Sort by chunk_index
        chunks.sort(key=lambda c: c["metadata"]["chunk_index"])

        result = []
        for chunk in chunks:
            result.append((
                chunk["content"],
                chunk["metadata"]["chunk_index"],
                chunk["chunk_id"],
                chunk["metadata"]["start_char"]
            ))

        return result
