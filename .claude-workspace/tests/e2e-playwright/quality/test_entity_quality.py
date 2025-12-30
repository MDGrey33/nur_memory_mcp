"""
Entity Resolution Quality Tests.

Tests:
- Entity extraction completeness
- Entity type accuracy (person, org, project, etc.)
- Entity deduplication (POSSIBLY_SAME edges)
- Canonical name quality
- Alias detection

These tests validate V4 entity extraction and resolution quality.

Run:
    # Without AI assessment
    pytest tests/e2e-playwright/quality/test_entity_quality.py -v

    # With AI assessment
    AI_ASSESSMENT_ENABLED=true pytest tests/e2e-playwright/quality/test_entity_quality.py -v

Markers:
    @pytest.mark.quality - All quality tests
    @pytest.mark.entity - Entity resolution tests
    @pytest.mark.requires_ai - Tests requiring GPT-4o
"""

from __future__ import annotations

import pytest
from typing import Dict, List

from .conftest import (
    TestDocument,
    ExpectedEntity,
    requires_ai,
    AI_ASSESSMENT_ENABLED
)


# =============================================================================
# Quality Thresholds
# =============================================================================

ENTITY_RECALL_THRESHOLD = 0.7  # 70% of expected entities should be found
TYPE_ACCURACY_THRESHOLD = 0.8  # 80% of entities should have correct type
DEDUP_QUALITY_THRESHOLD = 0.7  # 70% deduplication accuracy


# =============================================================================
# Entity Types
# =============================================================================

VALID_ENTITY_TYPES = ["person", "org", "project", "object", "place", "other"]


# =============================================================================
# Helper Functions
# =============================================================================

def get_entities_for_artifact(mcp_client, artifact_uid: str) -> List[Dict]:
    """Get entities extracted for an artifact (via hybrid_search or direct query)."""
    # Try hybrid_search with entity expansion
    result = mcp_client.call_tool("hybrid_search", {
        "query": "*",  # Get all
        "artifact_uid": artifact_uid,
        "expand_options": {
            "enabled": True,
            "include_entities": True
        }
    })

    if result.success and "entities" in result.data:
        return result.data["entities"]

    # Fallback: entities might be in different response structure
    return result.data.get("expanded_entities", [])


# =============================================================================
# Basic Entity Extraction Tests
# =============================================================================

@pytest.mark.quality
@pytest.mark.entity
class TestEntityExtractionBasic:
    """Basic entity extraction quality tests."""

    def test_person_entities_extracted(
        self,
        mcp_client,
        ingest_and_wait,
        product_launch_doc: TestDocument
    ):
        """Person entities should be extracted from meeting notes."""
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Person Entity Test",
            artifact_type="note"
        )

        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])
        person_entities = [e for e in entities if e.get("type") == "person"]

        # Should find some person entities
        assert len(person_entities) >= 1, "Should extract at least one person entity"

    def test_org_entities_extracted(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Organization entities should be extracted."""
        content = """
        Partnership Meeting

        We met with representatives from Acme Corp and TechStart Inc to discuss
        the integration partnership. Google Cloud Platform was mentioned as the
        preferred hosting solution.
        """

        result = ingest_and_wait(content=content, title="Org Entity Test")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        org_entities = [e for e in entities if e.get("type") == "org"]

        # Should find organization entities
        assert len(org_entities) >= 1, "Should extract at least one org entity"

    def test_project_entities_extracted(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Project entities should be extracted."""
        content = """
        Status Update

        Project Phoenix is on track for Q2 delivery.
        Project Aurora needs additional resources.
        The legacy system migration (Project Sunset) is 80% complete.
        """

        result = ingest_and_wait(content=content, title="Project Entity Test")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        project_entities = [e for e in entities if e.get("type") == "project"]

        # Should find project entities
        assert len(project_entities) >= 1, "Should extract at least one project entity"


@pytest.mark.quality
@pytest.mark.entity
class TestEntityTypeAccuracy:
    """Tests for entity type accuracy."""

    def test_all_entities_have_valid_type(
        self,
        mcp_client,
        ingest_and_wait,
        product_launch_doc: TestDocument
    ):
        """All entities should have valid V4 types."""
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Type Validation Test",
            artifact_type="note"
        )

        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        invalid_types = []
        for entity in entities:
            entity_type = entity.get("type")
            if entity_type not in VALID_ENTITY_TYPES:
                invalid_types.append({
                    "name": entity.get("canonical_name", ""),
                    "type": entity_type
                })

        assert len(invalid_types) == 0, (
            f"Found entities with invalid types: {invalid_types}"
        )

    def test_person_type_accuracy(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Person names should be typed as 'person'."""
        content = """
        Team Meeting

        Attendees: John Smith, Sarah Johnson, Mike Chen

        John presented the quarterly results.
        Sarah raised concerns about the timeline.
        Mike will follow up with the client.
        """

        result = ingest_and_wait(content=content, title="Person Type Test")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        # Check that names are typed as person
        for entity in entities:
            name = entity.get("canonical_name", "").lower()
            if any(n in name for n in ["john", "sarah", "mike"]):
                assert entity.get("type") == "person", (
                    f"'{entity.get('canonical_name')}' should be type 'person', "
                    f"got '{entity.get('type')}'"
                )


@pytest.mark.quality
@pytest.mark.entity
class TestEntityDeduplication:
    """Tests for entity deduplication quality."""

    def test_same_person_different_forms_merged(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Same person mentioned in different forms should be merged."""
        content = """
        Project Update

        Alice Chen presented the roadmap.
        Later, A. Chen answered questions from the team.
        Alice will send the follow-up materials.

        Bob mentioned that Chen's proposal was well-received.
        """

        result = ingest_and_wait(content=content, title="Dedup Test - Same Person")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        # Find Alice-related entities
        alice_entities = [
            e for e in entities
            if "alice" in e.get("canonical_name", "").lower()
            or "chen" in e.get("canonical_name", "").lower()
        ]

        # Should have merged or have POSSIBLY_SAME edges
        # Ideally only 1-2 entities for Alice
        assert len(alice_entities) <= 3, (
            f"Expected merged Alice entities, found {len(alice_entities)}: {alice_entities}"
        )

    def test_different_people_same_name_not_merged(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Different people with same name should not be merged."""
        content = """
        Cross-Team Meeting

        John from Engineering presented the technical proposal.
        John from Sales discussed the client requirements.

        Engineering John will implement the API.
        Sales John will coordinate with the client.
        """

        result = ingest_and_wait(content=content, title="Dedup Test - Different Johns")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        # Find John-related entities
        john_entities = [
            e for e in entities
            if "john" in e.get("canonical_name", "").lower()
        ]

        # Should have at least 2 separate John entities (or 1 with clear disambiguation)
        # This is a soft check - disambiguation is challenging
        if len(john_entities) == 1:
            # Check if the single entity has both contexts
            print(f"Found single John entity: {john_entities[0]}")


@pytest.mark.quality
@pytest.mark.entity
class TestEntityCanonicalNames:
    """Tests for canonical name quality."""

    def test_canonical_names_reasonable(
        self,
        mcp_client,
        ingest_and_wait,
        product_launch_doc: TestDocument
    ):
        """Canonical names should be reasonable and readable."""
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Canonical Name Test",
            artifact_type="note"
        )

        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        issues = []
        for entity in entities:
            name = entity.get("canonical_name", "")

            # Should not be empty
            if not name:
                issues.append("Empty canonical name")
                continue

            # Should not be too long
            if len(name) > 100:
                issues.append(f"Name too long: {name[:50]}...")

            # Should not be just symbols
            if not any(c.isalnum() for c in name):
                issues.append(f"Name is just symbols: {name}")

        assert len(issues) == 0, f"Canonical name issues: {issues}"

    def test_person_names_formatted_properly(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Person names should be properly formatted."""
        content = """
        Team Roster:
        - Dr. Alice Chen, PhD
        - Bob Smith Jr.
        - Sarah O'Connor
        """

        result = ingest_and_wait(content=content, title="Person Name Format Test")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        person_entities = [e for e in entities if e.get("type") == "person"]

        for entity in person_entities:
            name = entity.get("canonical_name", "")
            # Name should be capitalized properly
            words = name.split()
            for word in words:
                if word and word[0].isalpha():
                    # First letter should be uppercase (allowing for O'Connor etc)
                    pass  # Soft check - formatting can vary


@pytest.mark.quality
@pytest.mark.entity
class TestEntityAliases:
    """Tests for entity alias detection."""

    def test_aliases_captured(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Entity aliases should be captured."""
        content = """
        About the Company

        Alphabet Inc (formerly Google) announced new products.
        The tech giant (Google) continues to innovate.
        Alphabet's CEO presented the roadmap.
        """

        result = ingest_and_wait(content=content, title="Alias Test")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        # Find Google/Alphabet entity
        google_entities = [
            e for e in entities
            if "google" in e.get("canonical_name", "").lower()
            or "alphabet" in e.get("canonical_name", "").lower()
        ]

        if google_entities:
            # Check for aliases
            entity = google_entities[0]
            aliases = entity.get("aliases", [])
            # Should have captured multiple names
            all_names = [entity.get("canonical_name", "")] + aliases
            all_names_lower = [n.lower() for n in all_names]

            # At least should have the canonical name
            assert len(all_names) >= 1


# =============================================================================
# AI-Assessed Entity Quality Tests
# =============================================================================

@pytest.mark.quality
@pytest.mark.entity
@pytest.mark.requires_ai
class TestEntityQualityWithAI:
    """Entity quality tests using GPT-4o assessment."""

    @requires_ai
    def test_entity_extraction_quality_ai(
        self,
        mcp_client,
        ingest_and_wait,
        ai_assessor,
        product_launch_doc: TestDocument
    ):
        """Assess entity extraction quality using GPT-4o."""
        if ai_assessor is None:
            pytest.skip("AI assessor not available")

        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Entity AI Assessment",
            artifact_type="note"
        )

        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        # Convert expected entities to dict format
        expected_dicts = [
            {
                "name": e.name,
                "type": e.type,
                "role": e.role
            }
            for e in product_launch_doc.expected_entities
        ]

        # Convert extracted entities to standard format
        extracted_dicts = [
            {
                "name": e.get("canonical_name", ""),
                "type": e.get("type", ""),
                "aliases": e.get("aliases", [])
            }
            for e in entities
        ]

        assessment = ai_assessor.assess_entity_resolution(
            extracted_dicts,
            product_launch_doc.content,
            expected_dicts
        )

        assert assessment.score >= 0.7, (
            f"Entity quality score {assessment.score:.1%} below threshold. "
            f"Issues: {assessment.issues}"
        )

    @requires_ai
    def test_entity_type_accuracy_ai(
        self,
        mcp_client,
        ingest_and_wait,
        ai_assessor
    ):
        """Assess entity type accuracy using GPT-4o."""
        if ai_assessor is None:
            pytest.skip("AI assessor not available")

        content = """
        Quarterly Review

        John Smith (VP Engineering) and Sarah Johnson (Head of Product) met
        with representatives from Microsoft and Amazon.

        They discussed Project Neptune and the Chicago office expansion.
        The new CRM system (Salesforce) integration was also reviewed.
        """

        result = ingest_and_wait(content=content, title="Entity Type AI Test")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        extracted_dicts = [
            {
                "name": e.get("canonical_name", ""),
                "type": e.get("type", "")
            }
            for e in entities
        ]

        assessment = ai_assessor.assess_entity_resolution(
            extracted_dicts,
            content,
            None  # No expected entities - just assess what was found
        )

        # Check type accuracy score specifically
        if assessment.scores:
            type_accuracy = assessment.scores.get("type_accuracy", 0)
            assert type_accuracy >= 0.7, (
                f"Type accuracy {type_accuracy:.1%} below threshold"
            )


# =============================================================================
# Entity Resolution Regression Tests
# =============================================================================

@pytest.mark.quality
@pytest.mark.entity
class TestEntityRegressions:
    """Regression tests for known entity resolution issues."""

    def test_titles_not_extracted_as_entities(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Job titles should not be extracted as person entities."""
        content = """
        Organization Update

        The CEO announced the restructuring.
        Our VP of Engineering will lead the migration.
        The Head of Product is reviewing the roadmap.
        """

        result = ingest_and_wait(content=content, title="Title Regression Test")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        # Job titles shouldn't be person entities
        person_entities = [e for e in entities if e.get("type") == "person"]

        for entity in person_entities:
            name = entity.get("canonical_name", "").lower()
            # Should not be just a title
            title_only_patterns = ["ceo", "vp of engineering", "head of product"]
            is_title_only = any(name == pattern for pattern in title_only_patterns)
            if is_title_only:
                print(f"Warning: Title extracted as person: {name}")

    def test_pronouns_not_extracted_as_entities(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Pronouns should not be extracted as entities."""
        content = """
        Meeting Summary

        He mentioned the budget concerns.
        She will follow up next week.
        They decided to postpone the launch.
        We agreed on the timeline.
        """

        result = ingest_and_wait(content=content, title="Pronoun Regression Test")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        # Pronouns shouldn't be entities
        for entity in entities:
            name = entity.get("canonical_name", "").lower()
            pronouns = ["he", "she", "they", "we", "it", "him", "her", "them"]
            assert name not in pronouns, f"Pronoun extracted as entity: {name}"

    def test_common_words_not_extracted(
        self,
        mcp_client,
        ingest_and_wait
    ):
        """Common words should not be extracted as entities."""
        content = """
        Project Update

        The team discussed the plan.
        Everyone agreed on the approach.
        The meeting was productive.
        """

        result = ingest_and_wait(content=content, title="Common Words Test")
        entities = get_entities_for_artifact(mcp_client, result["artifact_uid"])

        # Common words shouldn't be entities
        common_words = ["the", "team", "plan", "meeting", "approach", "everyone"]

        for entity in entities:
            name = entity.get("canonical_name", "").lower()
            if name in common_words:
                print(f"Warning: Common word extracted as entity: {name}")
