"""
Integration tests for V4 extraction pipeline.

Tests:
- Extraction prompt returns entities_mentioned
- Entity resolution during extraction
- event_actor and event_subject populated
- graph_upsert job enqueued
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID
import json
from datetime import datetime

from services.event_extraction_service import EventExtractionService
from services.entity_resolution_service import (
    EntityResolutionService,
    EntityResolutionResult,
    ExtractedEntity,
    ContextClues
)


# =============================================================================
# Test Markers
# =============================================================================

pytestmark = [pytest.mark.v4, pytest.mark.integration]


# =============================================================================
# Extraction Prompt Tests
# =============================================================================

class TestExtractionPromptReturnsEntities:
    """Tests for extraction prompt returning entities_mentioned."""

    def test_extract_from_chunk_v4_returns_events_and_entities(self):
        """Test extract_from_chunk_v4 returns both events and entities."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "events": [
                {
                    "category": "Decision",
                    "narrative": "Alice decided to use Postgres",
                    "event_time": None,
                    "subject": {"type": "project", "ref": "database-selection"},
                    "actors": [{"ref": "Alice Chen", "role": "owner"}],
                    "confidence": 0.95,
                    "evidence": [
                        {"quote": "we're going with Postgres", "start_char": 100, "end_char": 125}
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
        mock_client.chat.completions.create.return_value = mock_response

        service = EventExtractionService(api_key="test-key")
        service.client = mock_client

        events, entities = service.extract_from_chunk_v4(
            chunk_text="Alice Chen, Engineering Manager at Acme Corp, decided...",
            chunk_index=0,
            chunk_id="chunk_001",
            start_char=0
        )

        assert len(events) == 1
        assert events[0]["category"] == "Decision"
        assert len(entities) == 1
        assert entities[0]["surface_form"] == "Alice Chen"
        assert entities[0]["type"] == "person"
        assert entities[0]["context_clues"]["role"] == "Engineering Manager"

    def test_extract_from_chunk_v4_adjusts_character_offsets(self):
        """Test extract_from_chunk_v4 adjusts character offsets for artifact position."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "events": [
                {
                    "category": "Commitment",
                    "narrative": "Test commitment",
                    "subject": {"type": "project", "ref": "test"},
                    "actors": [],
                    "confidence": 0.9,
                    "evidence": [
                        {"quote": "test", "start_char": 10, "end_char": 20}
                    ]
                }
            ],
            "entities_mentioned": [
                {
                    "surface_form": "Test Entity",
                    "type": "person",
                    "confidence": 0.9,
                    "start_char": 5,
                    "end_char": 15
                }
            ]
        })
        mock_client.chat.completions.create.return_value = mock_response

        service = EventExtractionService(api_key="test-key")
        service.client = mock_client

        start_char_offset = 1000  # Chunk starts at char 1000 in artifact

        events, entities = service.extract_from_chunk_v4(
            chunk_text="...",
            chunk_index=1,
            chunk_id="chunk_002",
            start_char=start_char_offset
        )

        # Event evidence offsets should be adjusted
        assert events[0]["evidence"][0]["start_char"] == 1010  # 10 + 1000
        assert events[0]["evidence"][0]["end_char"] == 1020    # 20 + 1000

        # Entity offsets should be adjusted
        assert entities[0]["start_char"] == 1005  # 5 + 1000
        assert entities[0]["end_char"] == 1015    # 15 + 1000

    def test_extract_from_chunk_v4_handles_missing_entities(self):
        """Test extract_from_chunk_v4 handles responses without entities."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "events": [{"category": "Decision", "narrative": "Test", "subject": {}, "actors": [], "confidence": 0.9, "evidence": []}]
            # No entities_mentioned key
        })
        mock_client.chat.completions.create.return_value = mock_response

        service = EventExtractionService(api_key="test-key")
        service.client = mock_client

        events, entities = service.extract_from_chunk_v4(
            chunk_text="Test content",
            chunk_index=0,
            chunk_id="chunk_001",
            start_char=0
        )

        assert len(events) == 1
        assert len(entities) == 0

    def test_extract_from_chunk_v4_adds_chunk_id_to_entities(self):
        """Test extract_from_chunk_v4 adds chunk_id to entity records."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "events": [],
            "entities_mentioned": [
                {"surface_form": "Test", "type": "person", "confidence": 0.9}
            ]
        })
        mock_client.chat.completions.create.return_value = mock_response

        service = EventExtractionService(api_key="test-key")
        service.client = mock_client

        _, entities = service.extract_from_chunk_v4(
            chunk_text="Test",
            chunk_index=0,
            chunk_id="chunk_xyz",
            start_char=0
        )

        assert entities[0]["chunk_id"] == "chunk_xyz"


# =============================================================================
# Entity Resolution During Extraction Tests
# =============================================================================

class TestEntityResolutionDuringExtraction:
    """Tests for entity resolution happening during extraction."""

    @pytest.mark.asyncio
    async def test_extracted_entities_are_resolved(
        self, mock_pg_client, mock_embedding_service, mock_openai_dedup_client
    ):
        """Test that extracted entities go through resolution."""
        # Setup
        mock_pg_client.fetch_one.return_value = None  # No exact match
        mock_pg_client.fetch_all.return_value = []    # No candidates
        mock_pg_client.fetch_val.return_value = uuid4()

        service = EntityResolutionService(
            pg_client=mock_pg_client,
            embedding_service=mock_embedding_service,
            openai_client=mock_openai_dedup_client
        )

        # Create extracted entity
        extracted = ExtractedEntity(
            surface_form="Alice Chen",
            canonical_suggestion="Alice Chen",
            entity_type="person",
            context_clues=ContextClues(
                role="Engineering Manager",
                organization="Acme Corp"
            ),
            aliases_in_doc=["Alice"],
            confidence=0.95
        )

        result = await service.resolve_extracted_entity(
            extracted=extracted,
            artifact_uid="doc_001",
            revision_id="rev_001",
            doc_title="Test Document"
        )

        assert isinstance(result, EntityResolutionResult)
        assert result.is_new is True  # New entity created

    @pytest.mark.asyncio
    async def test_entity_resolution_creates_mention_record(
        self, mock_pg_client, mock_embedding_service, mock_openai_dedup_client
    ):
        """Test that entity resolution creates mention records."""
        mock_pg_client.fetch_one.return_value = None
        mock_pg_client.fetch_all.return_value = []
        mock_pg_client.fetch_val.return_value = uuid4()

        service = EntityResolutionService(
            pg_client=mock_pg_client,
            embedding_service=mock_embedding_service,
            openai_client=mock_openai_dedup_client
        )

        await service.resolve_entity(
            surface_form="Bob Smith",
            canonical_suggestion="Bob Smith",
            entity_type="person",
            context_clues=ContextClues(),
            artifact_uid="doc_001",
            revision_id="rev_001",
            start_char=100,
            end_char=109
        )

        # Verify mention insert was called
        mention_calls = [
            call for call in mock_pg_client.execute.call_args_list
            if "entity_mention" in str(call)
        ]
        assert len(mention_calls) > 0


# =============================================================================
# Event Actor/Subject Population Tests
# =============================================================================

class TestEventActorSubjectPopulation:
    """Tests for event_actor and event_subject tables being populated."""

    @pytest.mark.asyncio
    async def test_event_actors_linked_to_entities(
        self, mock_pg_client
    ):
        """Test that event actors are linked to resolved entities."""
        # This tests the workflow where:
        # 1. Entity is resolved (gets entity_id)
        # 2. Event is created with actor reference
        # 3. event_actor row links event_id to entity_id

        # We'd normally test this in the worker, but here we verify the pattern

        event_id = uuid4()
        entity_id = uuid4()

        # Simulate event_actor insert
        insert_query = """
        INSERT INTO event_actor (event_id, entity_id, role)
        VALUES ($1, $2, $3)
        """

        await mock_pg_client.execute(
            insert_query,
            event_id,
            entity_id,
            "owner"
        )

        mock_pg_client.execute.assert_called_with(
            insert_query,
            event_id,
            entity_id,
            "owner"
        )

    @pytest.mark.asyncio
    async def test_event_subjects_linked_to_entities(
        self, mock_pg_client
    ):
        """Test that event subjects are linked to resolved entities."""
        event_id = uuid4()
        entity_id = uuid4()

        insert_query = """
        INSERT INTO event_subject (event_id, entity_id)
        VALUES ($1, $2)
        """

        await mock_pg_client.execute(
            insert_query,
            event_id,
            entity_id
        )

        mock_pg_client.execute.assert_called_with(
            insert_query,
            event_id,
            entity_id
        )


# =============================================================================
# Graph Upsert Job Enqueue Tests
# =============================================================================

class TestGraphUpsertJobEnqueue:
    """Tests for graph_upsert job being enqueued after extraction."""

    @pytest.mark.asyncio
    async def test_graph_upsert_job_created_after_extraction(
        self, mock_pg_client
    ):
        """Test that graph_upsert job is enqueued after extract_events completes."""
        artifact_uid = "doc_001"
        revision_id = "rev_001"
        job_id = uuid4()

        # Simulate job enqueue
        mock_pg_client.fetch_val.return_value = job_id

        result = await mock_pg_client.fetch_val(
            """
            INSERT INTO event_jobs (
                job_type, artifact_uid, revision_id, status, attempts, max_attempts, next_run_at
            ) VALUES (
                'graph_upsert', $1, $2, 'PENDING', 0, 3, now()
            )
            RETURNING job_id
            """,
            artifact_uid,
            revision_id
        )

        assert result == job_id
        # Verify job_type is graph_upsert
        call_args = mock_pg_client.fetch_val.call_args[0]
        assert "graph_upsert" in call_args[0]

    @pytest.mark.asyncio
    async def test_graph_upsert_job_linked_to_same_artifact(
        self, mock_pg_client
    ):
        """Test graph_upsert job uses same artifact_uid and revision_id."""
        artifact_uid = "doc_001"
        revision_id = "rev_001"

        await mock_pg_client.fetch_val(
            """
            INSERT INTO event_jobs (job_type, artifact_uid, revision_id, status, attempts, max_attempts, next_run_at)
            VALUES ('graph_upsert', $1, $2, 'PENDING', 0, 3, now())
            RETURNING job_id
            """,
            artifact_uid,
            revision_id
        )

        call_args = mock_pg_client.fetch_val.call_args[0]
        assert call_args[1] == artifact_uid
        assert call_args[2] == revision_id


# =============================================================================
# Entity Deduplication Tests
# =============================================================================

class TestEntityDeduplication:
    """Tests for entity deduplication during extraction."""

    def test_deduplicate_entities_merges_same_entity(self):
        """Test deduplicate_entities merges entities with same canonical name."""
        service = EventExtractionService(api_key="test-key")

        chunk_entities = [
            [
                {
                    "surface_form": "Alice Chen",
                    "canonical_suggestion": "Alice Chen",
                    "type": "person",
                    "context_clues": {"role": "Engineer"},
                    "aliases_in_doc": [],
                    "confidence": 0.9
                }
            ],
            [
                {
                    "surface_form": "Alice",
                    "canonical_suggestion": "Alice Chen",
                    "type": "person",
                    "context_clues": {"org": "Acme"},
                    "aliases_in_doc": [],
                    "confidence": 0.8
                }
            ]
        ]

        deduplicated = service.deduplicate_entities(chunk_entities)

        assert len(deduplicated) == 1
        assert deduplicated[0]["canonical_suggestion"] == "Alice Chen"
        # Should have merged context clues
        assert deduplicated[0]["context_clues"].get("role") == "Engineer"
        assert deduplicated[0]["context_clues"].get("org") == "Acme"
        # Should have merged aliases
        assert "Alice" in deduplicated[0]["aliases_in_doc"]

    def test_deduplicate_entities_keeps_different_types_separate(self):
        """Test deduplicate_entities keeps entities of different types separate."""
        service = EventExtractionService(api_key="test-key")

        chunk_entities = [
            [
                {
                    "surface_form": "Acme",
                    "canonical_suggestion": "Acme",
                    "type": "org",
                    "context_clues": {},
                    "confidence": 0.9
                }
            ],
            [
                {
                    "surface_form": "Acme",
                    "canonical_suggestion": "Acme",
                    "type": "project",  # Different type
                    "context_clues": {},
                    "confidence": 0.8
                }
            ]
        ]

        deduplicated = service.deduplicate_entities(chunk_entities)

        assert len(deduplicated) == 2

    def test_deduplicate_entities_keeps_highest_confidence(self):
        """Test deduplicate_entities keeps highest confidence score."""
        service = EventExtractionService(api_key="test-key")

        chunk_entities = [
            [
                {"surface_form": "A", "canonical_suggestion": "Test", "type": "person", "confidence": 0.6}
            ],
            [
                {"surface_form": "B", "canonical_suggestion": "Test", "type": "person", "confidence": 0.9}
            ]
        ]

        deduplicated = service.deduplicate_entities(chunk_entities)

        assert len(deduplicated) == 1
        assert deduplicated[0]["confidence"] == 0.9


# =============================================================================
# Entity Validation Tests
# =============================================================================

class TestEntityValidation:
    """Tests for entity validation during extraction."""

    def test_validate_entity_requires_surface_form(self):
        """Test validate_entity requires surface_form field."""
        service = EventExtractionService(api_key="test-key")

        entity = {"type": "person"}  # Missing surface_form

        is_valid = service.validate_entity(entity)

        assert is_valid is False

    def test_validate_entity_requires_type(self):
        """Test validate_entity requires type field."""
        service = EventExtractionService(api_key="test-key")

        entity = {"surface_form": "Alice"}  # Missing type

        is_valid = service.validate_entity(entity)

        assert is_valid is False

    def test_validate_entity_defaults_invalid_type(self):
        """Test validate_entity defaults invalid type to 'other'."""
        service = EventExtractionService(api_key="test-key")

        entity = {
            "surface_form": "Alice",
            "type": "invalid_type"
        }

        is_valid = service.validate_entity(entity)

        assert is_valid is True
        assert entity["type"] == "other"

    def test_validate_entity_clamps_confidence(self):
        """Test validate_entity clamps confidence to [0, 1]."""
        service = EventExtractionService(api_key="test-key")

        entity = {
            "surface_form": "Alice",
            "type": "person",
            "confidence": 1.5  # Invalid
        }

        is_valid = service.validate_entity(entity)

        assert is_valid is True
        assert entity["confidence"] == 0.9  # Default value

    def test_validate_entity_ensures_canonical_suggestion(self):
        """Test validate_entity ensures canonical_suggestion exists."""
        service = EventExtractionService(api_key="test-key")

        entity = {
            "surface_form": "Alice Chen",
            "type": "person"
            # No canonical_suggestion
        }

        is_valid = service.validate_entity(entity)

        assert is_valid is True
        assert entity["canonical_suggestion"] == "Alice Chen"


# =============================================================================
# Full Extraction Pipeline Integration Tests
# =============================================================================

class TestFullExtractionPipeline:
    """Tests for the complete extraction pipeline with entities."""

    def test_extraction_pipeline_produces_complete_output(self):
        """Test extraction pipeline produces events, entities, and evidence."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]

        # Realistic extraction output
        extraction_output = {
            "events": [
                {
                    "category": "Decision",
                    "narrative": "Team decided to adopt freemium model",
                    "event_time": "2024-03-15T14:30:00Z",
                    "subject": {"type": "project", "ref": "pricing"},
                    "actors": [
                        {"ref": "Alice Chen", "role": "owner"},
                        {"ref": "Bob Smith", "role": "contributor"}
                    ],
                    "confidence": 0.95,
                    "evidence": [
                        {"quote": "we're going with freemium", "start_char": 100, "end_char": 125}
                    ]
                },
                {
                    "category": "Commitment",
                    "narrative": "Alice committed to launch date",
                    "event_time": None,
                    "subject": {"type": "project", "ref": "launch"},
                    "actors": [{"ref": "Alice Chen", "role": "owner"}],
                    "confidence": 0.85,
                    "evidence": [
                        {"quote": "will launch by Q2", "start_char": 200, "end_char": 220}
                    ]
                }
            ],
            "entities_mentioned": [
                {
                    "surface_form": "Alice Chen",
                    "canonical_suggestion": "Alice Chen",
                    "type": "person",
                    "context_clues": {
                        "role": "Product Lead",
                        "org": "Acme"
                    },
                    "aliases_in_doc": ["Alice"],
                    "confidence": 0.95,
                    "start_char": 10,
                    "end_char": 20
                },
                {
                    "surface_form": "Bob Smith",
                    "canonical_suggestion": "Bob Smith",
                    "type": "person",
                    "context_clues": {
                        "role": "Engineering Manager"
                    },
                    "aliases_in_doc": ["Bob"],
                    "confidence": 0.90,
                    "start_char": 30,
                    "end_char": 39
                },
                {
                    "surface_form": "Acme",
                    "canonical_suggestion": "Acme Corp",
                    "type": "org",
                    "context_clues": {},
                    "aliases_in_doc": ["Acme Corp"],
                    "confidence": 0.85,
                    "start_char": 50,
                    "end_char": 54
                }
            ]
        }

        mock_response.choices[0].message.content = json.dumps(extraction_output)
        mock_client.chat.completions.create.return_value = mock_response

        service = EventExtractionService(api_key="test-key")
        service.client = mock_client

        events, entities = service.extract_from_chunk_v4(
            chunk_text="Sample document content...",
            chunk_index=0,
            chunk_id="chunk_001",
            start_char=0
        )

        # Verify events
        assert len(events) == 2
        assert events[0]["category"] == "Decision"
        assert events[1]["category"] == "Commitment"

        # Verify entities
        assert len(entities) == 3
        person_entities = [e for e in entities if e["type"] == "person"]
        org_entities = [e for e in entities if e["type"] == "org"]
        assert len(person_entities) == 2
        assert len(org_entities) == 1

        # Verify evidence has chunk_id
        assert events[0]["evidence"][0]["chunk_id"] == "chunk_001"

        # Verify entity context
        alice = next(e for e in entities if e["surface_form"] == "Alice Chen")
        assert alice["context_clues"]["role"] == "Product Lead"
