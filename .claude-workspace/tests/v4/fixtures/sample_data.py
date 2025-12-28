"""
V4 Test Fixtures - Sample Data.

Provides:
- Sample documents with known entities
- Pre-seeded entity database fixtures
- Mock LLM responses for entity dedup
- Mock embedding service fixtures
"""

from uuid import uuid4, UUID
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import json


# =============================================================================
# Sample Documents
# =============================================================================

MEETING_NOTES_DOCUMENT = {
    "artifact_uid": "meeting_001",
    "revision_id": "rev_001",
    "artifact_id": "art_meeting_001",
    "content": """
Meeting Notes - March 15, 2024
Project: Product Launch Planning
Location: Conference Room A

Attendees:
- Alice Chen (Engineering Manager, Acme Corp) - achen@acme.com
- Bob Smith (Senior Designer) - bob@design.co
- Carol Davis (Product Lead)

1. Status Updates

Alice Chen provided an update on the engineering timeline. She mentioned that the
backend services are 80% complete. The team is on track to meet the Q2 deadline.

Bob presented the new design mockups for the user dashboard. The designs have
been approved by stakeholders.

Carol outlined the marketing strategy. She confirmed the launch date is set for
April 15th.

2. Decisions Made

DECISION: The team decided to adopt a freemium pricing model for the initial launch.
This was proposed by Alice and seconded by Carol.

DECISION: Bob will lead the design review process going forward.

3. Action Items

- Alice will finalize the API documentation by Friday, March 22
- Bob to complete high-fidelity prototypes by March 25
- Carol to schedule user interviews for next week

4. Next Steps

The next meeting is scheduled for March 22, 2024.

Meeting adjourned at 3:30 PM.

Notes taken by Carol Davis
Distributed to: Engineering, Design, Product teams
""",
    "expected_entities": [
        {
            "surface_form": "Alice Chen",
            "type": "person",
            "role": "Engineering Manager",
            "organization": "Acme Corp",
            "email": "achen@acme.com"
        },
        {
            "surface_form": "Bob Smith",
            "type": "person",
            "role": "Senior Designer",
            "email": "bob@design.co"
        },
        {
            "surface_form": "Carol Davis",
            "type": "person",
            "role": "Product Lead"
        },
        {
            "surface_form": "Acme Corp",
            "type": "org"
        }
    ],
    "expected_events": [
        {"category": "Decision", "narrative_contains": "freemium"},
        {"category": "Decision", "narrative_contains": "design review"},
        {"category": "Commitment", "narrative_contains": "API documentation"},
        {"category": "Commitment", "narrative_contains": "prototypes"},
        {"category": "Commitment", "narrative_contains": "user interviews"}
    ]
}


PROJECT_UPDATE_DOCUMENT = {
    "artifact_uid": "update_001",
    "revision_id": "rev_001",
    "artifact_id": "art_update_001",
    "content": """
Project Status Update - March 18, 2024
From: A. Chen
To: Engineering Team

Team,

Quick update on our progress:

1. Backend Status
The authentication service is now complete. Great work by the team!
Alice Chen finished the review yesterday.

2. Blockers
We're still waiting on the security audit results from the InfoSec team.
Expected by end of week.

3. Upcoming
- Code freeze scheduled for March 25
- QA testing begins March 26
- Production deployment target: April 1

Please reach out if you have questions.

Best,
Alice
""",
    "expected_aliases": ["Alice Chen", "A. Chen", "Alice"],  # Same person
    "expected_entity_count": 1  # Should merge to single entity
}


CROSS_ORG_DOCUMENT = {
    "artifact_uid": "crossorg_001",
    "revision_id": "rev_001",
    "artifact_id": "art_crossorg_001",
    "content": """
Cross-Team Collaboration Meeting

Participants:
- Alice Chen (Engineer at Acme Corp)
- Alice Chen (Designer at OtherCorp)

Meeting Summary:

The Engineer Alice Chen from Acme presented the technical architecture.
The Designer Alice Chen from OtherCorp showed the UI mockups.

Both Alice's agreed that the design and implementation are aligned.

Key Points:
- Technical Alice (Acme) will own the backend implementation
- Designer Alice (OtherCorp) will own the UX specifications
""",
    "expected_entity_count": 2,  # Different people, should NOT merge
    "disambiguation_hints": ["different organizations", "different roles"]
}


MINIMAL_CONTEXT_DOCUMENT = {
    "artifact_uid": "minimal_001",
    "revision_id": "rev_001",
    "artifact_id": "art_minimal_001",
    "content": """
Quick note:

A. Chen mentioned that the deadline is next week.
Alice C. will follow up with the team.
""",
    "expected_uncertain_match": True,  # Insufficient context
    "entities": [
        {"surface_form": "A. Chen", "context_clues": {}},
        {"surface_form": "Alice C.", "context_clues": {}}
    ]
}


LARGE_DOCUMENT_FOR_CHUNKING = {
    "artifact_uid": "large_001",
    "revision_id": "rev_001",
    "artifact_id": "art_large_001",
    "content": """
# Technical Design Document

## Overview

This document describes the architecture for the new notification system.

Alice Chen (Tech Lead) has approved this design.

## Section 1: Requirements

The system must support:
- Real-time notifications
- Email digests
- Mobile push notifications
- Slack integration

Bob Smith (Backend Engineer) will implement the core service.

## Section 2: Architecture

The notification service uses an event-driven architecture.

### Components

1. Event Producer
   - Captures system events
   - Publishes to message queue

2. Event Consumer
   - Processes events asynchronously
   - Routes to appropriate channels

3. Delivery Service
   - Handles actual delivery
   - Supports multiple providers

### Data Flow

Events flow from producers to consumers via Kafka.

## Section 3: Implementation Plan

### Phase 1: Core Service (Week 1-2)
- Set up Kafka infrastructure
- Implement event producer
- Create consumer framework

Alice will lead this phase.

### Phase 2: Integrations (Week 3-4)
- Email provider integration
- Push notification setup
- Slack webhook configuration

Bob will lead integrations.

### Phase 3: Testing (Week 5)
- Load testing
- Integration testing
- User acceptance testing

## Section 4: Security Considerations

All notifications must be encrypted in transit.
PII must be handled according to GDPR requirements.

Carol Davis (Security Engineer) has reviewed this section.

## Section 5: Timeline

- Design Review: March 15
- Implementation Start: March 18
- Testing Complete: April 12
- Production Launch: April 15

## Appendix

Contact: alice.chen@acme.com, bob.smith@acme.com

""" * 3,  # Repeat to ensure chunking
    "expected_chunk_count": 3,  # Approximate
    "entities_across_chunks": ["Alice Chen", "Bob Smith", "Carol Davis"]
}


# =============================================================================
# Pre-seeded Entity Database
# =============================================================================

@dataclass
class SeedEntity:
    """Pre-seeded entity for testing."""
    entity_id: UUID
    entity_type: str
    canonical_name: str
    normalized_name: str
    role: Optional[str] = None
    organization: Optional[str] = None
    email: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    embedding: List[float] = field(default_factory=list)


def get_seeded_entities() -> List[SeedEntity]:
    """Get a set of pre-seeded entities for testing."""
    return [
        SeedEntity(
            entity_id=UUID("11111111-1111-1111-1111-111111111111"),
            entity_type="person",
            canonical_name="Alice Chen",
            normalized_name="alice chen",
            role="Engineering Manager",
            organization="Acme Corp",
            email="achen@acme.com",
            aliases=["Alice", "A. Chen"],
            embedding=[0.1] * 3072
        ),
        SeedEntity(
            entity_id=UUID("22222222-2222-2222-2222-222222222222"),
            entity_type="person",
            canonical_name="Bob Smith",
            normalized_name="bob smith",
            role="Senior Designer",
            organization="OtherCorp",
            email="bob@othercorp.com",
            aliases=["Bob", "B. Smith"],
            embedding=[0.2] * 3072
        ),
        SeedEntity(
            entity_id=UUID("33333333-3333-3333-3333-333333333333"),
            entity_type="person",
            canonical_name="Carol Davis",
            normalized_name="carol davis",
            role="Product Lead",
            organization="Acme Corp",
            email="carol@acme.com",
            aliases=["Carol", "C. Davis"],
            embedding=[0.3] * 3072
        ),
        SeedEntity(
            entity_id=UUID("44444444-4444-4444-4444-444444444444"),
            entity_type="org",
            canonical_name="Acme Corp",
            normalized_name="acme corp",
            aliases=["Acme", "Acme Corporation"],
            embedding=[0.4] * 3072
        ),
        SeedEntity(
            entity_id=UUID("55555555-5555-5555-5555-555555555555"),
            entity_type="org",
            canonical_name="OtherCorp",
            normalized_name="othercorp",
            aliases=["Other Corp"],
            embedding=[0.5] * 3072
        )
    ]


def get_seeded_entity_db_rows() -> List[Dict[str, Any]]:
    """Convert seeded entities to database row format."""
    return [
        {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "normalized_name": entity.normalized_name,
            "role": entity.role,
            "organization": entity.organization,
            "email": entity.email,
            "first_seen_artifact_uid": "seed_doc",
            "first_seen_revision_id": "seed_rev",
            "needs_review": False,
            "distance": 0.0  # Exact match
        }
        for entity in get_seeded_entities()
    ]


# =============================================================================
# Mock LLM Responses for Entity Dedup
# =============================================================================

class MockLLMResponses:
    """Mock LLM responses for entity deduplication."""

    @staticmethod
    def same_entity_response(canonical_name: str = "Alice Chen") -> str:
        """Response when LLM determines entities are the same."""
        return json.dumps({
            "decision": "same",
            "canonical_name": canonical_name,
            "reason": "Context clues indicate same person: matching organization and role"
        })

    @staticmethod
    def different_entity_response() -> str:
        """Response when LLM determines entities are different."""
        return json.dumps({
            "decision": "different",
            "canonical_name": "",
            "reason": "Different organizations and roles suggest different people"
        })

    @staticmethod
    def uncertain_entity_response() -> str:
        """Response when LLM cannot determine."""
        return json.dumps({
            "decision": "uncertain",
            "canonical_name": "",
            "reason": "Insufficient context to determine if entities are the same"
        })

    @staticmethod
    def extraction_response_with_entities() -> str:
        """Mock extraction response with events and entities."""
        return json.dumps({
            "events": [
                {
                    "category": "Decision",
                    "narrative": "Team decided on pricing model",
                    "event_time": "2024-03-15T14:30:00Z",
                    "subject": {"type": "project", "ref": "pricing"},
                    "actors": [{"ref": "Alice Chen", "role": "owner"}],
                    "confidence": 0.95,
                    "evidence": [
                        {"quote": "decided on freemium", "start_char": 100, "end_char": 120}
                    ]
                }
            ],
            "entities_mentioned": [
                {
                    "surface_form": "Alice Chen",
                    "canonical_suggestion": "Alice Chen",
                    "type": "person",
                    "context_clues": {
                        "role": "Engineering Manager",
                        "org": "Acme Corp"
                    },
                    "aliases_in_doc": ["Alice"],
                    "confidence": 0.95,
                    "start_char": 50,
                    "end_char": 60
                }
            ]
        })


# =============================================================================
# Sample Events
# =============================================================================

def get_sample_events() -> List[Dict[str, Any]]:
    """Get sample semantic events for testing."""
    alice_id = UUID("11111111-1111-1111-1111-111111111111")
    bob_id = UUID("22222222-2222-2222-2222-222222222222")

    return [
        {
            "event_id": UUID("aaaa1111-1111-1111-1111-111111111111"),
            "artifact_uid": "meeting_001",
            "revision_id": "rev_001",
            "category": "Decision",
            "event_time": datetime(2024, 3, 15, 14, 30),
            "narrative": "Team decided to adopt freemium pricing model",
            "subject_json": {"type": "project", "ref": "pricing-model"},
            "actors_json": [{"ref": "Alice Chen", "role": "owner"}],
            "confidence": 0.95,
            "actor_entity_ids": [alice_id],
            "subject_entity_ids": []
        },
        {
            "event_id": UUID("aaaa2222-2222-2222-2222-222222222222"),
            "artifact_uid": "meeting_001",
            "revision_id": "rev_001",
            "category": "Commitment",
            "event_time": datetime(2024, 3, 15, 15, 0),
            "narrative": "Alice committed to finalizing API docs by Friday",
            "subject_json": {"type": "object", "ref": "API-documentation"},
            "actors_json": [{"ref": "Alice Chen", "role": "owner"}],
            "confidence": 0.90,
            "actor_entity_ids": [alice_id],
            "subject_entity_ids": []
        },
        {
            "event_id": UUID("aaaa3333-3333-3333-3333-333333333333"),
            "artifact_uid": "meeting_001",
            "revision_id": "rev_001",
            "category": "Commitment",
            "event_time": datetime(2024, 3, 15, 15, 15),
            "narrative": "Bob committed to complete prototypes by March 25",
            "subject_json": {"type": "object", "ref": "prototypes"},
            "actors_json": [{"ref": "Bob Smith", "role": "owner"}],
            "confidence": 0.85,
            "actor_entity_ids": [bob_id],
            "subject_entity_ids": []
        }
    ]


def get_sample_event_actors() -> List[Dict[str, Any]]:
    """Get sample event_actor relationships."""
    events = get_sample_events()
    actors = []

    for event in events:
        for actor_id in event.get("actor_entity_ids", []):
            actors.append({
                "event_id": event["event_id"],
                "entity_id": actor_id,
                "role": event["actors_json"][0]["role"] if event["actors_json"] else "other"
            })

    return actors


# =============================================================================
# Graph Test Data
# =============================================================================

def get_graph_test_data() -> Dict[str, Any]:
    """Get test data for graph operations."""
    alice_id = UUID("11111111-1111-1111-1111-111111111111")
    bob_id = UUID("22222222-2222-2222-2222-222222222222")
    event1_id = UUID("aaaa1111-1111-1111-1111-111111111111")
    event2_id = UUID("aaaa2222-2222-2222-2222-222222222222")

    return {
        "entities": [
            {
                "entity_id": alice_id,
                "canonical_name": "Alice Chen",
                "entity_type": "person",
                "role": "Engineering Manager",
                "organization": "Acme Corp"
            },
            {
                "entity_id": bob_id,
                "canonical_name": "Bob Smith",
                "entity_type": "person",
                "role": "Senior Designer",
                "organization": "OtherCorp"
            }
        ],
        "events": [
            {
                "event_id": event1_id,
                "category": "Decision",
                "narrative": "Pricing decision",
                "artifact_uid": "doc_001",
                "revision_id": "rev_001",
                "event_time": "2024-03-15T14:30:00Z",
                "confidence": 0.95
            },
            {
                "event_id": event2_id,
                "category": "Commitment",
                "narrative": "API docs commitment",
                "artifact_uid": "doc_001",
                "revision_id": "rev_001",
                "event_time": "2024-03-15T15:00:00Z",
                "confidence": 0.90
            }
        ],
        "edges": {
            "acted_in": [
                {"entity_id": alice_id, "event_id": event1_id, "role": "owner"},
                {"entity_id": alice_id, "event_id": event2_id, "role": "owner"}
            ],
            "about": [],
            "possibly_same": []
        }
    }


# =============================================================================
# Embedding Test Data
# =============================================================================

def get_deterministic_embedding(text: str, dims: int = 3072) -> List[float]:
    """
    Generate a deterministic embedding for testing.

    Uses text hash to create reproducible embeddings.
    """
    hash_val = hash(text)
    base = (hash_val % 1000) / 1000.0

    embedding = [base + (i * 0.0001) for i in range(dims)]

    # Normalize
    magnitude = sum(x**2 for x in embedding) ** 0.5
    return [x / magnitude for x in embedding]


def get_similar_embeddings(count: int = 3) -> List[List[float]]:
    """Generate similar embeddings for testing threshold behavior."""
    base = get_deterministic_embedding("base_entity")

    embeddings = [base]
    for i in range(1, count):
        # Add small perturbation
        perturbed = [x + (0.001 * i) for x in base]
        magnitude = sum(x**2 for x in perturbed) ** 0.5
        normalized = [x / magnitude for x in perturbed]
        embeddings.append(normalized)

    return embeddings


def get_dissimilar_embeddings(count: int = 3) -> List[List[float]]:
    """Generate dissimilar embeddings for testing."""
    embeddings = []
    for i in range(count):
        embedding = get_deterministic_embedding(f"entity_{i}")
        embeddings.append(embedding)
    return embeddings
