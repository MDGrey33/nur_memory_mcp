"""
V6 Event Tools - Internal functions for semantic event operations.

Used internally by recall() for event search and retrieval.
NOT exposed as MCP tools.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
import re


def parse_iso8601(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse ISO8601 datetime string to Python datetime for asyncpg.

    Handles formats like:
    - 2024-01-01T00:00:00Z
    - 2024-01-01T00:00:00+00:00
    - 2024-01-01
    """
    if not date_str:
        return None
    try:
        # Handle 'Z' suffix for UTC
        normalized = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        # Try date-only format
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None

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

        # Build query - join with artifact_revision for source metadata
        # Note: Only reference columns that exist in artifact_revision schema
        query_parts = ["""
            SELECT e.*,
                   ar.artifact_type as source_artifact_type,
                   ar.source_system as source_source_system,
                   ar.source_id as source_source_id,
                   ar.source_ts as source_ts,
                   ar.ingested_at as source_ingested_at
            FROM semantic_event e
            LEFT JOIN artifact_revision ar ON e.artifact_uid = ar.artifact_uid AND e.revision_id = ar.revision_id
            WHERE 1=1
        """]
        params = []
        param_idx = 1

        filters_applied = {}

        if category:
            query_parts.append(f"AND e.category = ${param_idx}")
            params.append(category)
            param_idx += 1
            filters_applied["category"] = category

        if time_from:
            parsed_time_from = parse_iso8601(time_from)
            if parsed_time_from:
                query_parts.append(f"AND e.event_time >= ${param_idx}")
                params.append(parsed_time_from)
                param_idx += 1
                filters_applied["time_from"] = time_from

        if time_to:
            parsed_time_to = parse_iso8601(time_to)
            if parsed_time_to:
                query_parts.append(f"AND e.event_time <= ${param_idx}")
                params.append(parsed_time_to)
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

        # Execute query (primary: AND semantics via plainto_tsquery)
        sql = " ".join(query_parts)
        events = await pg_client.fetch_all(sql, *params)

        # Fallback: if query returns nothing, retry with OR semantics to improve recall.
        # This helps queries that contain extra terms not present in the narrative (e.g., "API delivery")
        # while still matching the core event ("security audit risk").
        if query and not events:
            try:
                # Extract safe tokens and build a websearch query with OR.
                tokens = [t for t in re.findall(r"[A-Za-z]+", query) if len(t) >= 3]
                tokens = tokens[:12]  # cap to keep tsquery reasonable
                if tokens:
                    or_query = " OR ".join(tokens)

                    # Rebuild query using websearch_to_tsquery for safer parsing.
                    # Note: Only reference columns that exist in artifact_revision schema
                    query_parts_or = ["""
                        SELECT e.*,
                               ar.artifact_type as source_artifact_type,
                               ar.source_system as source_source_system,
                               ar.source_id as source_source_id,
                               ar.source_ts as source_ts,
                               ar.ingested_at as source_ingested_at
                        FROM semantic_event e
                        LEFT JOIN artifact_revision ar ON e.artifact_uid = ar.artifact_uid AND e.revision_id = ar.revision_id
                        WHERE 1=1
                    """]
                    params_or = []
                    param_idx_or = 1

                    # Reapply the same non-query filters
                    if category:
                        query_parts_or.append(f"AND e.category = ${param_idx_or}")
                        params_or.append(category)
                        param_idx_or += 1
                    if time_from:
                        parsed_time_from = parse_iso8601(time_from)
                        if parsed_time_from:
                            query_parts_or.append(f"AND e.event_time >= ${param_idx_or}")
                            params_or.append(parsed_time_from)
                            param_idx_or += 1
                    if time_to:
                        parsed_time_to = parse_iso8601(time_to)
                        if parsed_time_to:
                            query_parts_or.append(f"AND e.event_time <= ${param_idx_or}")
                            params_or.append(parsed_time_to)
                            param_idx_or += 1
                    if artifact_uid:
                        query_parts_or.append(f"AND e.artifact_uid = ${param_idx_or}")
                        params_or.append(artifact_uid)
                        param_idx_or += 1

                    query_parts_or.append(
                        f"AND to_tsvector('english', e.narrative) @@ websearch_to_tsquery('english', ${param_idx_or})"
                    )
                    params_or.append(or_query)
                    param_idx_or += 1

                    query_parts_or.append("ORDER BY e.event_time DESC NULLS LAST, e.created_at DESC")
                    query_parts_or.append(f"LIMIT ${param_idx_or}")
                    params_or.append(limit)

                    sql_or = " ".join(query_parts_or)
                    events = await pg_client.fetch_all(sql_or, *params_or)
            except Exception as _:
                # If fallback fails, keep original empty set.
                pass

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
            # Build source context for authority/credibility reasoning
            source_context = {
                "artifact_uid": event["artifact_uid"],
                "revision_id": event["revision_id"],
                "artifact_type": event.get("source_artifact_type"),
                "source_system": event.get("source_source_system"),
                "source_id": event.get("source_source_id"),
                "source_ts": event["source_ts"].isoformat() if event.get("source_ts") else None,
                "ingested_at": event["source_ingested_at"].isoformat() if event.get("source_ingested_at") else None
            }

            formatted_events.append({
                "event_id": str(event["event_id"]),
                "category": event["category"],
                "event_time": event["event_time"].isoformat() if event.get("event_time") else None,
                "created_at": event["created_at"].isoformat() if event.get("created_at") else None,
                "narrative": event["narrative"],
                "subject": event["subject_json"],
                "actors": event["actors_json"],
                "confidence": event["confidence"],
                "source": source_context,
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
        # Fetch event with source metadata
        # Note: Only reference columns that exist in artifact_revision schema
        event_sql = """
            SELECT e.*,
                   ar.artifact_type as source_artifact_type,
                   ar.source_system as source_source_system,
                   ar.source_id as source_source_id,
                   ar.source_ts as source_ts,
                   ar.ingested_at as source_ingested_at
            FROM semantic_event e
            LEFT JOIN artifact_revision ar ON e.artifact_uid = ar.artifact_uid AND e.revision_id = ar.revision_id
            WHERE e.event_id = $1
        """

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

        # Build source context for authority/credibility reasoning
        source_context = {
            "artifact_uid": event["artifact_uid"],
            "revision_id": event["revision_id"],
            "artifact_type": event.get("source_artifact_type"),
            "source_system": event.get("source_source_system"),
            "source_id": event.get("source_source_id"),
            "source_ts": event["source_ts"].isoformat() if event.get("source_ts") else None,
            "ingested_at": event["source_ingested_at"].isoformat() if event.get("source_ingested_at") else None
        }

        return {
            "event_id": str(event["event_id"]),
            "category": event["category"],
            "event_time": event["event_time"].isoformat() if event.get("event_time") else None,
            "created_at": event["created_at"].isoformat(),
            "narrative": event["narrative"],
            "subject": event["subject_json"],
            "actors": event["actors_json"],
            "confidence": event["confidence"],
            "source": source_context,
            "evidence": evidence,
            "extraction_run_id": str(event["extraction_run_id"])
        }

    except Exception as e:
        logger.error(f"event_get error: {e}", exc_info=True)
        return {
            "error": f"Failed to get event: {str(e)}",
            "error_code": "INTERNAL_ERROR"
        }


