"""
Unit tests for EntityResolutionService.

Tests V4 entity resolution functionality:
- find_candidates() returns correct matches above threshold
- confirm_match() handles same/different/uncertain responses
- create_entity() generates embeddings correctly
- merge_entity() adds aliases and updates mentions
- resolve_entity() end-to-end flow
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID
import json

from services.entity_resolution_service import (
    EntityResolutionService,
    EntityResolutionResult,
    MergeDecision,
    Entity,
    ExtractedEntity,
    ContextClues,
    EntityResolutionError,
    EmbeddingGenerationError,
    DedupCandidateError,
    LLMConfirmationError
)


# =============================================================================
# Test Markers
# =============================================================================

pytestmark = [pytest.mark.v4, pytest.mark.unit]


# =============================================================================
# find_candidates() Tests
# =============================================================================

class TestFindCandidates:
    """Tests for find_dedup_candidates() method."""

    @pytest.mark.asyncio
    async def test_find_candidates_returns_matches_above_threshold(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test find_candidates returns entities above similarity threshold."""
        # Setup mock to return candidates
        mock_pg_client.fetch_all.return_value = [
            {
                "entity_id": uuid4(),
                "entity_type": "person",
                "canonical_name": "Alice Chen",
                "normalized_name": "alice chen",
                "role": "Engineering Manager",
                "organization": "Acme Corp",
                "email": "achen@acme.com",
                "first_seen_artifact_uid": "doc_001",
                "first_seen_revision_id": "rev_001",
                "needs_review": False,
                "distance": 0.10  # High similarity (low distance)
            }
        ]

        # Generate a test embedding
        embedding = [0.1] * 3072

        candidates = await entity_resolution_service.find_dedup_candidates(
            entity_type="person",
            context_embedding=embedding,
            threshold=0.85
        )

        assert len(candidates) == 1
        assert candidates[0].canonical_name == "Alice Chen"
        assert candidates[0].entity_type == "person"
        mock_pg_client.fetch_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_candidates_returns_empty_when_no_matches(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test find_candidates returns empty list when no matches."""
        mock_pg_client.fetch_all.return_value = []

        embedding = [0.1] * 3072
        candidates = await entity_resolution_service.find_dedup_candidates(
            entity_type="person",
            context_embedding=embedding
        )

        assert candidates == []

    @pytest.mark.asyncio
    async def test_find_candidates_respects_entity_type_filter(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test find_candidates only returns entities of same type."""
        mock_pg_client.fetch_all.return_value = []

        embedding = [0.1] * 3072
        await entity_resolution_service.find_dedup_candidates(
            entity_type="org",
            context_embedding=embedding
        )

        # Verify the query includes entity_type filter
        call_args = mock_pg_client.fetch_all.call_args
        assert "entity_type" in call_args[0][0]  # Query string
        assert call_args[0][2] == "org"  # Second parameter is entity_type

    @pytest.mark.asyncio
    async def test_find_candidates_respects_max_limit(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test find_candidates respects max_candidates limit."""
        # Return more candidates than limit
        mock_pg_client.fetch_all.return_value = [
            {
                "entity_id": uuid4(),
                "entity_type": "person",
                "canonical_name": f"Person {i}",
                "normalized_name": f"person {i}",
                "role": None,
                "organization": None,
                "email": None,
                "first_seen_artifact_uid": "doc_001",
                "first_seen_revision_id": "rev_001",
                "needs_review": False,
                "distance": 0.05 + i * 0.01
            }
            for i in range(10)
        ]

        embedding = [0.1] * 3072
        candidates = await entity_resolution_service.find_dedup_candidates(
            entity_type="person",
            context_embedding=embedding
        )

        # Should be limited by max_candidates (default 5)
        assert len(candidates) <= entity_resolution_service.max_candidates

    @pytest.mark.asyncio
    async def test_find_candidates_raises_on_db_error(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test find_candidates raises DedupCandidateError on database error."""
        mock_pg_client.fetch_all.side_effect = Exception("Database connection failed")

        embedding = [0.1] * 3072
        with pytest.raises(DedupCandidateError):
            await entity_resolution_service.find_dedup_candidates(
                entity_type="person",
                context_embedding=embedding
            )


# =============================================================================
# confirm_merge_with_llm() Tests
# =============================================================================

class TestConfirmMerge:
    """Tests for confirm_merge_with_llm() method."""

    @pytest.mark.asyncio
    async def test_confirm_merge_returns_same_decision(
        self, entity_resolution_service, mock_openai_same_entity
    ):
        """Test confirm_merge returns 'same' when LLM decides entities match."""
        entity_resolution_service.openai_client = mock_openai_same_entity

        decision = await entity_resolution_service.confirm_merge_with_llm(
            entity_a_name="Alice Chen",
            entity_a_type="person",
            entity_a_context=ContextClues(role="Engineering Manager", organization="Acme"),
            entity_b_name="A. Chen",
            entity_b_type="person",
            entity_b_context=ContextClues(organization="Acme"),
            doc_title_a="Meeting Notes",
            doc_title_b="Project Doc"
        )

        assert decision.decision == "same"
        assert decision.canonical_name == "Alice Chen"

    @pytest.mark.asyncio
    async def test_confirm_merge_returns_different_decision(
        self, entity_resolution_service, mock_openai_dedup_client
    ):
        """Test confirm_merge returns 'different' when LLM decides entities differ."""
        decision = await entity_resolution_service.confirm_merge_with_llm(
            entity_a_name="Alice Chen",
            entity_a_type="person",
            entity_a_context=ContextClues(role="Engineer", organization="Acme"),
            entity_b_name="Alice Chen",
            entity_b_type="person",
            entity_b_context=ContextClues(role="Designer", organization="OtherCorp"),
            doc_title_a="Doc A",
            doc_title_b="Doc B"
        )

        assert decision.decision == "different"

    @pytest.mark.asyncio
    async def test_confirm_merge_returns_uncertain_decision(
        self, entity_resolution_service, mock_openai_uncertain_entity
    ):
        """Test confirm_merge returns 'uncertain' when LLM cannot decide."""
        entity_resolution_service.openai_client = mock_openai_uncertain_entity

        decision = await entity_resolution_service.confirm_merge_with_llm(
            entity_a_name="A. Chen",
            entity_a_type="person",
            entity_a_context=ContextClues(),  # No context
            entity_b_name="Alice C.",
            entity_b_type="person",
            entity_b_context=ContextClues(),  # No context
            doc_title_a="Doc A",
            doc_title_b="Doc B"
        )

        assert decision.decision == "uncertain"

    @pytest.mark.asyncio
    async def test_confirm_merge_handles_invalid_json(
        self, entity_resolution_service
    ):
        """Test confirm_merge handles invalid JSON response gracefully."""
        mock_client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "not valid json"
        mock_client.chat.completions.create.return_value = response
        entity_resolution_service.openai_client = mock_client

        decision = await entity_resolution_service.confirm_merge_with_llm(
            entity_a_name="Test",
            entity_a_type="person",
            entity_a_context=ContextClues(),
            entity_b_name="Test",
            entity_b_type="person",
            entity_b_context=ContextClues(),
            doc_title_a="A",
            doc_title_b="B"
        )

        # Should return uncertain on parse failure
        assert decision.decision == "uncertain"

    @pytest.mark.asyncio
    async def test_confirm_merge_raises_on_api_error(
        self, entity_resolution_service
    ):
        """Test confirm_merge raises LLMConfirmationError on API failure."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API timeout")
        entity_resolution_service.openai_client = mock_client

        with pytest.raises(LLMConfirmationError):
            await entity_resolution_service.confirm_merge_with_llm(
                entity_a_name="Test",
                entity_a_type="person",
                entity_a_context=ContextClues(),
                entity_b_name="Test",
                entity_b_type="person",
                entity_b_context=ContextClues(),
                doc_title_a="A",
                doc_title_b="B"
            )


# =============================================================================
# create_entity() Tests
# =============================================================================

class TestCreateEntity:
    """Tests for create_entity() method."""

    @pytest.mark.asyncio
    async def test_create_entity_generates_uuid(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test create_entity generates a new UUID."""
        mock_pg_client.fetch_val.return_value = uuid4()

        embedding = [0.1] * 3072
        entity_id = await entity_resolution_service.create_entity(
            canonical_name="Alice Chen",
            normalized_name="alice chen",
            entity_type="person",
            context_clues=ContextClues(role="Engineer"),
            context_embedding=embedding,
            artifact_uid="doc_001",
            revision_id="rev_001"
        )

        assert isinstance(entity_id, UUID)
        mock_pg_client.fetch_val.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_entity_stores_context_clues(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test create_entity stores role, organization, email."""
        mock_pg_client.fetch_val.return_value = uuid4()

        embedding = [0.1] * 3072
        await entity_resolution_service.create_entity(
            canonical_name="Alice Chen",
            normalized_name="alice chen",
            entity_type="person",
            context_clues=ContextClues(
                role="Engineering Manager",
                organization="Acme Corp",
                email="achen@acme.com"
            ),
            context_embedding=embedding,
            artifact_uid="doc_001",
            revision_id="rev_001"
        )

        # Verify insert was called with context clues
        call_args = mock_pg_client.fetch_val.call_args[0]
        assert "Engineering Manager" in call_args
        assert "Acme Corp" in call_args
        assert "achen@acme.com" in call_args

    @pytest.mark.asyncio
    async def test_create_entity_stores_embedding_as_vector(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test create_entity stores embedding in pgvector format."""
        mock_pg_client.fetch_val.return_value = uuid4()

        embedding = [0.1, 0.2, 0.3]  # Simplified for test
        await entity_resolution_service.create_entity(
            canonical_name="Test",
            normalized_name="test",
            entity_type="person",
            context_clues=ContextClues(),
            context_embedding=embedding,
            artifact_uid="doc_001",
            revision_id="rev_001"
        )

        # Verify embedding was converted to string format
        call_args = mock_pg_client.fetch_val.call_args[0]
        query = call_args[0]
        assert "::vector" in query

    @pytest.mark.asyncio
    async def test_create_entity_sets_needs_review_flag(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test create_entity sets needs_review flag when requested."""
        mock_pg_client.fetch_val.return_value = uuid4()

        embedding = [0.1] * 3072
        await entity_resolution_service.create_entity(
            canonical_name="Uncertain Entity",
            normalized_name="uncertain entity",
            entity_type="person",
            context_clues=ContextClues(),
            context_embedding=embedding,
            artifact_uid="doc_001",
            revision_id="rev_001",
            needs_review=True
        )

        # Verify needs_review was passed
        call_args = mock_pg_client.fetch_val.call_args[0]
        assert True in call_args  # needs_review=True should be in args


# =============================================================================
# merge_entity() Tests
# =============================================================================

class TestMergeEntity:
    """Tests for merge_entity() method."""

    @pytest.mark.asyncio
    async def test_merge_entity_updates_canonical_name_if_longer(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test merge_entity updates canonical name if new name is longer."""
        existing_entity_id = uuid4()
        mock_pg_client.fetch_one.return_value = {"canonical_name": "A. Chen"}

        await entity_resolution_service.merge_entity(
            new_surface_form="Alice Chen",
            existing_entity_id=existing_entity_id,
            new_canonical_name="Alice Chen"
        )

        # Should have called UPDATE
        mock_pg_client.execute.assert_called()

    @pytest.mark.asyncio
    async def test_merge_entity_does_not_update_if_shorter(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test merge_entity does not update if existing name is longer."""
        existing_entity_id = uuid4()
        mock_pg_client.fetch_one.return_value = {"canonical_name": "Alice Chen"}

        await entity_resolution_service.merge_entity(
            new_surface_form="Alice",
            existing_entity_id=existing_entity_id,
            new_canonical_name="Alice"
        )

        # Should NOT have called UPDATE (execute is for other operations)
        # Check that no UPDATE was issued
        for call in mock_pg_client.execute.call_args_list:
            if call and call[0]:
                assert "UPDATE entity" not in call[0][0]

    @pytest.mark.asyncio
    async def test_merge_entity_returns_existing_id(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test merge_entity returns the existing entity ID."""
        existing_entity_id = uuid4()
        mock_pg_client.fetch_one.return_value = {"canonical_name": "Alice Chen"}

        result = await entity_resolution_service.merge_entity(
            new_surface_form="Alice",
            existing_entity_id=existing_entity_id,
            new_canonical_name=None
        )

        assert result == existing_entity_id


# =============================================================================
# add_alias() Tests
# =============================================================================

class TestAddAlias:
    """Tests for add_alias() method."""

    @pytest.mark.asyncio
    async def test_add_alias_inserts_new_alias(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test add_alias inserts a new alias record."""
        entity_id = uuid4()

        await entity_resolution_service.add_alias(entity_id, "A. Chen")

        mock_pg_client.execute.assert_called_once()
        call_args = mock_pg_client.execute.call_args[0]
        assert "INSERT INTO entity_alias" in call_args[0]

    @pytest.mark.asyncio
    async def test_add_alias_is_idempotent(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test add_alias uses ON CONFLICT DO NOTHING."""
        entity_id = uuid4()

        await entity_resolution_service.add_alias(entity_id, "Alice")

        call_args = mock_pg_client.execute.call_args[0]
        assert "ON CONFLICT" in call_args[0]
        assert "DO NOTHING" in call_args[0]


# =============================================================================
# record_mention() Tests
# =============================================================================

class TestRecordMention:
    """Tests for record_mention() method."""

    @pytest.mark.asyncio
    async def test_record_mention_creates_mention_record(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test record_mention creates an entity_mention record."""
        entity_id = uuid4()

        mention_id = await entity_resolution_service.record_mention(
            entity_id=entity_id,
            artifact_uid="doc_001",
            revision_id="rev_001",
            surface_form="Alice Chen",
            start_char=150,
            end_char=160
        )

        mock_pg_client.execute.assert_called_once()
        call_args = mock_pg_client.execute.call_args[0]
        assert "INSERT INTO entity_mention" in call_args[0]

    @pytest.mark.asyncio
    async def test_record_mention_includes_character_offsets(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test record_mention stores character offsets."""
        entity_id = uuid4()

        await entity_resolution_service.record_mention(
            entity_id=entity_id,
            artifact_uid="doc_001",
            revision_id="rev_001",
            surface_form="Alice",
            start_char=100,
            end_char=105
        )

        call_args = mock_pg_client.execute.call_args[0]
        assert 100 in call_args  # start_char
        assert 105 in call_args  # end_char


# =============================================================================
# resolve_entity() End-to-End Tests
# =============================================================================

class TestResolveEntity:
    """Tests for resolve_entity() end-to-end flow."""

    @pytest.mark.asyncio
    async def test_resolve_entity_creates_new_when_no_match(
        self, entity_resolution_service, mock_pg_client, mock_embedding_service
    ):
        """Test resolve_entity creates new entity when no candidates found."""
        # No exact match
        mock_pg_client.fetch_one.return_value = None
        # No embedding candidates
        mock_pg_client.fetch_all.return_value = []
        # Return new entity_id
        new_id = uuid4()
        mock_pg_client.fetch_val.return_value = new_id

        result = await entity_resolution_service.resolve_entity(
            surface_form="Alice Chen",
            canonical_suggestion="Alice Chen",
            entity_type="person",
            context_clues=ContextClues(role="Engineer"),
            artifact_uid="doc_001",
            revision_id="rev_001"
        )

        assert result.is_new is True
        assert result.entity_id == new_id
        assert result.merged_from is None

    @pytest.mark.asyncio
    async def test_resolve_entity_merges_when_same_decision(
        self, entity_resolution_service, mock_pg_client, mock_embedding_service, mock_openai_same_entity
    ):
        """Test resolve_entity merges entities when LLM returns 'same'."""
        # No exact match
        mock_pg_client.fetch_one.side_effect = [
            None,  # No exact match
            {"canonical_name": "Alice Chen"}  # For merge update check
        ]

        # Return a candidate
        existing_id = uuid4()
        mock_pg_client.fetch_all.return_value = [
            {
                "entity_id": existing_id,
                "entity_type": "person",
                "canonical_name": "Alice Chen",
                "normalized_name": "alice chen",
                "role": "Engineer",
                "organization": "Acme",
                "email": None,
                "first_seen_artifact_uid": "old_doc",
                "first_seen_revision_id": "old_rev",
                "needs_review": False,
                "distance": 0.05
            }
        ]

        # Set up LLM to return "same"
        entity_resolution_service.openai_client = mock_openai_same_entity

        result = await entity_resolution_service.resolve_entity(
            surface_form="A. Chen",
            canonical_suggestion="A. Chen",
            entity_type="person",
            context_clues=ContextClues(organization="Acme"),
            artifact_uid="doc_002",
            revision_id="rev_001"
        )

        assert result.is_new is False
        assert result.entity_id == existing_id
        assert result.merged_from == existing_id

    @pytest.mark.asyncio
    async def test_resolve_entity_creates_uncertain_with_possibly_same(
        self, entity_resolution_service, mock_pg_client, mock_embedding_service, mock_openai_uncertain_entity
    ):
        """Test resolve_entity creates entity with POSSIBLY_SAME when uncertain."""
        # No exact match
        mock_pg_client.fetch_one.return_value = None

        # Return a candidate
        existing_id = uuid4()
        mock_pg_client.fetch_all.return_value = [
            {
                "entity_id": existing_id,
                "entity_type": "person",
                "canonical_name": "Alice Chen",
                "normalized_name": "alice chen",
                "role": None,
                "organization": None,
                "email": None,
                "first_seen_artifact_uid": "old_doc",
                "first_seen_revision_id": "old_rev",
                "needs_review": False,
                "distance": 0.08
            }
        ]

        # Set up LLM to return "uncertain"
        entity_resolution_service.openai_client = mock_openai_uncertain_entity

        # New entity ID
        new_id = uuid4()
        mock_pg_client.fetch_val.return_value = new_id

        result = await entity_resolution_service.resolve_entity(
            surface_form="A. Chen",
            canonical_suggestion="A. Chen",
            entity_type="person",
            context_clues=ContextClues(),
            artifact_uid="doc_002",
            revision_id="rev_001"
        )

        assert result.is_new is True
        assert result.uncertain_match == existing_id

        # Verify uncertain pair was tracked
        pairs = entity_resolution_service.get_uncertain_pairs()
        assert len(pairs) == 1
        assert pairs[0][0] == new_id
        assert pairs[0][1] == existing_id

    @pytest.mark.asyncio
    async def test_resolve_entity_uses_exact_match_when_available(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test resolve_entity uses exact match instead of embedding search."""
        # Return exact match
        existing_id = uuid4()
        mock_pg_client.fetch_one.return_value = {
            "entity_id": existing_id,
            "entity_type": "person",
            "canonical_name": "Alice Chen",
            "normalized_name": "alice chen",
            "role": "Engineer",
            "organization": "Acme",
            "email": None,
            "first_seen_artifact_uid": "old_doc",
            "first_seen_revision_id": "old_rev",
            "needs_review": False
        }

        result = await entity_resolution_service.resolve_entity(
            surface_form="Alice Chen",
            canonical_suggestion="Alice Chen",
            entity_type="person",
            context_clues=ContextClues(),
            artifact_uid="doc_002",
            revision_id="rev_001"
        )

        assert result.is_new is False
        assert result.entity_id == existing_id
        # Should not have called embedding generation or LLM
        mock_pg_client.fetch_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_entity_records_aliases(
        self, entity_resolution_service, mock_pg_client
    ):
        """Test resolve_entity records aliases from document."""
        # No match - create new
        mock_pg_client.fetch_one.return_value = None
        mock_pg_client.fetch_all.return_value = []
        mock_pg_client.fetch_val.return_value = uuid4()

        await entity_resolution_service.resolve_entity(
            surface_form="Alice Chen",
            canonical_suggestion="Alice Chen",
            entity_type="person",
            context_clues=ContextClues(),
            artifact_uid="doc_001",
            revision_id="rev_001",
            aliases_in_doc=["Alice", "A. Chen"]
        )

        # Should have called add_alias for each alias
        alias_inserts = [
            call for call in mock_pg_client.execute.call_args_list
            if "INSERT INTO entity_alias" in call[0][0]
        ]
        assert len(alias_inserts) >= 2


# =============================================================================
# generate_context_embedding() Tests
# =============================================================================

class TestGenerateContextEmbedding:
    """Tests for generate_context_embedding() method."""

    @pytest.mark.asyncio
    async def test_generate_embedding_includes_all_context(
        self, entity_resolution_service, mock_embedding_service
    ):
        """Test generate_context_embedding includes name, type, role, org."""
        await entity_resolution_service.generate_context_embedding(
            canonical_name="Alice Chen",
            entity_type="person",
            role="Engineering Manager",
            organization="Acme Corp"
        )

        call_args = mock_embedding_service.generate_embedding.call_args[0][0]
        assert "Alice Chen" in call_args
        assert "person" in call_args
        assert "Engineering Manager" in call_args
        assert "Acme Corp" in call_args

    @pytest.mark.asyncio
    async def test_generate_embedding_handles_missing_context(
        self, entity_resolution_service, mock_embedding_service
    ):
        """Test generate_context_embedding handles missing role/org."""
        await entity_resolution_service.generate_context_embedding(
            canonical_name="Alice",
            entity_type="person",
            role=None,
            organization=None
        )

        call_args = mock_embedding_service.generate_embedding.call_args[0][0]
        assert "Alice" in call_args
        assert "person" in call_args

    @pytest.mark.asyncio
    async def test_generate_embedding_raises_on_service_error(
        self, entity_resolution_service, mock_embedding_service
    ):
        """Test generate_context_embedding raises on embedding service error."""
        mock_embedding_service.generate_embedding.side_effect = Exception("API error")

        with pytest.raises(EmbeddingGenerationError):
            await entity_resolution_service.generate_context_embedding(
                canonical_name="Test",
                entity_type="person"
            )


# =============================================================================
# resolve_extracted_entity() Tests
# =============================================================================

class TestResolveExtractedEntity:
    """Tests for resolve_extracted_entity() convenience method."""

    @pytest.mark.asyncio
    async def test_resolve_extracted_entity_delegates_correctly(
        self, entity_resolution_service, mock_pg_client, sample_extracted_entity_alice
    ):
        """Test resolve_extracted_entity delegates to resolve_entity."""
        mock_pg_client.fetch_one.return_value = None
        mock_pg_client.fetch_all.return_value = []
        mock_pg_client.fetch_val.return_value = uuid4()

        result = await entity_resolution_service.resolve_extracted_entity(
            extracted=sample_extracted_entity_alice,
            artifact_uid="doc_001",
            revision_id="rev_001",
            doc_title="Test Document"
        )

        assert isinstance(result, EntityResolutionResult)


# =============================================================================
# Normalization Tests
# =============================================================================

class TestNormalization:
    """Tests for name normalization."""

    def test_normalize_name_lowercases(self, entity_resolution_service):
        """Test _normalize_name lowercases text."""
        result = entity_resolution_service._normalize_name("Alice Chen")
        assert result == "alice chen"

    def test_normalize_name_strips_whitespace(self, entity_resolution_service):
        """Test _normalize_name strips extra whitespace."""
        result = entity_resolution_service._normalize_name("  Alice   Chen  ")
        assert result == "alice chen"

    def test_normalize_name_handles_special_chars(self, entity_resolution_service):
        """Test _normalize_name handles special characters."""
        result = entity_resolution_service._normalize_name("Alice O'Brien-Smith")
        assert result == "alice o'brien-smith"
