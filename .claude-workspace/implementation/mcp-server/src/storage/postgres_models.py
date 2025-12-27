"""
Data models for V3 Postgres tables.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


@dataclass
class ArtifactRevision:
    """Immutable artifact revision record."""
    artifact_uid: str
    revision_id: str
    artifact_id: str  # ChromaDB reference
    artifact_type: str
    source_system: str
    source_id: str
    source_ts: Optional[datetime]
    content_hash: str
    token_count: int
    is_chunked: bool
    chunk_count: int
    sensitivity: str
    visibility_scope: str
    retention_policy: str
    is_latest: bool
    ingested_at: datetime
    # Source metadata for authority/credibility reasoning
    title: Optional[str] = None
    document_date: Optional[str] = None
    source_type: Optional[str] = None
    document_status: Optional[str] = None
    author_title: Optional[str] = None
    distribution_scope: Optional[str] = None


@dataclass
class EventJob:
    """Async job queue record."""
    job_id: UUID
    job_type: str
    artifact_uid: str
    revision_id: str
    status: str  # PENDING, PROCESSING, DONE, FAILED
    attempts: int
    max_attempts: int
    next_run_at: datetime
    locked_at: Optional[datetime]
    locked_by: Optional[str]
    last_error_code: Optional[str]
    last_error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class SemanticEvent:
    """Structured semantic event."""
    event_id: UUID
    artifact_uid: str
    revision_id: str
    category: str  # Commitment, Decision, etc.
    event_time: Optional[datetime]
    narrative: str
    subject_json: Dict[str, Any]  # {"type": "...", "ref": "..."}
    actors_json: List[Dict[str, str]]  # [{"ref": "...", "role": "..."}]
    confidence: float
    extraction_run_id: UUID
    created_at: datetime


@dataclass
class EventEvidence:
    """Evidence span linking event to artifact text."""
    evidence_id: UUID
    event_id: UUID
    artifact_uid: str
    revision_id: str
    chunk_id: Optional[str]
    start_char: int
    end_char: int
    quote: str
    created_at: datetime


# Response models for API

@dataclass
class EventWithEvidence:
    """Event with evidence for API responses."""
    event_id: str
    artifact_uid: str
    revision_id: str
    category: str
    event_time: Optional[str]
    narrative: str
    subject: Dict[str, Any]
    actors: List[Dict[str, str]]
    confidence: float
    evidence: Optional[List[Dict[str, Any]]] = None
    extraction_run_id: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class JobStatus:
    """Job status for API responses."""
    job_id: str
    artifact_uid: str
    revision_id: str
    status: str
    attempts: int
    max_attempts: int
    created_at: str
    updated_at: str
    locked_by: Optional[str] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    next_run_at: Optional[str] = None


# Helper functions for model conversion

def event_to_dict(event: SemanticEvent, evidence: Optional[List[EventEvidence]] = None) -> Dict[str, Any]:
    """Convert SemanticEvent to API response dict."""
    result = {
        "event_id": str(event.event_id),
        "artifact_uid": event.artifact_uid,
        "revision_id": event.revision_id,
        "category": event.category,
        "event_time": event.event_time.isoformat() if event.event_time else None,
        "narrative": event.narrative,
        "subject": event.subject_json,
        "actors": event.actors_json,
        "confidence": event.confidence,
        "extraction_run_id": str(event.extraction_run_id),
        "created_at": event.created_at.isoformat()
    }

    if evidence is not None:
        result["evidence"] = [
            {
                "evidence_id": str(ev.evidence_id),
                "quote": ev.quote,
                "start_char": ev.start_char,
                "end_char": ev.end_char,
                "chunk_id": ev.chunk_id
            }
            for ev in evidence
        ]

    return result


def job_to_dict(job: EventJob) -> Dict[str, Any]:
    """Convert EventJob to API response dict."""
    return {
        "job_id": str(job.job_id),
        "artifact_uid": job.artifact_uid,
        "revision_id": job.revision_id,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "locked_by": job.locked_by,
        "last_error_code": job.last_error_code,
        "last_error_message": job.last_error_message,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None
    }
