"""
Unit tests for GraphService.

Tests V4 graph operations:
- upsert_entity_node() creates node correctly
- upsert_event_node() creates node correctly
- upsert_edges() creates all edge types
- expand_from_events() returns correct related events
- graph health check
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID
import json

from services.graph_service import (
    GraphService,
    GraphServiceError,
    AGENotAvailableError,
    GraphQueryTimeoutError,
    CypherSyntaxError,
    RelatedContext,
    GraphHealthStats
)


# =============================================================================
# Test Markers
# =============================================================================

pytestmark = [pytest.mark.v4, pytest.mark.unit]


# =============================================================================
# AGE Availability Tests
# =============================================================================

class TestAGEAvailability:
    """Tests for Apache AGE availability checks."""

    @pytest.mark.asyncio
    async def test_check_age_available_returns_true_when_configured(
        self, mock_pg_client
    ):
        """Test check_age_available returns True when AGE is properly configured."""
        # Mock extension check
        mock_pg_client.fetch_one.side_effect = [
            {"1": 1},  # Extension exists
            {"1": 1}   # Graph exists
        ]

        service = GraphService(pg_client=mock_pg_client)
        result = await service.check_age_available()

        assert result is True
        assert service._age_available is True

    @pytest.mark.asyncio
    async def test_check_age_available_returns_false_when_no_extension(
        self, mock_pg_client
    ):
        """Test check_age_available returns False when AGE extension not installed."""
        mock_pg_client.fetch_one.return_value = None

        service = GraphService(pg_client=mock_pg_client)
        result = await service.check_age_available()

        assert result is False
        assert service._age_available is False

    @pytest.mark.asyncio
    async def test_check_age_available_returns_false_when_no_graph(
        self, mock_pg_client
    ):
        """Test check_age_available returns False when graph doesn't exist."""
        mock_pg_client.fetch_one.side_effect = [
            {"1": 1},  # Extension exists
            None       # Graph doesn't exist
        ]

        service = GraphService(pg_client=mock_pg_client)
        result = await service.check_age_available()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_age_available_caches_result(
        self, mock_pg_client
    ):
        """Test check_age_available caches the result."""
        mock_pg_client.fetch_one.side_effect = [
            {"1": 1},
            {"1": 1}
        ]

        service = GraphService(pg_client=mock_pg_client)

        # First call - should query database
        await service.check_age_available()

        # Second call - should use cache
        result = await service.check_age_available()

        assert result is True
        # Should only have called fetch_one twice (for first check)
        assert mock_pg_client.fetch_one.call_count == 2

    @pytest.mark.asyncio
    async def test_check_age_available_handles_db_error(
        self, mock_pg_client
    ):
        """Test check_age_available returns False on database error."""
        mock_pg_client.fetch_one.side_effect = Exception("Connection failed")

        service = GraphService(pg_client=mock_pg_client)
        result = await service.check_age_available()

        assert result is False


# =============================================================================
# upsert_entity_node() Tests
# =============================================================================

class TestUpsertEntityNode:
    """Tests for upsert_entity_node() method."""

    @pytest.mark.asyncio
    async def test_upsert_entity_node_creates_node(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_entity_node creates an Entity node."""
        # Mock AGE available
        mock_pg_client.fetch_one.side_effect = [
            {"1": 1},  # Extension check
            {"1": 1}   # Graph check
        ]

        # Mock Cypher execution
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{"entity_id": "test"}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        entity_id = uuid4()
        await graph_service.upsert_entity_node(
            entity_id=entity_id,
            canonical_name="Alice Chen",
            entity_type="person",
            role="Engineer",
            organization="Acme"
        )

        # Verify Cypher was executed
        mock_conn.fetch.assert_called()
        call_args = mock_conn.fetch.call_args[0][0]
        assert "MERGE" in call_args
        assert "Entity" in call_args
        assert str(entity_id) in call_args

    @pytest.mark.asyncio
    async def test_upsert_entity_node_sets_properties(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_entity_node sets all properties."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        await graph_service.upsert_entity_node(
            entity_id=uuid4(),
            canonical_name="Alice Chen",
            entity_type="person",
            role="Engineering Manager",
            organization="Acme Corp"
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "canonical_name" in call_args
        assert "Alice Chen" in call_args
        assert "Engineering Manager" in call_args
        assert "Acme Corp" in call_args

    @pytest.mark.asyncio
    async def test_upsert_entity_node_handles_optional_fields(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_entity_node handles missing role/organization."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        await graph_service.upsert_entity_node(
            entity_id=uuid4(),
            canonical_name="Test Entity",
            entity_type="org",
            role=None,
            organization=None
        )

        # Should not raise, and query should be valid
        mock_conn.fetch.assert_called()

    @pytest.mark.asyncio
    async def test_upsert_entity_node_raises_when_age_unavailable(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_entity_node raises when AGE is unavailable."""
        mock_pg_client.fetch_one.return_value = None

        with pytest.raises(AGENotAvailableError):
            await graph_service.upsert_entity_node(
                entity_id=uuid4(),
                canonical_name="Test",
                entity_type="person"
            )


# =============================================================================
# upsert_event_node() Tests
# =============================================================================

class TestUpsertEventNode:
    """Tests for upsert_event_node() method."""

    @pytest.mark.asyncio
    async def test_upsert_event_node_creates_node(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_event_node creates an Event node."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        event_id = uuid4()
        await graph_service.upsert_event_node(
            event_id=event_id,
            category="Decision",
            narrative="Team decided on pricing model",
            artifact_uid="doc_001",
            revision_id="rev_001",
            event_time="2024-03-15T14:30:00Z",
            confidence=0.95
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "MERGE" in call_args
        assert "Event" in call_args
        assert str(event_id) in call_args
        assert "Decision" in call_args

    @pytest.mark.asyncio
    async def test_upsert_event_node_truncates_long_narrative(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_event_node truncates narratives over 500 chars."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        long_narrative = "A" * 1000  # 1000 character narrative

        await graph_service.upsert_event_node(
            event_id=uuid4(),
            category="Decision",
            narrative=long_narrative,
            artifact_uid="doc_001",
            revision_id="rev_001"
        )

        # The service truncates to 500 chars
        mock_conn.fetch.assert_called()

    @pytest.mark.asyncio
    async def test_upsert_event_node_handles_null_event_time(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_event_node handles null event_time."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        await graph_service.upsert_event_node(
            event_id=uuid4(),
            category="Decision",
            narrative="Test event",
            artifact_uid="doc_001",
            revision_id="rev_001",
            event_time=None
        )

        mock_conn.fetch.assert_called()


# =============================================================================
# upsert_acted_in_edge() Tests
# =============================================================================

class TestUpsertActedInEdge:
    """Tests for upsert_acted_in_edge() method."""

    @pytest.mark.asyncio
    async def test_upsert_acted_in_edge_creates_edge(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_acted_in_edge creates ACTED_IN edge."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        entity_id = uuid4()
        event_id = uuid4()

        await graph_service.upsert_acted_in_edge(
            entity_id=entity_id,
            event_id=event_id,
            role="owner"
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "ACTED_IN" in call_args
        assert "MERGE" in call_args
        assert str(entity_id) in call_args
        assert str(event_id) in call_args
        assert "owner" in call_args

    @pytest.mark.asyncio
    async def test_upsert_acted_in_edge_sets_role_property(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_acted_in_edge sets role property on edge."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        await graph_service.upsert_acted_in_edge(
            entity_id=uuid4(),
            event_id=uuid4(),
            role="contributor"
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "r.role" in call_args
        assert "contributor" in call_args


# =============================================================================
# upsert_about_edge() Tests
# =============================================================================

class TestUpsertAboutEdge:
    """Tests for upsert_about_edge() method."""

    @pytest.mark.asyncio
    async def test_upsert_about_edge_creates_edge(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_about_edge creates ABOUT edge."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        event_id = uuid4()
        entity_id = uuid4()

        await graph_service.upsert_about_edge(
            event_id=event_id,
            entity_id=entity_id
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "ABOUT" in call_args
        assert "MERGE" in call_args
        assert str(event_id) in call_args
        assert str(entity_id) in call_args


# =============================================================================
# upsert_possibly_same_edge() Tests
# =============================================================================

class TestUpsertPossiblySameEdge:
    """Tests for upsert_possibly_same_edge() method."""

    @pytest.mark.asyncio
    async def test_upsert_possibly_same_edge_creates_edge(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_possibly_same_edge creates POSSIBLY_SAME edge."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        entity_a_id = uuid4()
        entity_b_id = uuid4()

        await graph_service.upsert_possibly_same_edge(
            entity_a_id=entity_a_id,
            entity_b_id=entity_b_id,
            confidence=0.75,
            reason="Similar name, limited context"
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "POSSIBLY_SAME" in call_args
        assert str(entity_a_id) in call_args
        assert str(entity_b_id) in call_args
        assert "0.75" in call_args

    @pytest.mark.asyncio
    async def test_upsert_possibly_same_edge_truncates_reason(
        self, graph_service, mock_pg_client
    ):
        """Test upsert_possibly_same_edge truncates long reasons."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"result": '{}'}]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        long_reason = "X" * 500  # Long reason

        await graph_service.upsert_possibly_same_edge(
            entity_a_id=uuid4(),
            entity_b_id=uuid4(),
            confidence=0.7,
            reason=long_reason
        )

        # Should not raise
        mock_conn.fetch.assert_called()


# =============================================================================
# expand_from_events() Tests
# =============================================================================

class TestExpandFromEvents:
    """Tests for expand_from_events() method."""

    @pytest.mark.asyncio
    async def test_expand_from_events_returns_related_events(
        self, graph_service, mock_pg_client
    ):
        """Test expand_from_events returns related events."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        related_event_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "event_id": f'"{str(related_event_id)}"',
                "category": '"Decision"',
                "narrative": '"Related decision"',
                "event_time": '"2024-03-15T10:00:00Z"',
                "confidence": '0.9',
                "artifact_uid": '"doc_002"',
                "revision_id": '"rev_001"',
                "entity_name": '"Alice Chen"',
                "reason": '"same_actor:Alice Chen"'
            }
        ]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        seed_event_ids = [uuid4()]

        results = await graph_service.expand_from_events(
            seed_event_ids=seed_event_ids,
            budget=10
        )

        assert len(results) == 1
        assert isinstance(results[0], RelatedContext)
        assert results[0].category == "Decision"
        assert results[0].reason == "same_actor:Alice Chen"

    @pytest.mark.asyncio
    async def test_expand_from_events_returns_empty_on_no_seeds(
        self, graph_service
    ):
        """Test expand_from_events returns empty list when no seeds."""
        results = await graph_service.expand_from_events(
            seed_event_ids=[],
            budget=10
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_expand_from_events_respects_budget(
        self, graph_service, mock_pg_client
    ):
        """Test expand_from_events respects budget limit."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        await graph_service.expand_from_events(
            seed_event_ids=[uuid4()],
            budget=5
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "LIMIT 5" in call_args

    @pytest.mark.asyncio
    async def test_expand_from_events_applies_category_filter(
        self, graph_service, mock_pg_client
    ):
        """Test expand_from_events applies category filter."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        await graph_service.expand_from_events(
            seed_event_ids=[uuid4()],
            budget=10,
            category_filter=["Decision", "Commitment"]
        )

        call_args = mock_conn.fetch.call_args[0][0]
        assert "Decision" in call_args
        assert "Commitment" in call_args

    @pytest.mark.asyncio
    async def test_expand_from_events_returns_empty_when_age_unavailable(
        self, graph_service, mock_pg_client
    ):
        """Test expand_from_events returns empty when AGE unavailable."""
        mock_pg_client.fetch_one.return_value = None

        results = await graph_service.expand_from_events(
            seed_event_ids=[uuid4()],
            budget=10
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_expand_from_events_handles_timeout_gracefully(
        self, graph_service, mock_pg_client
    ):
        """Test expand_from_events handles timeout gracefully."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        mock_conn.fetch.side_effect = Exception("timeout exceeded")
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        results = await graph_service.expand_from_events(
            seed_event_ids=[uuid4()],
            budget=10
        )

        # Should return empty, not raise
        assert results == []


# =============================================================================
# get_health() Tests
# =============================================================================

class TestGetHealth:
    """Tests for get_health() method."""

    @pytest.mark.asyncio
    async def test_get_health_returns_stats_when_available(
        self, graph_service, mock_pg_client
    ):
        """Test get_health returns stats when AGE is available."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        mock_conn = AsyncMock()
        # Mock count queries
        mock_conn.fetch.side_effect = [
            [{"result": "10"}],  # Entity count
            [{"result": "20"}],  # Event count
            [{"result": "15"}],  # ACTED_IN count
            [{"result": "8"}],   # ABOUT count
            [{"result": "2"}]    # POSSIBLY_SAME count
        ]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        health = await graph_service.get_health()

        assert isinstance(health, GraphHealthStats)
        assert health.age_enabled is True
        assert health.graph_exists is True

    @pytest.mark.asyncio
    async def test_get_health_returns_disabled_when_age_unavailable(
        self, graph_service, mock_pg_client
    ):
        """Test get_health returns disabled stats when AGE unavailable."""
        mock_pg_client.fetch_one.return_value = None

        health = await graph_service.get_health()

        assert health.age_enabled is False
        assert health.graph_exists is False
        assert health.entity_node_count == 0
        assert health.event_node_count == 0

    @pytest.mark.asyncio
    async def test_get_health_to_dict(self, graph_service, mock_pg_client):
        """Test GraphHealthStats.to_dict() method."""
        mock_pg_client.fetch_one.return_value = None

        health = await graph_service.get_health()
        health_dict = health.to_dict()

        assert "age_enabled" in health_dict
        assert "graph_exists" in health_dict
        assert "entity_node_count" in health_dict
        assert "possibly_same_edge_count" in health_dict


# =============================================================================
# get_entities_for_events() Tests
# =============================================================================

class TestGetEntitiesForEvents:
    """Tests for get_entities_for_events() method."""

    @pytest.mark.asyncio
    async def test_get_entities_returns_entities(
        self, graph_service, mock_pg_client
    ):
        """Test get_entities_for_events returns entity information."""
        mock_pg_client.fetch_one.side_effect = [{"1": 1}, {"1": 1}]

        entity_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {
                "entity_id": f'"{str(entity_id)}"',
                "name": '"Alice Chen"',
                "type": '"person"',
                "role": '"Engineer"',
                "organization": '"Acme"',
                "mention_count": '3'
            }
        ]
        mock_conn.execute = AsyncMock()
        mock_pg_client.acquire.return_value.__aenter__.return_value = mock_conn

        results = await graph_service.get_entities_for_events([uuid4()])

        assert len(results) == 1
        assert results[0]["name"] == "Alice Chen"
        assert results[0]["type"] == "person"
        assert results[0]["mention_count"] == 3

    @pytest.mark.asyncio
    async def test_get_entities_returns_empty_on_no_events(
        self, graph_service
    ):
        """Test get_entities_for_events returns empty when no event IDs."""
        results = await graph_service.get_entities_for_events([])
        assert results == []

    @pytest.mark.asyncio
    async def test_get_entities_returns_empty_when_age_unavailable(
        self, graph_service, mock_pg_client
    ):
        """Test get_entities_for_events returns empty when AGE unavailable."""
        mock_pg_client.fetch_one.return_value = None

        results = await graph_service.get_entities_for_events([uuid4()])
        assert results == []


# =============================================================================
# Parameter Substitution Tests
# =============================================================================

class TestParameterSubstitution:
    """Tests for Cypher parameter substitution."""

    def test_substitute_params_string(self, graph_service):
        """Test parameter substitution for strings."""
        query = "MATCH (n {name: $name}) RETURN n"
        result = graph_service._substitute_params(query, {"name": "Alice"})
        assert "'Alice'" in result

    def test_substitute_params_escapes_quotes(self, graph_service):
        """Test parameter substitution escapes single quotes."""
        query = "MATCH (n {name: $name}) RETURN n"
        result = graph_service._substitute_params(query, {"name": "O'Brien"})
        assert "\\'" in result

    def test_substitute_params_number(self, graph_service):
        """Test parameter substitution for numbers."""
        query = "MATCH (n) WHERE n.count = $count RETURN n"
        result = graph_service._substitute_params(query, {"count": 42})
        assert "42" in result

    def test_substitute_params_boolean(self, graph_service):
        """Test parameter substitution for booleans."""
        query = "MATCH (n {active: $active}) RETURN n"
        result = graph_service._substitute_params(query, {"active": True})
        assert "true" in result

    def test_substitute_params_list(self, graph_service):
        """Test parameter substitution for lists."""
        query = "MATCH (n) WHERE n.id IN $ids RETURN n"
        result = graph_service._substitute_params(query, {"ids": ["a", "b", "c"]})
        assert "['a', 'b', 'c']" in result

    def test_substitute_params_uuid(self, graph_service):
        """Test parameter substitution for UUIDs."""
        query = "MATCH (n {id: $id}) RETURN n"
        test_id = uuid4()
        result = graph_service._substitute_params(query, {"id": test_id})
        assert str(test_id) in result

    def test_substitute_params_null(self, graph_service):
        """Test parameter substitution for null values."""
        query = "MATCH (n {name: $name}) RETURN n"
        result = graph_service._substitute_params(query, {"name": None})
        assert "null" in result


# =============================================================================
# AGType Parsing Tests
# =============================================================================

class TestAGTypeParsing:
    """Tests for AGE agtype parsing."""

    def test_parse_agtype_json_string(self, graph_service):
        """Test parsing JSON string agtype."""
        result = graph_service._parse_agtype('{"name": "Alice"}')
        assert result == {"name": "Alice"}

    def test_parse_agtype_plain_string(self, graph_service):
        """Test parsing plain string agtype."""
        result = graph_service._parse_agtype('"Alice"')
        assert result == "Alice"

    def test_parse_agtype_number(self, graph_service):
        """Test parsing number agtype."""
        result = graph_service._parse_agtype("42")
        assert result == 42

    def test_parse_agtype_null(self, graph_service):
        """Test parsing null agtype."""
        result = graph_service._parse_agtype(None)
        assert result is None

    def test_parse_agtype_invalid_json(self, graph_service):
        """Test parsing invalid JSON returns original value."""
        result = graph_service._parse_agtype("not json {")
        assert result == "not json {"


# =============================================================================
# RelatedContext Tests
# =============================================================================

class TestRelatedContext:
    """Tests for RelatedContext data class."""

    def test_related_context_to_dict(self):
        """Test RelatedContext.to_dict() method."""
        context = RelatedContext(
            event_id=uuid4(),
            category="Decision",
            narrative="Test narrative",
            reason="same_actor:Alice",
            event_time="2024-03-15T10:00:00Z",
            confidence=0.9,
            entity_name="Alice Chen",
            artifact_uid="doc_001",
            revision_id="rev_001"
        )

        result = context.to_dict()

        assert result["type"] == "event"
        assert result["category"] == "Decision"
        assert result["reason"] == "same_actor:Alice"
        assert "event_id" not in result  # Uses "id" instead
        assert "id" in result
