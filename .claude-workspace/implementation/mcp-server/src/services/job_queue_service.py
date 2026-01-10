"""
Job queue service for async event extraction using Postgres as queue.
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from uuid import UUID, uuid4
import json

from storage.postgres_client import PostgresClient
from storage.postgres_models import EventJob, SemanticEvent, EventEvidence, job_to_dict

logger = logging.getLogger("job_queue")


class JobQueueService:
    """Service for managing event extraction job queue."""

    def __init__(self, pg_client: PostgresClient, max_attempts: int = 5):
        """
        Initialize job queue service.

        Args:
            pg_client: Postgres client instance
            max_attempts: Maximum retry attempts for failed jobs
        """
        self.pg = pg_client
        self.max_attempts = max_attempts

    async def enqueue_job(
        self,
        artifact_uid: str,
        revision_id: str,
        job_type: str = "extract_events"
    ) -> Optional[UUID]:
        """
        Enqueue a new extraction job (idempotent).

        Args:
            artifact_uid: Artifact UID
            revision_id: Revision ID
            job_type: Job type (default: extract_events)

        Returns:
            Job ID if created, None if already exists
        """
        try:
            query = """
            INSERT INTO event_jobs (artifact_uid, revision_id, job_type, status, max_attempts)
            VALUES ($1, $2, $3, 'PENDING', $4)
            ON CONFLICT (artifact_uid, revision_id, job_type) DO NOTHING
            RETURNING job_id
            """

            job_id = await self.pg.fetch_val(
                query,
                artifact_uid,
                revision_id,
                job_type,
                self.max_attempts
            )

            if job_id:
                logger.info(f"Enqueued job {job_id} for {artifact_uid}/{revision_id}")
            else:
                logger.info(f"Job already exists for {artifact_uid}/{revision_id}")

            return job_id

        except Exception as e:
            logger.error(f"Failed to enqueue job: {e}")
            raise

    async def claim_job(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        Atomically claim a pending job (FOR UPDATE SKIP LOCKED).

        IMPORTANT (V4):
        Historically this method claimed any pending job type, which is unsafe now that
        we have multiple job types (e.g., extract_events, graph_upsert). To preserve
        backwards compatibility while remaining correct, this method is now equivalent
        to claiming an `extract_events` job.

        Args:
            worker_id: Worker ID claiming the job

        Returns:
            Job dict or None if no jobs available
        """
        # Delegate to the safe typed method (extract_events).
        return await self.claim_job_by_type(worker_id, "extract_events")

    async def mark_job_done(self, job_id: UUID) -> None:
        """
        Mark job as successfully completed.

        Args:
            job_id: Job ID to mark done
        """
        try:
            query = """
            UPDATE event_jobs
            SET status = 'DONE',
                updated_at = now()
            WHERE job_id = $1
            """

            await self.pg.execute(query, job_id)
            logger.info(f"Job {job_id} marked DONE")

        except Exception as e:
            logger.error(f"Failed to mark job done: {e}")
            raise

    async def mark_job_failed(
        self,
        job_id: UUID,
        error_code: str,
        error_message: str,
        retry: bool = False
    ) -> None:
        """
        Mark job as failed (with optional retry).

        Args:
            job_id: Job ID to mark failed
            error_code: Error code
            error_message: Error message
            retry: If True, set status to PENDING with backoff
        """
        try:
            # Fetch current attempts
            job = await self.pg.fetch_one(
                "SELECT attempts, max_attempts FROM event_jobs WHERE job_id = $1",
                job_id
            )

            if not job:
                logger.error(f"Job {job_id} not found")
                return

            attempts = job["attempts"]
            max_attempts = job["max_attempts"]

            if retry and attempts < max_attempts:
                # Retry with exponential backoff
                backoff_seconds = min(30 * (2 ** attempts), 600)  # Max 10 minutes
                next_run_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)

                query = """
                UPDATE event_jobs
                SET status = 'PENDING',
                    next_run_at = $1,
                    last_error_code = $2,
                    last_error_message = $3,
                    updated_at = now()
                WHERE job_id = $4
                """

                await self.pg.execute(query, next_run_at, error_code, error_message, job_id)
                logger.info(f"Job {job_id} retrying in {backoff_seconds}s (attempt {attempts}/{max_attempts})")

            else:
                # Terminal failure
                query = """
                UPDATE event_jobs
                SET status = 'FAILED',
                    last_error_code = $1,
                    last_error_message = $2,
                    updated_at = now()
                WHERE job_id = $3
                """

                await self.pg.execute(query, error_code, error_message, job_id)
                logger.error(f"Job {job_id} marked FAILED after {attempts} attempts")

        except Exception as e:
            logger.error(f"Failed to mark job failed: {e}")
            raise

    async def get_job_status(
        self,
        artifact_uid: str,
        revision_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get job status for an artifact revision.

        Args:
            artifact_uid: Artifact UID
            revision_id: Revision ID (if None, get latest)

        Returns:
            Job status dict or None
        """
        try:
            if revision_id:
                query = """
                SELECT * FROM event_jobs
                WHERE artifact_uid = $1 AND revision_id = $2
                ORDER BY created_at DESC
                LIMIT 1
                """
                row = await self.pg.fetch_one(query, artifact_uid, revision_id)
            else:
                # Get latest revision
                rev_query = """
                SELECT revision_id FROM artifact_revision
                WHERE artifact_uid = $1 AND is_latest = true
                LIMIT 1
                """
                rev_row = await self.pg.fetch_one(rev_query, artifact_uid)

                if not rev_row:
                    return None

                revision_id = rev_row["revision_id"]

                query = """
                SELECT * FROM event_jobs
                WHERE artifact_uid = $1 AND revision_id = $2
                LIMIT 1
                """
                row = await self.pg.fetch_one(query, artifact_uid, revision_id)

            if not row:
                return None

            return {
                "job_id": str(row["job_id"]),
                "artifact_uid": row["artifact_uid"],
                "revision_id": row["revision_id"],
                "status": row["status"],
                "attempts": row["attempts"],
                "max_attempts": row["max_attempts"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
                "locked_by": row["locked_by"],
                "last_error_code": row["last_error_code"],
                "last_error_message": row["last_error_message"],
                "next_run_at": row["next_run_at"].isoformat() if row.get("next_run_at") else None
            }

        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            raise

    async def write_events_atomic(
        self,
        artifact_uid: str,
        revision_id: str,
        extraction_run_id: UUID,
        events: List[Dict[str, Any]]
    ) -> None:
        """
        Write events atomically (replace-on-success).

        Args:
            artifact_uid: Artifact UID
            revision_id: Revision ID
            extraction_run_id: Job ID for traceability
            events: List of extracted events with evidence
        """
        try:
            async with self.pg.acquire() as conn:
                async with conn.transaction():
                    # Delete old events (cascade deletes evidence)
                    delete_query = """
                    DELETE FROM semantic_event
                    WHERE artifact_uid = $1 AND revision_id = $2
                    """
                    await conn.execute(delete_query, artifact_uid, revision_id)

                    logger.info(f"Deleted old events for {artifact_uid}/{revision_id}")

                    # Insert new events
                    for event in events:
                        event_query = """
                        INSERT INTO semantic_event (
                            artifact_uid, revision_id, category, event_time,
                            narrative, subject_json, actors_json, confidence,
                            extraction_run_id
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        RETURNING event_id
                        """

                        event_time = None
                        if event.get("event_time"):
                            # Parse ISO8601 or leave as None
                            try:
                                event_time = datetime.fromisoformat(event["event_time"].replace("Z", "+00:00"))
                            except (ValueError, TypeError) as e:
                                logger.warning(f"Invalid event_time format: {event.get('event_time')}: {e}")

                        event_id = await conn.fetchval(
                            event_query,
                            artifact_uid,
                            revision_id,
                            event["category"],
                            event_time,
                            event["narrative"],
                            json.dumps(event["subject"]),
                            json.dumps(event["actors"]),
                            event["confidence"],
                            extraction_run_id
                        )

                        # Insert evidence
                        for ev in event.get("evidence", []):
                            evidence_query = """
                            INSERT INTO event_evidence (
                                event_id, artifact_uid, revision_id, chunk_id,
                                start_char, end_char, quote
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """

                            await conn.execute(
                                evidence_query,
                                event_id,
                                artifact_uid,
                                revision_id,
                                ev.get("chunk_id"),
                                ev["start_char"],
                                ev["end_char"],
                                ev["quote"]
                            )

                    logger.info(f"Wrote {len(events)} events for {artifact_uid}/{revision_id}")

        except Exception as e:
            logger.error(f"Failed to write events: {e}")
            raise

    async def force_reextract(
        self,
        artifact_uid: str,
        revision_id: Optional[str] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Force re-extraction of events for a revision.

        Args:
            artifact_uid: Artifact UID
            revision_id: Revision ID (if None, use latest)
            force: If True, reset even if job is DONE

        Returns:
            Job status dict
        """
        try:
            # Resolve revision_id if not provided
            if not revision_id:
                rev_query = """
                SELECT revision_id FROM artifact_revision
                WHERE artifact_uid = $1 AND is_latest = true
                LIMIT 1
                """
                rev_row = await self.pg.fetch_one(rev_query, artifact_uid)

                if not rev_row:
                    raise ValueError(f"Artifact {artifact_uid} not found")

                revision_id = rev_row["revision_id"]

            # Check existing job
            job = await self.get_job_status(artifact_uid, revision_id)

            if job and job["status"] == "DONE" and not force:
                return {
                    **job,
                    "message": "Job already DONE (use force=true to override)"
                }

            if job and job["status"] == "PROCESSING":
                return {
                    **job,
                    "message": "Job already in progress"
                }

            # Reset job to PENDING or create new one
            if job:
                reset_query = """
                UPDATE event_jobs
                SET status = 'PENDING',
                    attempts = 0,
                    next_run_at = now(),
                    locked_at = NULL,
                    locked_by = NULL,
                    last_error_code = NULL,
                    last_error_message = NULL,
                    updated_at = now()
                WHERE artifact_uid = $1 AND revision_id = $2
                """
                await self.pg.execute(reset_query, artifact_uid, revision_id)

                logger.info(f"Reset job for {artifact_uid}/{revision_id}")

                return {
                    **job,
                    "status": "PENDING",
                    "message": "Job reset and re-enqueued (force=true)"
                }
            else:
                job_id = await self.enqueue_job(artifact_uid, revision_id)

                return {
                    "job_id": str(job_id),
                    "artifact_uid": artifact_uid,
                    "revision_id": revision_id,
                    "status": "PENDING",
                    "message": "Re-extraction job enqueued"
                }

        except Exception as e:
            logger.error(f"Failed to force reextract: {e}")
            raise

    # =========================================================================
    # V4: Enhanced methods for entity resolution and graph support
    # =========================================================================

    async def write_events_atomic_v4(
        self,
        artifact_uid: str,
        revision_id: str,
        extraction_run_id: UUID,
        events: List[Dict[str, Any]],
        entity_event_map: Dict[str, List[Dict[str, Any]]] = None,
        enqueue_graph_upsert: bool = False,  # V5: Disabled - AGE graph removed
        event_embeddings: List[Optional[List[float]]] = None  # V9: Cached embeddings
    ) -> None:
        """
        Write events with V4 entity relationships (replace-on-success).

        This extended version:
        1. Writes events and evidence (V3)
        2. Writes event_actor and event_subject relationships (V4)
        3. Optionally enqueues graph_upsert job (V4) - DISABLED in V5
        4. Stores narrative embeddings for triplet scoring cache (V9)

        Args:
            artifact_uid: Artifact UID
            revision_id: Revision ID
            extraction_run_id: Job ID for traceability
            events: List of extracted events with evidence
            entity_event_map: Map of event index -> list of {entity_id, role, is_actor}
            enqueue_graph_upsert: Whether to enqueue graph materialization job (V5: disabled)
            event_embeddings: Pre-computed embeddings for each event narrative (V9)
        """
        entity_event_map = entity_event_map or {}

        try:
            async with self.pg.acquire() as conn:
                async with conn.transaction():
                    # Delete old events (cascade deletes evidence, event_actor, event_subject)
                    delete_query = """
                    DELETE FROM semantic_event
                    WHERE artifact_uid = $1 AND revision_id = $2
                    """
                    await conn.execute(delete_query, artifact_uid, revision_id)

                    logger.info(f"Deleted old events for {artifact_uid}/{revision_id}")

                    event_ids = []
                    event_embeddings = event_embeddings or []

                    # Insert new events
                    for idx, event in enumerate(events):
                        # V9: Get embedding for this event (if available)
                        embedding = event_embeddings[idx] if idx < len(event_embeddings) else None

                        event_query = """
                        INSERT INTO semantic_event (
                            artifact_uid, revision_id, category, event_time,
                            narrative, subject_json, actors_json, confidence,
                            extraction_run_id, embedding
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        RETURNING event_id
                        """

                        event_time = None
                        if event.get("event_time"):
                            try:
                                event_time = datetime.fromisoformat(
                                    event["event_time"].replace("Z", "+00:00")
                                )
                            except (ValueError, TypeError) as e:
                                logger.warning(f"Invalid event_time: {event.get('event_time')}: {e}")

                        # V9: Convert embedding to string format for pgvector
                        embedding_str = None
                        if embedding:
                            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

                        event_id = await conn.fetchval(
                            event_query,
                            artifact_uid,
                            revision_id,
                            event["category"],
                            event_time,
                            event["narrative"],
                            json.dumps(event["subject"]),
                            json.dumps(event["actors"]),
                            event["confidence"],
                            extraction_run_id,
                            embedding_str
                        )

                        event_ids.append(event_id)

                        # Insert evidence
                        for ev in event.get("evidence", []):
                            evidence_query = """
                            INSERT INTO event_evidence (
                                event_id, artifact_uid, revision_id, chunk_id,
                                start_char, end_char, quote
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """

                            await conn.execute(
                                evidence_query,
                                event_id,
                                artifact_uid,
                                revision_id,
                                ev.get("chunk_id"),
                                ev["start_char"],
                                ev["end_char"],
                                ev["quote"]
                            )

                        # V4: Insert event_actor and event_subject relationships
                        event_entities = entity_event_map.get(str(idx), [])
                        for rel in event_entities:
                            entity_id = rel.get("entity_id")
                            if not entity_id:
                                continue

                            if rel.get("is_actor", False):
                                # Insert event_actor
                                actor_query = """
                                INSERT INTO event_actor (event_id, entity_id, role)
                                VALUES ($1, $2, $3)
                                ON CONFLICT (event_id, entity_id) DO UPDATE SET role = $3
                                """
                                role = rel.get("role", "other")
                                # Normalize role to allowed values
                                if role not in ("owner", "contributor", "reviewer", "stakeholder", "other"):
                                    role = "other"
                                await conn.execute(actor_query, event_id, entity_id, role)
                            else:
                                # Insert event_subject
                                subject_query = """
                                INSERT INTO event_subject (event_id, entity_id)
                                VALUES ($1, $2)
                                ON CONFLICT (event_id, entity_id) DO NOTHING
                                """
                                await conn.execute(subject_query, event_id, entity_id)

                    logger.info(f"Wrote {len(events)} events for {artifact_uid}/{revision_id}")

                    # V4: Enqueue graph_upsert job in same transaction
                    if enqueue_graph_upsert:
                        graph_job_query = """
                        INSERT INTO event_jobs (artifact_uid, revision_id, job_type, status, max_attempts)
                        VALUES ($1, $2, 'graph_upsert', 'PENDING', $3)
                        ON CONFLICT (artifact_uid, revision_id, job_type) DO UPDATE
                        SET status = 'PENDING',
                            attempts = 0,
                            next_run_at = now(),
                            updated_at = now()
                        RETURNING job_id
                        """

                        graph_job_id = await conn.fetchval(
                            graph_job_query,
                            artifact_uid,
                            revision_id,
                            self.max_attempts
                        )

                        logger.info(f"Enqueued graph_upsert job {graph_job_id}")

        except Exception as e:
            logger.error(f"Failed to write events (V4): {e}")
            raise

    async def claim_job_by_type(
        self,
        worker_id: str,
        job_type: str = "extract_events"
    ) -> Optional[Dict[str, Any]]:
        """
        Atomically claim a pending job of a specific type.

        Args:
            worker_id: Worker ID claiming the job
            job_type: Job type to claim (extract_events, graph_upsert)

        Returns:
            Job dict or None if no jobs available
        """
        try:
            async with self.pg.acquire() as conn:
                async with conn.transaction():
                    select_query = """
                    SELECT job_id, artifact_uid, revision_id, attempts
                    FROM event_jobs
                    WHERE status = 'PENDING'
                      AND job_type = $1
                      AND next_run_at <= now()
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """

                    row = await conn.fetchrow(select_query, job_type)

                    if not row:
                        return None

                    job_id = row["job_id"]

                    update_query = """
                    UPDATE event_jobs
                    SET status = 'PROCESSING',
                        locked_at = now(),
                        locked_by = $1,
                        attempts = attempts + 1,
                        updated_at = now()
                    WHERE job_id = $2
                    """

                    await conn.execute(update_query, worker_id, job_id)

                    logger.info(f"Worker {worker_id} claimed {job_type} job {job_id}")

                    return {
                        "job_id": str(job_id),
                        "job_type": job_type,
                        "artifact_uid": row["artifact_uid"],
                        "revision_id": row["revision_id"],
                        "attempts": row["attempts"] + 1
                    }

        except Exception as e:
            logger.error(f"Failed to claim {job_type} job: {e}")
            raise

    async def get_entities_for_revision(
        self,
        artifact_uid: str,
        revision_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get all entities related to events in a revision.

        Used by graph_upsert worker.

        Args:
            artifact_uid: Artifact UID
            revision_id: Revision ID

        Returns:
            List of entity dicts with their event relationships
        """
        query = """
        WITH event_entities AS (
            SELECT DISTINCT e.entity_id
            FROM semantic_event se
            JOIN event_actor ea ON se.event_id = ea.event_id
            JOIN entity e ON ea.entity_id = e.entity_id
            WHERE se.artifact_uid = $1 AND se.revision_id = $2

            UNION

            SELECT DISTINCT e.entity_id
            FROM semantic_event se
            JOIN event_subject es ON se.event_id = es.event_id
            JOIN entity e ON es.entity_id = e.entity_id
            WHERE se.artifact_uid = $1 AND se.revision_id = $2
        )
        SELECT e.entity_id, e.entity_type, e.canonical_name,
               e.role, e.organization, e.email, e.needs_review
        FROM event_entities ee
        JOIN entity e ON ee.entity_id = e.entity_id
        """

        try:
            rows = await self.pg.fetch_all(query, artifact_uid, revision_id)
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get entities for revision: {e}")
            return []

    async def get_events_for_revision(
        self,
        artifact_uid: str,
        revision_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get all events for a revision with actor/subject relationships.

        Used by graph_upsert worker.

        Args:
            artifact_uid: Artifact UID
            revision_id: Revision ID

        Returns:
            List of event dicts with actor and subject entity IDs
        """
        events_query = """
        SELECT event_id, category, narrative, event_time, confidence
        FROM semantic_event
        WHERE artifact_uid = $1 AND revision_id = $2
        """

        try:
            events = await self.pg.fetch_all(events_query, artifact_uid, revision_id)

            result = []
            for event in events:
                event_dict = dict(event)
                event_dict["artifact_uid"] = artifact_uid
                event_dict["revision_id"] = revision_id

                # Get actors
                actors_query = """
                SELECT entity_id, role FROM event_actor WHERE event_id = $1
                """
                actors = await self.pg.fetch_all(actors_query, event["event_id"])
                event_dict["actors"] = [dict(a) for a in actors]

                # Get subjects
                subjects_query = """
                SELECT entity_id FROM event_subject WHERE event_id = $1
                """
                subjects = await self.pg.fetch_all(subjects_query, event["event_id"])
                event_dict["subjects"] = [dict(s) for s in subjects]

                result.append(event_dict)

            return result

        except Exception as e:
            logger.error(f"Failed to get events for revision: {e}")
            return []

    async def get_uncertain_entity_pairs(
        self,
        artifact_uid: str,
        revision_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get uncertain entity pairs that need POSSIBLY_SAME edges.

        These are entities with needs_review=true that were first seen
        in this revision and have embedding similarity > threshold with
        other entities.

        Args:
            artifact_uid: Artifact UID
            revision_id: Revision ID

        Returns:
            List of entity pair dicts
        """
        # Note: This is a simplified version. In practice, the entity resolution
        # service tracks uncertain pairs during resolution.
        query = """
        SELECT e1.entity_id AS entity_a_id,
               e2.entity_id AS entity_b_id,
               1 - (e1.context_embedding <=> e2.context_embedding) AS similarity
        FROM entity e1
        JOIN entity e2 ON e1.entity_type = e2.entity_type
                      AND e1.entity_id < e2.entity_id
        WHERE e1.needs_review = true
          AND e1.first_seen_artifact_uid = $1
          AND e1.first_seen_revision_id = $2
          AND e1.context_embedding IS NOT NULL
          AND e2.context_embedding IS NOT NULL
          AND (e1.context_embedding <=> e2.context_embedding) < 0.20
        ORDER BY similarity DESC
        LIMIT 10
        """

        try:
            rows = await self.pg.fetch_all(query, artifact_uid, revision_id)
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get uncertain entity pairs: {e}")
            return []
