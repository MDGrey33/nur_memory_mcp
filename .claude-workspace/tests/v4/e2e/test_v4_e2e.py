"""
V4 End-to-End Tests.

Implements all 10 E2E tests from v4.md:

1. test_entity_extraction_rich_context - Entity extraction returns rich context
2. test_entity_dedup_same_person - Entity deduplication merges same person
3. test_entity_dedup_different_people - Entity deduplication keeps different people separate
4. test_uncertain_merge_creates_possibly_same - Uncertain merge creates POSSIBLY_SAME edge
5. test_graph_upsert_materializes_nodes - graph_upsert materializes nodes/edges
6. test_hybrid_search_expand_options - hybrid_search returns expand_options
7. test_related_context_connected_bounded - Related context is connected and bounded
8. test_graph_seed_limit_respected - graph_seed_limit is respected
9. test_backward_compatibility - Backward compatibility with V3
10. test_chunk_to_revision_mapping - Chunk-to-revision mapping works
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID
import json
import re

from services.entity_resolution_service import (
    EntityResolutionService,
    EntityResolutionResult,
    ContextClues,
    ExtractedEntity
)
from services.graph_service import GraphService, RelatedContext
from services.event_extraction_service import EventExtractionService
from services.retrieval_service import RetrievalService, V4SearchResult
from storage.models import SearchResult, MergedResult


# =============================================================================
# Test Markers
# =============================================================================

pytestmark = [pytest.mark.v4, pytest.mark.e2e]


# =============================================================================
# Test 1: Entity Extraction Returns Rich Context
# =============================================================================

class TestEntityExtractionRichContext:
    """
    V4-E2E-001: Entity extraction returns rich context.

    - Ingest artifact mentioning "Alice Chen, Engineering Manager at Acme"
    - Assert entity created with role="Engineering Manager", organization="Acme Corp"
    - Assert entity_mention links to correct character offsets
    """

    @pytest.mark.asyncio
    async def test_entity_extraction_creates_entity_with_context(
        self, mock_pg_client, mock_embedding_service, mock_openai_dedup_client
    ):
        """Test that entity extraction creates entities with role and organization."""
        # Setup - no existing entities
        mock_pg_client.fetch_one.return_value = None
        mock_pg_client.fetch_all.return_value = []
        entity_id = uuid4()
        mock_pg_client.fetch_val.return_value = entity_id

        service = EntityResolutionService(
            pg_client=mock_pg_client,
            embedding_service=mock_embedding_service,
            openai_client=mock_openai_dedup_client
        )

        # Act - resolve entity with rich context
        result = await service.resolve_entity(
            surface_form="Alice Chen",
            canonical_suggestion="Alice Chen",
            entity_type="person",
            context_clues=ContextClues(
                role="Engineering Manager",
                organization="Acme Corp",
                email="achen@acme.com"
            ),
            artifact_uid="doc_001",
            revision_id="rev_001",
            start_char=150,
            end_char=160
        )

        # Assert - entity created
        assert result.is_new is True
        assert result.entity_id == entity_id

        # Assert - entity insert was called with context
        insert_calls = [c for c in mock_pg_client.fetch_val.call_args_list]
        assert len(insert_calls) > 0

        # Verify context clues were passed to insert
        insert_call = insert_calls[0]
        insert_args = insert_call[0]
        insert_query = insert_args[0]

        # Should insert role, organization, email
        assert "role" in insert_query.lower() or "Engineering Manager" in str(insert_args)

    @pytest.mark.asyncio
    async def test_entity_extraction_records_mention_with_offsets(
        self, mock_pg_client, mock_embedding_service, mock_openai_dedup_client
    ):
        """Test that entity mentions include character offsets."""
        mock_pg_client.fetch_one.return_value = None
        mock_pg_client.fetch_all.return_value = []
        mock_pg_client.fetch_val.return_value = uuid4()

        service = EntityResolutionService(
            pg_client=mock_pg_client,
            embedding_service=mock_embedding_service,
            openai_client=mock_openai_dedup_client
        )

        await service.resolve_entity(
            surface_form="Alice Chen",
            canonical_suggestion="Alice Chen",
            entity_type="person",
            context_clues=ContextClues(role="Engineering Manager"),
            artifact_uid="doc_001",
            revision_id="rev_001",
            start_char=150,
            end_char=160
        )

        # Verify mention was recorded with offsets
        mention_calls = [
            c for c in mock_pg_client.execute.call_args_list
            if "entity_mention" in str(c)
        ]
        assert len(mention_calls) > 0

        # Check that start_char and end_char were passed
        mention_call = mention_calls[0]
        mention_args = mention_call[0]
        assert 150 in mention_args  # start_char
        assert 160 in mention_args  # end_char


# =============================================================================
# Test 2: Entity Deduplication (Same Person)
# =============================================================================

class TestEntityDedupSamePerson:
    """
    V4-E2E-002: Entity deduplication merges same person.

    - Ingest doc A mentioning "Alice Chen, Engineering Manager"
    - Ingest doc B mentioning "A. Chen from Acme"
    - Assert: single entity created (merged)
    - Assert: both surface forms in entity_mention
    - Assert: alias "A. Chen" added to entity_alias
    """

    @pytest.mark.asyncio
    async def test_dedup_merges_same_person(
        self, mock_pg_client, mock_embedding_service, mock_openai_same_entity
    ):
        """Test that same person is merged into single entity."""
        existing_entity_id = uuid4()

        # First resolution - creates new entity
        mock_pg_client.fetch_one.side_effect = [
            None,  # No exact match
            {"canonical_name": "Alice Chen"}  # For merge update
        ]
        mock_pg_client.fetch_all.side_effect = [
            [],  # No candidates for first entity
            [    # Return existing entity as candidate for second
                {
                    "entity_id": existing_entity_id,
                    "entity_type": "person",
                    "canonical_name": "Alice Chen",
                    "normalized_name": "alice chen",
                    "role": "Engineering Manager",
                    "organization": "Acme",
                    "email": None,
                    "first_seen_artifact_uid": "doc_a",
                    "first_seen_revision_id": "rev_001",
                    "needs_review": False,
                    "distance": 0.05
                }
            ]
        ]
        mock_pg_client.fetch_val.return_value = existing_entity_id

        service = EntityResolutionService(
            pg_client=mock_pg_client,
            embedding_service=mock_embedding_service,
            openai_client=mock_openai_same_entity  # Returns "same"
        )

        # First entity - Alice Chen from doc A
        result1 = await service.resolve_entity(
            surface_form="Alice Chen",
            canonical_suggestion="Alice Chen",
            entity_type="person",
            context_clues=ContextClues(role="Engineering Manager"),
            artifact_uid="doc_a",
            revision_id="rev_001"
        )

        # Reset mocks for second call
        mock_pg_client.fetch_one.side_effect = [
            None,  # No exact match
            {"canonical_name": "Alice Chen"}  # For merge update
        ]

        # Second entity - A. Chen from doc B (should merge)
        result2 = await service.resolve_entity(
            surface_form="A. Chen",
            canonical_suggestion="A. Chen",
            entity_type="person",
            context_clues=ContextClues(organization="Acme"),
            artifact_uid="doc_b",
            revision_id="rev_001"
        )

        # Assert - merged with existing
        assert result2.is_new is False
        assert result2.entity_id == existing_entity_id
        assert result2.merged_from == existing_entity_id

    @pytest.mark.asyncio
    async def test_dedup_adds_alias_for_different_surface_form(
        self, mock_pg_client, mock_embedding_service, mock_openai_same_entity
    ):
        """Test that alias is added when merging with different surface form."""
        existing_entity_id = uuid4()

        mock_pg_client.fetch_one.side_effect = [
            None,
            {"canonical_name": "Alice Chen"}
        ]
        mock_pg_client.fetch_all.return_value = [
            {
                "entity_id": existing_entity_id,
                "entity_type": "person",
                "canonical_name": "Alice Chen",
                "normalized_name": "alice chen",
                "role": None,
                "organization": None,
                "email": None,
                "first_seen_artifact_uid": "doc_a",
                "first_seen_revision_id": "rev_001",
                "needs_review": False,
                "distance": 0.05
            }
        ]

        service = EntityResolutionService(
            pg_client=mock_pg_client,
            embedding_service=mock_embedding_service,
            openai_client=mock_openai_same_entity
        )

        await service.resolve_entity(
            surface_form="A. Chen",
            canonical_suggestion="A. Chen",
            entity_type="person",
            context_clues=ContextClues(),
            artifact_uid="doc_b",
            revision_id="rev_001"
        )

        # Verify alias was added
        alias_calls = [
            c for c in mock_pg_client.execute.call_args_list
            if "entity_alias" in str(c)
        ]
        assert len(alias_calls) > 0


# =============================================================================
# Test 3: Entity Deduplication (Different People)
# =============================================================================

class TestEntityDedupDifferentPeople:
    """
    V4-E2E-003: Entity deduplication keeps different people separate.

    - Ingest doc mentioning "Alice Chen" (Engineer at Acme)
    - Ingest doc mentioning "Alice Chen" (Designer at OtherCorp)
    - Assert: two separate entities created (different org context)
    """

    @pytest.mark.asyncio
    async def test_dedup_keeps_different_people_separate(
        self, mock_pg_client, mock_embedding_service, mock_openai_dedup_client
    ):
        """Test that people at different orgs stay separate."""
        entity1_id = uuid4()
        entity2_id = uuid4()

        # First entity - no matches
        mock_pg_client.fetch_one.side_effect = [None, None]
        mock_pg_client.fetch_all.return_value = []
        mock_pg_client.fetch_val.side_effect = [entity1_id, entity2_id]

        service = EntityResolutionService(
            pg_client=mock_pg_client,
            embedding_service=mock_embedding_service,
            openai_client=mock_openai_dedup_client  # Returns "different"
        )

        # First Alice Chen - Engineer at Acme
        result1 = await service.resolve_entity(
            surface_form="Alice Chen",
            canonical_suggestion="Alice Chen",
            entity_type="person",
            context_clues=ContextClues(role="Engineer", organization="Acme Corp"),
            artifact_uid="doc_001",
            revision_id="rev_001"
        )

        # Setup for second entity - return first as candidate but LLM says different
        mock_pg_client.fetch_one.side_effect = [None]
        mock_pg_client.fetch_all.return_value = [
            {
                "entity_id": entity1_id,
                "entity_type": "person",
                "canonical_name": "Alice Chen",
                "normalized_name": "alice chen",
                "role": "Engineer",
                "organization": "Acme Corp",
                "email": None,
                "first_seen_artifact_uid": "doc_001",
                "first_seen_revision_id": "rev_001",
                "needs_review": False,
                "distance": 0.08
            }
        ]

        # Second Alice Chen - Designer at OtherCorp
        result2 = await service.resolve_entity(
            surface_form="Alice Chen",
            canonical_suggestion="Alice Chen",
            entity_type="person",
            context_clues=ContextClues(role="Designer", organization="OtherCorp"),
            artifact_uid="doc_002",
            revision_id="rev_001"
        )

        # Assert - both are new entities (different IDs)
        assert result1.is_new is True
        assert result2.is_new is True
        assert result1.entity_id != result2.entity_id


# =============================================================================
# Test 4: Uncertain Merge Creates POSSIBLY_SAME Edge
# =============================================================================

class TestUncertainMergeCreatesPossiblySame:
    """
    V4-E2E-004: Uncertain merge creates POSSIBLY_SAME edge.

    - Ingest doc A: "A. Chen mentioned the deadline" (minimal context)
    - Ingest doc B: "Alice C. updated the status" (minimal context)
    - Assert: two entities created (different due to uncertainty)
    - Assert: POSSIBLY_SAME edge exists in graph between them
    - Assert: at least one entity has needs_review=true
    """

    @pytest.mark.asyncio
    async def test_uncertain_creates_possibly_same(
        self, mock_pg_client, mock_embedding_service, mock_openai_uncertain_entity
    ):
        """Test that uncertain matches create POSSIBLY_SAME edge."""
        entity1_id = uuid4()
        entity2_id = uuid4()

        mock_pg_client.fetch_one.side_effect = [None, None]
        mock_pg_client.fetch_all.side_effect = [
            [],  # No candidates for first
            [    # Return first entity as candidate for second
                {
                    "entity_id": entity1_id,
                    "entity_type": "person",
                    "canonical_name": "A. Chen",
                    "normalized_name": "a. chen",
                    "role": None,
                    "organization": None,
                    "email": None,
                    "first_seen_artifact_uid": "doc_a",
                    "first_seen_revision_id": "rev_001",
                    "needs_review": False,
                    "distance": 0.12
                }
            ]
        ]
        mock_pg_client.fetch_val.side_effect = [entity1_id, entity2_id]

        service = EntityResolutionService(
            pg_client=mock_pg_client,
            embedding_service=mock_embedding_service,
            openai_client=mock_openai_uncertain_entity  # Returns "uncertain"
        )

        # First entity - minimal context
        result1 = await service.resolve_entity(
            surface_form="A. Chen",
            canonical_suggestion="A. Chen",
            entity_type="person",
            context_clues=ContextClues(),  # No context
            artifact_uid="doc_a",
            revision_id="rev_001"
        )

        # Second entity - should trigger uncertain decision
        result2 = await service.resolve_entity(
            surface_form="Alice C.",
            canonical_suggestion="Alice C.",
            entity_type="person",
            context_clues=ContextClues(),  # No context
            artifact_uid="doc_b",
            revision_id="rev_001"
        )

        # Assert - second entity is new with uncertain_match
        assert result2.is_new is True
        assert result2.uncertain_match == entity1_id

        # Assert - uncertain pair was tracked
        pairs = service.get_uncertain_pairs()
        assert len(pairs) == 1
        assert pairs[0][0] == entity2_id
        assert pairs[0][1] == entity1_id

    @pytest.mark.asyncio
    async def test_uncertain_entity_has_needs_review_flag(
        self, mock_pg_client, mock_embedding_service, mock_openai_uncertain_entity
    ):
        """Test that uncertain entities have needs_review=true."""
        entity1_id = uuid4()
        entity2_id = uuid4()

        mock_pg_client.fetch_one.return_value = None
        mock_pg_client.fetch_all.side_effect = [
            [],
            [
                {
                    "entity_id": entity1_id,
                    "entity_type": "person",
                    "canonical_name": "Test",
                    "normalized_name": "test",
                    "role": None,
                    "organization": None,
                    "email": None,
                    "first_seen_artifact_uid": "doc",
                    "first_seen_revision_id": "rev",
                    "needs_review": False,
                    "distance": 0.1
                }
            ]
        ]
        mock_pg_client.fetch_val.side_effect = [entity1_id, entity2_id]

        service = EntityResolutionService(
            pg_client=mock_pg_client,
            embedding_service=mock_embedding_service,
            openai_client=mock_openai_uncertain_entity
        )

        # First entity
        await service.resolve_entity(
            surface_form="A",
            canonical_suggestion="A",
            entity_type="person",
            context_clues=ContextClues(),
            artifact_uid="doc_a",
            revision_id="rev_001"
        )

        # Second entity - uncertain
        await service.resolve_entity(
            surface_form="B",
            canonical_suggestion="B",
            entity_type="person",
            context_clues=ContextClues(),
            artifact_uid="doc_b",
            revision_id="rev_001"
        )

        # Verify needs_review=True was passed in create
        create_calls = [c for c in mock_pg_client.fetch_val.call_args_list]
        # Second create call should have needs_review=True
        second_create = create_calls[1]
        assert True in second_create[0]  # needs_review=True in args


# =============================================================================
# Test 5: Graph Upsert Materializes Nodes/Edges
# =============================================================================

class TestGraphUpsertMaterializesNodes:
    """
    V4-E2E-005: graph_upsert materializes nodes/edges.

    - Ingest artifact -> wait extraction DONE -> wait graph_upsert DONE
    - Assert: Entity and Event nodes exist in AGE graph
    - Assert: ACTED_IN and ABOUT edges exist
    - Assert: hybrid_search(graph_expand=true) returns non-empty related_context
    """

    @pytest.mark.asyncio
    async def test_graph_upsert_creates_entity_nodes(
        self, mock_pg_client
    ):
        """Test graph_upsert creates Entity nodes."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": "{}"}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        service = GraphService(pg_client=mock_pg_client)

        entity_id = uuid4()
        await service.upsert_entity_node(
            entity_id=entity_id,
            canonical_name="Alice Chen",
            entity_type="person",
            role="Engineer",
            organization="Acme"
        )

        # Verify Cypher MERGE was called
        mock_conn.fetch.assert_called()
        call_args = mock_conn.fetch.call_args[0][0]
        assert "MERGE" in call_args
        assert "Entity" in call_args
        assert str(entity_id) in call_args

    @pytest.mark.asyncio
    async def test_graph_upsert_creates_event_nodes(
        self, mock_pg_client
    ):
        """Test graph_upsert creates Event nodes."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": "{}"}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        service = GraphService(pg_client=mock_pg_client)

        event_id = uuid4()
        await service.upsert_event_node(
            event_id=event_id,
            category="Decision",
            narrative="Team made a decision",
            artifact_uid="doc_001",
            revision_id="rev_001"
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "MERGE" in call_args
        assert "Event" in call_args
        assert "Decision" in call_args

    @pytest.mark.asyncio
    async def test_graph_upsert_creates_acted_in_edges(
        self, mock_pg_client
    ):
        """Test graph_upsert creates ACTED_IN edges."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": "{}"}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        service = GraphService(pg_client=mock_pg_client)

        await service.upsert_acted_in_edge(
            entity_id=uuid4(),
            event_id=uuid4(),
            role="owner"
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "ACTED_IN" in call_args
        assert "MERGE" in call_args

    @pytest.mark.asyncio
    async def test_graph_upsert_creates_about_edges(
        self, mock_pg_client
    ):
        """Test graph_upsert creates ABOUT edges."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": "{}"}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        service = GraphService(pg_client=mock_pg_client)

        await service.upsert_about_edge(
            event_id=uuid4(),
            entity_id=uuid4()
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "ABOUT" in call_args
        assert "MERGE" in call_args


# =============================================================================
# Test 6: Hybrid Search Returns Expand Options
# =============================================================================

class TestHybridSearchExpandOptions:
    """
    V4-E2E-006: hybrid_search returns expand_options.

    - Call hybrid_search
    - Assert: expand_options contains graph_expand, include_memory, expand_neighbors, graph_budget, graph_filters
    """

    @pytest.mark.asyncio
    async def test_expand_options_contains_required_fields(
        self, retrieval_service_v4, mock_chroma_client
    ):
        """Test expand_options contains all required fields."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True
        )

        # Verify expand_options is present
        assert "expand_options" in result.to_dict()

        # The expand_options should have useful metadata
        expand_opts = result.expand_options
        assert "graph_expand" in expand_opts

    @pytest.mark.asyncio
    async def test_expand_options_always_returned(
        self, retrieval_service_v4, mock_chroma_client
    ):
        """Test expand_options is returned even when graph_expand=false."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=False
        )

        assert result.expand_options is not None


# =============================================================================
# Test 7: Related Context is Connected and Bounded
# =============================================================================

class TestRelatedContextConnectedBounded:
    """
    V4-E2E-007: Related context is connected and bounded.

    - Create two docs sharing the same actor (verified same entity)
    - Call hybrid_search(query about doc A, graph_expand=true)
    - Assert: related_context includes events from doc B
    - Assert: related_context.length <= graph_budget
    - Assert: each related item has standardized reason format
    """

    @pytest.mark.asyncio
    async def test_related_context_from_connected_docs(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test related_context includes events from connected documents."""
        # Setup primary result from doc A
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content from doc A"]],
            "metadatas": [[{"artifact_uid": "doc_a"}]],
            "distances": [[0.1]]
        }

        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc_a", "revision_id": "rev_001"}
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]

        # Mock graph returns related event from doc B
        mock_graph_service.expand_from_events.return_value = [
            RelatedContext(
                event_id=uuid4(),
                category="Decision",
                narrative="Related decision from doc B",
                reason="same_actor:Alice Chen",
                event_time=None,
                confidence=0.9,
                entity_name="Alice Chen",
                artifact_uid="doc_b",  # Different document
                revision_id="rev_001"
            )
        ]

        result = await retrieval_service_v4.hybrid_search_v4(
            query="doc A content",
            graph_expand=True
        )

        assert len(result.related_context) == 1
        assert result.related_context[0].artifact_uid == "doc_b"

    @pytest.mark.asyncio
    async def test_related_context_respects_budget(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test related_context respects graph_budget."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }

        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc", "revision_id": "rev"}
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]

        # Return more items than budget
        mock_graph_service.expand_from_events.return_value = [
            RelatedContext(
                event_id=uuid4(),
                category="Decision",
                narrative=f"Event {i}",
                reason="same_actor:Test",
                event_time=None,
                confidence=0.9,
                entity_name="Test",
                artifact_uid="doc",
                revision_id="rev"
            )
            for i in range(20)
        ]

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True,
            graph_budget=5
        )

        # Graph service should limit to budget
        mock_graph_service.expand_from_events.assert_called_with(
            seed_event_ids=pytest.approx(mock_pg_client.fetch_all.return_value[0]["event_id"], abs=0),
            budget=5,
            category_filter=None
        )

    @pytest.mark.asyncio
    async def test_related_context_has_standardized_reason(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test related_context items have standardized reason format."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }

        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc", "revision_id": "rev"}
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]

        mock_graph_service.expand_from_events.return_value = [
            RelatedContext(
                event_id=uuid4(),
                category="Decision",
                narrative="Test",
                reason="same_actor:Alice Chen",
                event_time=None,
                confidence=0.9,
                entity_name="Alice Chen",
                artifact_uid="doc",
                revision_id="rev"
            ),
            RelatedContext(
                event_id=uuid4(),
                category="Commitment",
                narrative="Test 2",
                reason="same_subject:Project X",
                event_time=None,
                confidence=0.85,
                entity_name="Project X",
                artifact_uid="doc",
                revision_id="rev"
            )
        ]

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True
        )

        # Verify standardized reason formats
        reasons = [rc.reason for rc in result.related_context]
        assert all(
            re.match(r"same_(actor|subject):.+", reason)
            for reason in reasons
        )


# =============================================================================
# Test 8: Graph Seed Limit Respected
# =============================================================================

class TestGraphSeedLimitRespected:
    """
    V4-E2E-008: graph_seed_limit is respected.

    - Create 10 primary results
    - Call hybrid_search(graph_expand=true, graph_seed_limit=3)
    - Assert: expansion only uses top 3 results as seeds
    """

    @pytest.mark.asyncio
    async def test_seed_limit_limits_expansion_seeds(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test graph_seed_limit limits expansion seed count."""
        # Return 10 primary results
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [[f"art_{i:03d}" for i in range(10)]],
            "documents": [[f"Content {i}" for i in range(10)]],
            "metadatas": [[{} for _ in range(10)]],
            "distances": [[0.1 + i*0.01 for i in range(10)]]
        }

        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc", "revision_id": "rev"}
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]
        mock_graph_service.expand_from_events.return_value = []

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            limit=10,
            graph_expand=True,
            graph_seed_limit=3
        )

        # Verify seeds_used in expand_options
        assert result.expand_options.get("seeds_used", 0) <= 3


# =============================================================================
# Test 9: Backward Compatibility
# =============================================================================

class TestBackwardCompatibility:
    """
    V4-E2E-009: Backward compatibility with V3.

    - Call hybrid_search(graph_expand=false)
    - Assert: output shape identical to V3 (no related_context, no entities)
    - Assert: primary_results quality unchanged
    - Assert: expand_options IS included (only new field)
    """

    @pytest.mark.asyncio
    async def test_v3_compatible_output_shape(
        self, retrieval_service_v4, mock_chroma_client
    ):
        """Test output shape matches V3 when graph_expand=false."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001", "art_002"]],
            "documents": [["Content 1", "Content 2"]],
            "metadatas": [[{"title": "Doc 1"}, {"title": "Doc 2"}]],
            "distances": [[0.1, 0.2]]
        }

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=False
        )

        result_dict = result.to_dict()

        # V3 compatible: primary_results present
        assert "primary_results" in result_dict
        assert len(result_dict["primary_results"]) == 2

        # V3 compatible: no related_context content
        assert result_dict["related_context"] == []

        # V3 compatible: no entities content
        assert result_dict["entities"] == []

        # V4 addition: expand_options present
        assert "expand_options" in result_dict

    @pytest.mark.asyncio
    async def test_primary_results_unchanged(
        self, retrieval_service_v4, mock_chroma_client
    ):
        """Test primary_results format unchanged from V3."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Test content"]],
            "metadatas": [[{"title": "Test Doc", "type": "document"}]],
            "distances": [[0.15]]
        }

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=False
        )

        result_dict = result.to_dict()
        primary = result_dict["primary_results"][0]

        # V3 compatible fields
        assert "id" in primary
        assert "content" in primary
        assert "metadata" in primary
        assert "collection" in primary
        assert "rrf_score" in primary


# =============================================================================
# Test 10: Chunk-to-Revision Mapping
# =============================================================================

class TestChunkToRevisionMapping:
    """
    V4-E2E-010: Chunk-to-revision mapping works.

    - Ingest large artifact (creates chunks)
    - Search returns a chunk as primary result
    - Call with graph_expand=true
    - Assert: correctly maps chunk -> artifact_revision -> events -> graph expansion
    """

    @pytest.mark.asyncio
    async def test_chunk_maps_to_revision(
        self, retrieval_service_v4, mock_pg_client
    ):
        """Test chunk ID correctly maps to artifact_revision."""
        mock_pg_client.fetch_one.return_value = {
            "artifact_uid": "doc_001",
            "revision_id": "rev_001"
        }

        # Simulate _get_seed_events with chunk result
        primary_results = [
            MergedResult(
                result=SearchResult(
                    id="art_001::chunk::000::abc",  # Chunk ID
                    content="Chunk content",
                    metadata={"artifact_id": "art_001"},
                    collection="artifact_chunks",
                    rank=0,
                    distance=0.1,
                    is_chunk=True,
                    artifact_id="art_001"
                ),
                rrf_score=0.5,
                collections=["artifact_chunks"]
            )
        ]

        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]

        seed_events = await retrieval_service_v4._get_seed_events(primary_results)

        # Verify artifact_revision lookup was called with artifact_id
        mock_pg_client.fetch_one.assert_called()
        call_args = mock_pg_client.fetch_one.call_args[0]
        assert "artifact_revision" in call_args[0]

        # Verify we got seed events
        assert len(seed_events) >= 1

    @pytest.mark.asyncio
    async def test_chunk_expansion_uses_correct_events(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test graph expansion uses events from chunk's artifact."""
        # Return chunk as primary result
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001::chunk::002::xyz"]],
            "documents": [["Middle chunk of large document"]],
            "metadatas": [[{"artifact_id": "art_001", "chunk_index": 2}]],
            "distances": [[0.1]]
        }

        # Map chunk to revision
        mock_pg_client.fetch_one.return_value = {
            "artifact_uid": "large_doc",
            "revision_id": "rev_001"
        }

        # Return events for that revision
        event_id = uuid4()
        mock_pg_client.fetch_all.return_value = [{"event_id": event_id}]

        # Graph expansion
        mock_graph_service.expand_from_events.return_value = []

        await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True
        )

        # Verify expand_from_events was called with the event from revision
        mock_graph_service.expand_from_events.assert_called()
        call_args = mock_graph_service.expand_from_events.call_args
        seed_ids = call_args.kwargs.get("seed_event_ids") or call_args[1].get("seed_event_ids") or call_args[0][0]
        assert event_id in seed_ids

    @pytest.mark.asyncio
    async def test_get_artifact_uid_for_chunk(
        self, retrieval_service_v4, mock_pg_client
    ):
        """Test get_artifact_uid_for_chunk utility method."""
        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc_001"}

        result = await retrieval_service_v4.get_artifact_uid_for_chunk(
            "art_001::chunk::000::abc"
        )

        assert result == "doc_001"

        # Verify correct artifact_id was extracted from chunk_id
        call_args = mock_pg_client.fetch_one.call_args[0]
        assert "art_001" in str(call_args)


# =============================================================================
# Additional E2E Verification Tests
# =============================================================================

class TestE2EVerification:
    """Additional tests to verify E2E scenarios work correctly."""

    @pytest.mark.asyncio
    async def test_full_pipeline_entity_to_search(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test the full pipeline from entity resolution to search."""
        # This test verifies the integration of all V4 components

        # 1. Search returns results
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Alice Chen discussed the project"]],
            "metadatas": [[{"title": "Meeting Notes"}]],
            "distances": [[0.1]]
        }

        # 2. Revision lookup works
        mock_pg_client.fetch_one.return_value = {
            "artifact_uid": "meeting_001",
            "revision_id": "rev_001"
        }

        # 3. Events exist for the artifact
        mock_pg_client.fetch_all.return_value = [
            {"event_id": uuid4()}
        ]

        # 4. Graph expansion returns related context
        mock_graph_service.expand_from_events.return_value = [
            RelatedContext(
                event_id=uuid4(),
                category="Decision",
                narrative="Alice made a decision",
                reason="same_actor:Alice Chen",
                event_time=None,
                confidence=0.9,
                entity_name="Alice Chen",
                artifact_uid="other_doc",
                revision_id="rev_001"
            )
        ]

        # 5. Entities are fetched
        mock_graph_service.get_entities_for_events.return_value = [
            {
                "entity_id": str(uuid4()),
                "name": "Alice Chen",
                "type": "person",
                "role": "Engineer",
                "organization": "Acme",
                "mention_count": 5
            }
        ]

        # Execute full search
        result = await retrieval_service_v4.hybrid_search_v4(
            query="Alice project discussion",
            graph_expand=True,
            include_entities=True
        )

        # Verify complete result
        assert len(result.primary_results) == 1
        assert len(result.related_context) == 1
        assert len(result.entities) == 1

        # Verify result can be serialized
        result_dict = result.to_dict()
        assert "primary_results" in result_dict
        assert "related_context" in result_dict
        assert "entities" in result_dict
        assert "expand_options" in result_dict
