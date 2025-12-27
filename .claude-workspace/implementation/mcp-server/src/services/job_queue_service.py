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

        Args:
            worker_id: Worker ID claiming the job

        Returns:
            Job dict or None if no jobs available
        """
        try:
            # Atomic claim in transaction
            async with self.pg.acquire() as conn:
                async with conn.transaction():
                    # Select one pending job
                    select_query = """
                    SELECT job_id, artifact_uid, revision_id, attempts
                    FROM event_jobs
                    WHERE status = 'PENDING'
                      AND next_run_at <= now()
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """

                    row = await conn.fetchrow(select_query)

                    if not row:
                        return None

                    job_id = row["job_id"]

                    # Update to PROCESSING
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

                    logger.info(f"Worker {worker_id} claimed job {job_id}")

                    return {
                        "job_id": str(job_id),
                        "artifact_uid": row["artifact_uid"],
                        "revision_id": row["revision_id"],
                        "attempts": row["attempts"] + 1
                    }

        except Exception as e:
            logger.error(f"Failed to claim job: {e}")
            raise

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
