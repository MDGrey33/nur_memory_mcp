"""
AI Assessor for Quality Tests.

Uses GPT-4o for intelligent assessment of:
- Event extraction quality
- Entity resolution correctness
- Evidence relevance
- Hallucination detection

Usage:
    assessor = AIAssessor(api_key="...", model="gpt-4o")
    result = assessor.assess_event_quality(event, source_document)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@dataclass
class AssessmentResult:
    """Result of AI assessment."""
    score: float  # 0.0 to 1.0
    reasoning: str
    issues: List[str]
    suggestions: List[str]
    scores: Optional[Dict[str, float]] = None


@dataclass
class CompletenessResult:
    """Result of extraction completeness assessment."""
    completeness_score: float
    matched_expected: List[str]
    missing_expected: List[str]
    unexpected_but_valid: List[str]
    false_positives: List[str]
    reasoning: str


class AIAssessor:
    """GPT-4o-based assessment for extraction quality."""

    def __init__(self, api_key: str = None, model: str = "gpt-4o"):
        """
        Initialize AI Assessor.

        Args:
            api_key: OpenAI API key. If not provided, uses OPENAI_API_KEY env var.
            model: Model to use for assessment. Default: gpt-4o
        """
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package not installed. Run: pip install openai")

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required")

        self.client = openai.OpenAI(api_key=self.api_key)
        self.model = model

    def assess_event_quality(
        self,
        event: Dict,
        source_document: str,
        expected_outcomes: Optional[Dict] = None
    ) -> AssessmentResult:
        """
        Assess quality of a single extracted event.

        Args:
            event: The extracted event to assess
            source_document: Original source document
            expected_outcomes: Optional expected outcomes for comparison

        Returns:
            AssessmentResult with scores and feedback
        """
        prompt = f"""Assess the quality of this extracted event:

SOURCE DOCUMENT:
{source_document[:3000]}{"..." if len(source_document) > 3000 else ""}

EXTRACTED EVENT:
Category: {event.get('category')}
Narrative: {event.get('narrative')}
Actors: {event.get('actors', [])}
Evidence: {json.dumps(event.get('evidence', []), indent=2)}

ASSESSMENT CRITERIA:
1. Narrative Coherence (0-1): Does the narrative make sense as a standalone statement?
2. Category Accuracy (0-1): Is the category appropriate for this content?
3. Actor Attribution (0-1): Are actors correctly identified from the source?
4. Evidence Validity (0-1): Do evidence quotes exist in the source and support the event?
5. Hallucination Check (0-1): Is all information grounded in the source? (1 = no hallucination)

Respond in JSON format:
{{
    "overall_score": 0.0-1.0,
    "scores": {{
        "narrative_coherence": 0.0-1.0,
        "category_accuracy": 0.0-1.0,
        "actor_attribution": 0.0-1.0,
        "evidence_validity": 0.0-1.0,
        "no_hallucination": 0.0-1.0
    }},
    "reasoning": "Brief explanation",
    "issues": ["List of specific issues found"],
    "suggestions": ["List of improvements"]
}}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1
        )

        result = json.loads(response.choices[0].message.content)
        return AssessmentResult(
            score=result.get("overall_score", 0.0),
            reasoning=result.get("reasoning", ""),
            issues=result.get("issues", []),
            suggestions=result.get("suggestions", []),
            scores=result.get("scores")
        )

    def assess_extraction_completeness(
        self,
        extracted_events: List[Dict],
        source_document: str,
        expected_events: List[Dict]
    ) -> CompletenessResult:
        """
        Assess whether all expected events were extracted.

        Args:
            extracted_events: List of extracted events
            source_document: Original source document
            expected_events: List of expected events

        Returns:
            CompletenessResult with matching analysis
        """
        # Simplify events for prompt
        simplified_extracted = [
            {
                "category": e.get("category"),
                "narrative": e.get("narrative")
            }
            for e in extracted_events
        ]

        simplified_expected = [
            {
                "id": e.get("id", f"exp_{i}"),
                "category": e.get("category"),
                "description": e.get("description")
            }
            for i, e in enumerate(expected_events)
        ]

        prompt = f"""Compare extracted events against expected events.

SOURCE DOCUMENT:
{source_document[:3000]}{"..." if len(source_document) > 3000 else ""}

EXPECTED EVENTS:
{json.dumps(simplified_expected, indent=2)}

EXTRACTED EVENTS:
{json.dumps(simplified_extracted, indent=2)}

For each expected event, determine if it was captured by any extracted event.
Consider semantic equivalence, not exact matching.

Respond in JSON format:
{{
    "completeness_score": 0.0-1.0,
    "matched_expected": ["list of expected event IDs that were found"],
    "missing_expected": ["list of expected event IDs that were NOT found"],
    "unexpected_but_valid": ["narratives of extra events that seem valid"],
    "false_positives": ["narratives of extracted events that seem incorrect"],
    "reasoning": "Brief explanation"
}}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1
        )

        result = json.loads(response.choices[0].message.content)
        return CompletenessResult(
            completeness_score=result.get("completeness_score", 0.0),
            matched_expected=result.get("matched_expected", []),
            missing_expected=result.get("missing_expected", []),
            unexpected_but_valid=result.get("unexpected_but_valid", []),
            false_positives=result.get("false_positives", []),
            reasoning=result.get("reasoning", "")
        )

    def assess_entity_resolution(
        self,
        entities: List[Dict],
        source_document: str,
        expected_entities: Optional[List[Dict]] = None
    ) -> AssessmentResult:
        """
        Assess entity extraction and resolution quality.

        Args:
            entities: Extracted entities
            source_document: Original source document
            expected_entities: Optional expected entities

        Returns:
            AssessmentResult with scores and feedback
        """
        prompt = f"""Assess the quality of entity extraction and resolution:

SOURCE DOCUMENT:
{source_document[:3000]}{"..." if len(source_document) > 3000 else ""}

EXTRACTED ENTITIES:
{json.dumps(entities, indent=2)}

{"EXPECTED ENTITIES:" + chr(10) + json.dumps(expected_entities, indent=2) if expected_entities else ""}

ASSESSMENT CRITERIA:
1. Completeness (0-1): Are all mentioned entities extracted?
2. Type Accuracy (0-1): Are entity types (person, org, project, etc.) correct?
3. Deduplication (0-1): Are duplicate mentions properly merged?
4. Canonical Names (0-1): Are canonical names reasonable and consistent?
5. Alias Detection (0-1): Are aliases/variations properly identified?

Respond in JSON format:
{{
    "overall_score": 0.0-1.0,
    "scores": {{
        "completeness": 0.0-1.0,
        "type_accuracy": 0.0-1.0,
        "deduplication": 0.0-1.0,
        "canonical_names": 0.0-1.0,
        "alias_detection": 0.0-1.0
    }},
    "reasoning": "Brief explanation",
    "issues": ["List of specific issues found"],
    "suggestions": ["List of improvements"]
}}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1
        )

        result = json.loads(response.choices[0].message.content)
        return AssessmentResult(
            score=result.get("overall_score", 0.0),
            reasoning=result.get("reasoning", ""),
            issues=result.get("issues", []),
            suggestions=result.get("suggestions", []),
            scores=result.get("scores")
        )

    def assess_evidence_quality(
        self,
        event: Dict,
        source_document: str
    ) -> AssessmentResult:
        """
        Assess quality of evidence quotes for an event.

        Args:
            event: Event with evidence
            source_document: Original source document

        Returns:
            AssessmentResult with scores and feedback
        """
        evidence = event.get("evidence", [])

        prompt = f"""Assess the quality of evidence quotes for this event:

SOURCE DOCUMENT:
{source_document[:3000]}{"..." if len(source_document) > 3000 else ""}

EVENT:
Category: {event.get('category')}
Narrative: {event.get('narrative')}

EVIDENCE QUOTES:
{json.dumps(evidence, indent=2)}

ASSESSMENT CRITERIA:
1. Existence (0-1): Do quotes actually exist in the source document?
2. Relevance (0-1): Do quotes support the event narrative?
3. Completeness (0-1): Is there enough evidence to justify the event?
4. Context (0-1): Is context (speaker, etc.) correctly attributed?

Respond in JSON format:
{{
    "overall_score": 0.0-1.0,
    "scores": {{
        "existence": 0.0-1.0,
        "relevance": 0.0-1.0,
        "completeness": 0.0-1.0,
        "context": 0.0-1.0
    }},
    "reasoning": "Brief explanation",
    "issues": ["List of specific issues found"],
    "suggestions": ["List of improvements"]
}}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1
        )

        result = json.loads(response.choices[0].message.content)
        return AssessmentResult(
            score=result.get("overall_score", 0.0),
            reasoning=result.get("reasoning", ""),
            issues=result.get("issues", []),
            suggestions=result.get("suggestions", []),
            scores=result.get("scores")
        )

    def batch_assess_events(
        self,
        events: List[Dict],
        source_document: str,
        sample_size: int = 5
    ) -> List[AssessmentResult]:
        """
        Assess a batch of events (samples for efficiency).

        Args:
            events: List of events to assess
            source_document: Original source document
            sample_size: Number of events to sample

        Returns:
            List of AssessmentResults
        """
        import random

        # Sample events if too many
        if len(events) > sample_size:
            events = random.sample(events, sample_size)

        results = []
        for event in events:
            result = self.assess_event_quality(event, source_document)
            results.append(result)

        return results


class MockAIAssessor:
    """Mock AI Assessor for testing without API calls."""

    def __init__(self, **kwargs):
        pass

    def assess_event_quality(self, event: Dict, source_document: str, **kwargs) -> AssessmentResult:
        """Return mock assessment."""
        return AssessmentResult(
            score=0.85,
            reasoning="Mock assessment - event appears valid",
            issues=[],
            suggestions=[],
            scores={
                "narrative_coherence": 0.9,
                "category_accuracy": 0.85,
                "actor_attribution": 0.8,
                "evidence_validity": 0.85,
                "no_hallucination": 0.9
            }
        )

    def assess_extraction_completeness(
        self,
        extracted_events: List[Dict],
        source_document: str,
        expected_events: List[Dict]
    ) -> CompletenessResult:
        """Return mock completeness result."""
        return CompletenessResult(
            completeness_score=0.8,
            matched_expected=[f"exp_{i}" for i in range(len(expected_events) - 1)],
            missing_expected=[f"exp_{len(expected_events) - 1}"],
            unexpected_but_valid=[],
            false_positives=[],
            reasoning="Mock assessment - most events found"
        )

    def assess_entity_resolution(
        self,
        entities: List[Dict],
        source_document: str,
        expected_entities: Optional[List[Dict]] = None
    ) -> AssessmentResult:
        """Return mock entity assessment."""
        return AssessmentResult(
            score=0.85,
            reasoning="Mock assessment - entities properly resolved",
            issues=[],
            suggestions=[],
            scores={
                "completeness": 0.9,
                "type_accuracy": 0.85,
                "deduplication": 0.8,
                "canonical_names": 0.85,
                "alias_detection": 0.8
            }
        )
