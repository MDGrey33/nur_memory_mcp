"""
V3 MCP Tools for semantic events.

Provides 5 new tools:
- event_search: Query events with filters
- event_get: Get single event by ID
- event_list_for_revision: List events for artifact revision
- event_reextract: Force re-extraction
- job_status: Check job status
"""

import logging
from typing import Optional, List, Dict, Any
from uuid import UUID

logger = logging.getLogger("event_tools")


# Event categories (for validation)
EVENT_CATEGORIES = [
    "Commitment",
    "Execution",
    "Decision",
    "Collaboration",
    "QualityRisk",
    "Feedback",
    "Change",
    "Stakeholder"
]


async def event_search(
    pg_client,
    query: Optional[str] = None,
    limit: int = 20,
    category: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    artifact_uid: Optional[str] = None,
    include_evidence: bool = True
) -> dict:
    """
    Search semantic events with structured filters.

    Args:
        pg_client: Postgres client instance
        query: Full-text search on narrative (optional)
        limit: Maximum results (1-100)
        category: Filter by event category
        time_from: Filter events after this time (ISO8601)
        time_to: Filter events before this time (ISO8601)
        artifact_uid: Filter to specific artifact
        include_evidence: Include evidence quotes

    Returns:
        Dict with events list and metadata
    """
    try:
        # Validate inputs
        if limit < 1 or limit > 100:
            return {
                "error": "Invalid limit. Must be between 1 and 100",
                "error_code": "INVALID_PARAMETER"
            }

        if category and category not in EVENT_CATEGORIES:
            return {
                "error": f"Invalid category: {category}. Must be one of: {', '.join(EVENT_CATEGORIES)}",
                "error_code": "INVALID_CATEGORY",
                "details": {"valid_categories": EVENT_CATEGORIES}
            }

        # Build query
        query_parts = ["SELECT e.* FROM semantic_event e WHERE 1=1"]
        params = []
        param_idx = 1

        filters_applied = {}

        if category:
            query_parts.append(f"AND e.category = ${param_idx}")
            params.append(category)
            param_idx += 1
            filters_applied["category"] = category

        if time_from:
            query_parts.append(f"AND e.event_time >= ${param_idx}")
            params.append(time_from)
            param_idx += 1
            filters_applied["time_from"] = time_from

        if time_to:
            query_parts.append(f"AND e.event_time <= ${param_idx}")
            params.append(time_to)
            param_idx += 1
            filters_applied["time_to"] = time_to

        if artifact_uid:
            query_parts.append(f"AND e.artifact_uid = ${param_idx}")
            params.append(artifact_uid)
            param_idx += 1
            filters_applied["artifact_uid"] = artifact_uid

        if query:
            # Use plainto_tsquery for safe full-text search (prevents SQL injection)
            query_parts.append(f"AND to_tsvector('english', e.narrative) @@ plainto_tsquery('english', ${param_idx})")
            params.append(query)
            param_idx += 1
            filters_applied["query"] = query

        # Order and limit
        query_parts.append("ORDER BY e.event_time DESC NULLS LAST, e.created_at DESC")
        query_parts.append(f"LIMIT ${param_idx}")
        params.append(limit)

        # Execute query
        sql = " ".join(query_parts)
        events = await pg_client.fetch_all(sql, *params)

        # Batch fetch evidence if requested (avoids N+1 query)
        evidence_map = {}
        if include_evidence and events:
            event_ids = [event["event_id"] for event in events]
            # Generate parameterized placeholders for IN clause
            placeholders = ", ".join(f"${i+1}" for i in range(len(event_ids)))
            evidence_sql = f"""
            SELECT event_id, evidence_id, quote, start_char, end_char, chunk_id
            FROM event_evidence
            WHERE event_id IN ({placeholders})
            ORDER BY event_id, start_char
            """
            evidence_rows = await pg_client.fetch_all(evidence_sql, *event_ids)

            # Group evidence by event_id
            for ev in evidence_rows:
                event_id = ev["event_id"]
                if event_id not in evidence_map:
                    evidence_map[event_id] = []
                evidence_map[event_id].append({
                    "evidence_id": str(ev["evidence_id"]),
                    "quote": ev["quote"],
                    "start_char": ev["start_char"],
                    "end_char": ev["end_char"],
                    "chunk_id": ev["chunk_id"]
                })

        # Attach evidence to events
        if include_evidence:
            for event in events:
                event["evidence"] = evidence_map.get(event["event_id"], [])

        # Format response
        formatted_events = []
        for event in events:
            formatted_events.append({
                "event_id": str(event["event_id"]),
                "artifact_uid": event["artifact_uid"],
                "revision_id": event["revision_id"],
                "category": event["category"],
                "event_time": event["event_time"].isoformat() if event.get("event_time") else None,
                "narrative": event["narrative"],
                "subject": event["subject_json"],
                "actors": event["actors_json"],
                "confidence": event["confidence"],
                "evidence": event.get("evidence", []) if include_evidence else None
            })

        return {
            "events": formatted_events,
            "total": len(formatted_events),
            "filters_applied": filters_applied
        }

    except Exception as e:
        logger.error(f"event_search error: {e}", exc_info=True)
        return {
            "error": f"Search failed: {str(e)}",
            "error_code": "INTERNAL_ERROR"
        }


async def event_get(
    pg_client,
    event_id: str
) -> dict:
    """
    Get a single event by ID with all evidence.

    Args:
        pg_client: Postgres client instance
        event_id: Event UUID

    Returns:
        Event dict with evidence
    """
    try:
        # Fetch event
        event_sql = "SELECT * FROM semantic_event WHERE event_id = $1"

        try:
            event_uuid = UUID(event_id.replace("evt_", ""))
        except ValueError:
            return {
                "error": f"Invalid event_id format: {event_id}",
                "error_code": "INVALID_PARAMETER"
            }

        event = await pg_client.fetch_one(event_sql, event_uuid)

        if not event:
            return {
                "error": f"Event {event_id} not found",
                "error_code": "NOT_FOUND"
            }

        # Fetch evidence
        evidence_sql = """
        SELECT evidence_id, quote, start_char, end_char, chunk_id
        FROM event_evidence
        WHERE event_id = $1
        ORDER BY start_char
        """
        evidence_rows = await pg_client.fetch_all(evidence_sql, event_uuid)

        evidence = [
            {
                "evidence_id": str(ev["evidence_id"]),
                "quote": ev["quote"],
                "start_char": ev["start_char"],
                "end_char": ev["end_char"],
                "chunk_id": ev["chunk_id"]
            }
            for ev in evidence_rows
        ]

        return {
            "event_id": str(event["event_id"]),
            "artifact_uid": event["artifact_uid"],
            "revision_id": event["revision_id"],
            "category": event["category"],
            "event_time": event["event_time"].isoformat() if event.get("event_time") else None,
            "narrative": event["narrative"],
            "subject": event["subject_json"],
            "actors": event["actors_json"],
            "confidence": event["confidence"],
            "evidence": evidence,
            "extraction_run_id": str(event["extraction_run_id"]),
            "created_at": event["created_at"].isoformat()
        }

    except Exception as e:
        logger.error(f"event_get error: {e}", exc_info=True)
        return {
            "error": f"Failed to get event: {str(e)}",
            "error_code": "INTERNAL_ERROR"
        }


async def event_list_for_revision(
    pg_client,
    artifact_uid: str,
    revision_id: Optional[str] = None,
    include_evidence: bool = False
) -> dict:
    """
    List all events for an artifact revision.

    Args:
        pg_client: Postgres client instance
        artifact_uid: Artifact UID
        revision_id: Specific revision (defaults to latest)
        include_evidence: Include evidence quotes

    Returns:
        Dict with revision metadata and events list
    """
    try:
        # Resolve revision_id if not provided
        if not revision_id:
            rev_sql = """
            SELECT revision_id, is_latest
            FROM artifact_revision
            WHERE artifact_uid = $1 AND is_latest = true
            LIMIT 1
            """
            rev_row = await pg_client.fetch_one(rev_sql, artifact_uid)

            if not rev_row:
                return {
                    "error": f"Artifact {artifact_uid} not found",
                    "error_code": "NOT_FOUND"
                }

            revision_id = rev_row["revision_id"]
            is_latest = rev_row["is_latest"]
        else:
            # Check if this revision exists
            rev_sql = """
            SELECT is_latest
            FROM artifact_revision
            WHERE artifact_uid = $1 AND revision_id = $2
            """
            rev_row = await pg_client.fetch_one(rev_sql, artifact_uid, revision_id)

            if not rev_row:
                return {
                    "error": f"Revision {revision_id} not found for artifact {artifact_uid}",
                    "error_code": "NOT_FOUND"
                }

            is_latest = rev_row["is_latest"]

        # Fetch events
        events_sql = """
        SELECT * FROM semantic_event
        WHERE artifact_uid = $1 AND revision_id = $2
        ORDER BY event_time DESC NULLS LAST, created_at DESC
        """
        events = await pg_client.fetch_all(events_sql, artifact_uid, revision_id)

        # Batch fetch evidence if requested (avoids N+1 query)
        evidence_map = {}
        if include_evidence and events:
            event_ids = [event["event_id"] for event in events]
            # Generate parameterized placeholders for IN clause
            placeholders = ", ".join(f"${i+1}" for i in range(len(event_ids)))
            evidence_sql = f"""
            SELECT event_id, evidence_id, quote, start_char, end_char, chunk_id
            FROM event_evidence
            WHERE event_id IN ({placeholders})
            ORDER BY event_id, start_char
            """
            evidence_rows = await pg_client.fetch_all(evidence_sql, *event_ids)

            # Group evidence by event_id
            for ev in evidence_rows:
                event_id = ev["event_id"]
                if event_id not in evidence_map:
                    evidence_map[event_id] = []
                evidence_map[event_id].append({
                    "evidence_id": str(ev["evidence_id"]),
                    "quote": ev["quote"],
                    "start_char": ev["start_char"],
                    "end_char": ev["end_char"],
                    "chunk_id": ev["chunk_id"]
                })

        # Attach evidence to events
        if include_evidence:
            for event in events:
                event["evidence"] = evidence_map.get(event["event_id"], [])

        # Format response
        formatted_events = []
        for event in events:
            formatted_events.append({
                "event_id": str(event["event_id"]),
                "category": event["category"],
                "narrative": event["narrative"],
                "event_time": event["event_time"].isoformat() if event.get("event_time") else None,
                "subject": event["subject_json"],
                "actors": event["actors_json"],
                "confidence": event["confidence"],
                "evidence": event.get("evidence") if include_evidence else None
            })

        return {
            "artifact_uid": artifact_uid,
            "revision_id": revision_id,
            "is_latest": is_latest,
            "events": formatted_events,
            "total": len(formatted_events)
        }

    except Exception as e:
        logger.error(f"event_list_for_revision error: {e}", exc_info=True)
        return {
            "error": f"Failed to list events: {str(e)}",
            "error_code": "INTERNAL_ERROR"
        }
