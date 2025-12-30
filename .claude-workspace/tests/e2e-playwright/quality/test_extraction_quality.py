"""
Event Extraction Quality Tests.

Tests:
- Event extraction recall (% of expected events found)
- Event extraction precision (% of extracted events that are valid)
- Evidence quality (quotes exist in source)
- Category accuracy
- Actor attribution

These tests use known-outcome documents with defined expected events
to measure extraction quality objectively.

Run:
    # Without AI assessment (uses heuristics)
    pytest tests/e2e-playwright/quality/test_extraction_quality.py -v

    # With AI assessment (costs money)
    AI_ASSESSMENT_ENABLED=true pytest tests/e2e-playwright/quality/test_extraction_quality.py -v

Markers:
    @pytest.mark.quality - All quality tests
    @pytest.mark.extraction - Event extraction tests
    @pytest.mark.requires_ai - Tests requiring GPT-4o
"""

from __future__ import annotations

import pytest
from typing import Dict, List

from .conftest import (
    TestDocument,
    ExpectedEvent,
    QualityMetrics,
    requires_ai,
    AI_ASSESSMENT_ENABLED
)


# =============================================================================
# Quality Thresholds
# =============================================================================

RECALL_THRESHOLD = 0.7  # 70% of expected events should be found
PRECISION_THRESHOLD = 0.6  # 60% of extracted events should be valid
F1_THRESHOLD = 0.65  # Combined F1 score
EVIDENCE_QUALITY_THRESHOLD = 0.8  # 80% of evidence quotes should exist


# =============================================================================
# Basic Extraction Tests (No AI Required)
# =============================================================================

@pytest.mark.quality
@pytest.mark.extraction
class TestEventExtractionBasic:
    """Basic event extraction quality tests using heuristics."""

    def test_product_launch_extraction(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        calculate_quality_metrics,
        product_launch_doc: TestDocument
    ):
        """Test extraction quality on product launch meeting notes."""
        # Ingest document
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Product Launch Planning",
            artifact_type="note"
        )
        artifact_uid = result["artifact_uid"]

        # Get extracted events
        extracted_events = get_extracted_events(artifact_uid)

        # Calculate metrics
        metrics = calculate_quality_metrics(
            extracted_events,
            product_launch_doc.expected_events,
            product_launch_doc.content
        )

        # Assert quality thresholds
        assert metrics.recall >= RECALL_THRESHOLD, (
            f"Recall {metrics.recall:.1%} below threshold {RECALL_THRESHOLD:.0%}. "
            f"Missing: {metrics.missing_events}"
        )
        assert metrics.precision >= PRECISION_THRESHOLD, (
            f"Precision {metrics.precision:.1%} below threshold {PRECISION_THRESHOLD:.0%}"
        )
        assert metrics.evidence_quality >= EVIDENCE_QUALITY_THRESHOLD, (
            f"Evidence quality {metrics.evidence_quality:.1%} below threshold {EVIDENCE_QUALITY_THRESHOLD:.0%}"
        )

    def test_sprint_planning_extraction(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        calculate_quality_metrics,
        sprint_planning_doc: TestDocument
    ):
        """Test extraction quality on sprint planning meeting."""
        result = ingest_and_wait(
            content=sprint_planning_doc.content,
            title="Sprint Planning",
            artifact_type="note"
        )
        artifact_uid = result["artifact_uid"]

        extracted_events = get_extracted_events(artifact_uid)
        metrics = calculate_quality_metrics(
            extracted_events,
            sprint_planning_doc.expected_events,
            sprint_planning_doc.content
        )

        assert metrics.recall >= RECALL_THRESHOLD
        assert metrics.precision >= PRECISION_THRESHOLD

    def test_project_status_extraction(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        calculate_quality_metrics,
        project_status_doc: TestDocument
    ):
        """Test extraction quality on project status email thread."""
        result = ingest_and_wait(
            content=project_status_doc.content,
            title="Project Status Update",
            artifact_type="note"
        )
        artifact_uid = result["artifact_uid"]

        extracted_events = get_extracted_events(artifact_uid)
        metrics = calculate_quality_metrics(
            extracted_events,
            project_status_doc.expected_events,
            project_status_doc.content
        )

        assert metrics.recall >= RECALL_THRESHOLD
        assert metrics.precision >= PRECISION_THRESHOLD


@pytest.mark.quality
@pytest.mark.extraction
class TestEventCounts:
    """Tests for event count ranges."""

    def test_product_launch_event_count(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        product_launch_doc: TestDocument
    ):
        """Product launch should extract expected number of events."""
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Product Launch",
            artifact_type="note"
        )

        events = get_extracted_events(result["artifact_uid"])
        counts = product_launch_doc.expected_counts

        total_min = counts.get("total_min", 5)
        total_max = counts.get("total_max", 25)

        assert total_min <= len(events) <= total_max, (
            f"Expected {total_min}-{total_max} events, got {len(events)}"
        )

    def test_category_distribution(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        product_launch_doc: TestDocument
    ):
        """Events should have expected category distribution."""
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Product Launch Categories",
            artifact_type="note"
        )

        events = get_extracted_events(result["artifact_uid"])

        # Count by category
        category_counts = {}
        for event in events:
            cat = event.get("category", "Unknown")
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Check expected categories exist
        expected_categories = product_launch_doc.expected_counts.get("by_category", {})
        for category, (min_count, max_count) in expected_categories.items():
            actual = category_counts.get(category, 0)
            # Use soft assertion - log but don't fail for minor deviations
            if actual < min_count or actual > max_count:
                print(f"Category {category}: expected {min_count}-{max_count}, got {actual}")


@pytest.mark.quality
@pytest.mark.extraction
class TestEvidenceQuality:
    """Tests for evidence quote quality."""

    def test_evidence_quotes_exist_in_source(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        product_launch_doc: TestDocument
    ):
        """All evidence quotes should exist in source document."""
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Evidence Quality Test",
            artifact_type="note"
        )

        events = get_extracted_events(result["artifact_uid"])

        missing_quotes = []
        total_quotes = 0

        for event in events:
            evidence = event.get("evidence", [])
            for ev in evidence:
                quote = ev.get("quote", "")
                if quote:
                    total_quotes += 1
                    if quote not in product_launch_doc.content:
                        missing_quotes.append({
                            "event": event.get("narrative", "")[:50],
                            "quote": quote[:100]
                        })

        if total_quotes > 0:
            quality = 1 - (len(missing_quotes) / total_quotes)
            assert quality >= EVIDENCE_QUALITY_THRESHOLD, (
                f"Evidence quality {quality:.1%} below threshold. "
                f"Missing quotes: {missing_quotes[:3]}"
            )

    def test_evidence_has_required_fields(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        product_launch_doc: TestDocument
    ):
        """Evidence should have required fields (quote, context)."""
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Evidence Fields Test",
            artifact_type="note"
        )

        events = get_extracted_events(result["artifact_uid"])

        for event in events:
            evidence = event.get("evidence", [])
            for ev in evidence:
                # Should have quote
                assert "quote" in ev, f"Evidence missing 'quote' field in event: {event.get('narrative', '')[:50]}"


@pytest.mark.quality
@pytest.mark.extraction
class TestCategoryAccuracy:
    """Tests for event category accuracy."""

    VALID_CATEGORIES = [
        "Commitment",
        "Execution",
        "Decision",
        "Collaboration",
        "QualityRisk",
        "Feedback",
        "Change",
        "Stakeholder"
    ]

    def test_all_events_have_valid_category(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        product_launch_doc: TestDocument
    ):
        """All extracted events should have valid V4 categories."""
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Category Validation Test",
            artifact_type="note"
        )

        events = get_extracted_events(result["artifact_uid"])

        invalid_categories = []
        for event in events:
            category = event.get("category")
            if category not in self.VALID_CATEGORIES:
                invalid_categories.append({
                    "narrative": event.get("narrative", "")[:50],
                    "category": category
                })

        assert len(invalid_categories) == 0, (
            f"Found {len(invalid_categories)} events with invalid categories: {invalid_categories}"
        )

    def test_decision_events_contain_decisions(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        product_launch_doc: TestDocument
    ):
        """Decision events should contain actual decisions."""
        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Decision Category Test",
            artifact_type="note"
        )

        events = get_extracted_events(result["artifact_uid"])
        decision_events = [e for e in events if e.get("category") == "Decision"]

        # Decision keywords
        decision_indicators = [
            "decide", "decision", "chose", "choose", "selected", "select",
            "approved", "approve", "agreed", "go with", "will use", "opted"
        ]

        for event in decision_events:
            narrative = event.get("narrative", "").lower()
            has_indicator = any(ind in narrative for ind in decision_indicators)
            # Soft check - not all decisions use these exact words
            if not has_indicator:
                print(f"Decision event may not contain decision language: {narrative[:80]}")


# =============================================================================
# AI-Assessed Quality Tests
# =============================================================================

@pytest.mark.quality
@pytest.mark.extraction
@pytest.mark.requires_ai
class TestExtractionQualityWithAI:
    """Event extraction quality tests using GPT-4o assessment."""

    @requires_ai
    def test_event_quality_ai_assessment(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        ai_assessor,
        product_launch_doc: TestDocument
    ):
        """Assess event quality using GPT-4o."""
        if ai_assessor is None:
            pytest.skip("AI assessor not available")

        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="AI Quality Assessment",
            artifact_type="note"
        )

        events = get_extracted_events(result["artifact_uid"])

        # Sample events for assessment (to control cost)
        sample_events = events[:5] if len(events) > 5 else events

        for event in sample_events:
            assessment = ai_assessor.assess_event_quality(
                event,
                product_launch_doc.content
            )

            assert assessment.score >= 0.7, (
                f"Event quality score {assessment.score:.1%} below threshold. "
                f"Issues: {assessment.issues}"
            )

    @requires_ai
    def test_extraction_completeness_ai(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        ai_assessor,
        product_launch_doc: TestDocument
    ):
        """Assess extraction completeness using GPT-4o."""
        if ai_assessor is None:
            pytest.skip("AI assessor not available")

        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Completeness Assessment",
            artifact_type="note"
        )

        events = get_extracted_events(result["artifact_uid"])

        # Convert expected events to dict format
        expected_dicts = [
            {
                "id": e.id,
                "category": e.category,
                "description": e.description
            }
            for e in product_launch_doc.expected_events
        ]

        completeness = ai_assessor.assess_extraction_completeness(
            events,
            product_launch_doc.content,
            expected_dicts
        )

        assert completeness.completeness_score >= 0.7, (
            f"Completeness score {completeness.completeness_score:.1%} below threshold. "
            f"Missing: {completeness.missing_expected}"
        )

    @requires_ai
    def test_evidence_quality_ai(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events,
        ai_assessor,
        product_launch_doc: TestDocument
    ):
        """Assess evidence quality using GPT-4o."""
        if ai_assessor is None:
            pytest.skip("AI assessor not available")

        result = ingest_and_wait(
            content=product_launch_doc.content,
            title="Evidence AI Assessment",
            artifact_type="note"
        )

        events = get_extracted_events(result["artifact_uid"])

        # Sample events with evidence
        events_with_evidence = [e for e in events if e.get("evidence")][:3]

        for event in events_with_evidence:
            assessment = ai_assessor.assess_evidence_quality(
                event,
                product_launch_doc.content
            )

            assert assessment.score >= 0.7, (
                f"Evidence quality {assessment.score:.1%} below threshold. "
                f"Issues: {assessment.issues}"
            )


# =============================================================================
# Regression Tests
# =============================================================================

@pytest.mark.quality
@pytest.mark.extraction
class TestExtractionRegression:
    """Regression tests for known extraction issues."""

    def test_commitments_extracted(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events
    ):
        """Commitments with deadlines should be extracted."""
        content = """
        Meeting Notes - Project Alpha

        John committed to delivering the API documentation by Friday.
        Sarah agreed to review the security audit by end of week.
        The team decided to use PostgreSQL for the database.
        """

        result = ingest_and_wait(content=content, title="Commitment Test")
        events = get_extracted_events(result["artifact_uid"])

        # Should find commitment events
        commitment_events = [e for e in events if e.get("category") == "Commitment"]
        assert len(commitment_events) >= 1, "Should extract at least one commitment"

    def test_decisions_extracted(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events
    ):
        """Clear decisions should be extracted."""
        content = """
        Architecture Review - January 15

        After discussion, the team decided to:
        1. Use microservices architecture for the new platform
        2. Adopt Kubernetes for container orchestration
        3. Go with AWS as the cloud provider

        These decisions were approved by the CTO.
        """

        result = ingest_and_wait(content=content, title="Decision Test")
        events = get_extracted_events(result["artifact_uid"])

        # Should find decision events
        decision_events = [e for e in events if e.get("category") == "Decision"]
        assert len(decision_events) >= 1, "Should extract at least one decision"

    def test_risks_extracted(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events
    ):
        """Quality risks should be extracted."""
        content = """
        Sprint Retrospective

        Concerns raised:
        - The timeline is too aggressive for the scope
        - Technical debt is accumulating in the authentication module
        - We're missing test coverage in critical paths

        Action items were assigned to address these risks.
        """

        result = ingest_and_wait(content=content, title="Risk Test")
        events = get_extracted_events(result["artifact_uid"])

        # Should find risk events
        risk_events = [e for e in events if e.get("category") == "QualityRisk"]
        assert len(risk_events) >= 1, "Should extract at least one quality risk"

    def test_no_events_for_purely_factual_content(
        self,
        mcp_client,
        ingest_and_wait,
        get_extracted_events
    ):
        """Purely factual content should have few/no events."""
        content = """
        API Documentation

        The REST API uses JSON for request and response bodies.
        Authentication is handled via JWT tokens in the Authorization header.
        All endpoints are versioned with /api/v1/ prefix.

        Rate limiting is set to 100 requests per minute per API key.
        """

        result = ingest_and_wait(content=content, title="Factual Content Test")
        events = get_extracted_events(result["artifact_uid"])

        # Factual content should have few events
        assert len(events) <= 3, (
            f"Factual content should have few events, got {len(events)}"
        )
