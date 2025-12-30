"""
Pytest Configuration for Quality Tests with AI Assessment.

Provides:
- AI assessment fixtures (GPT-4o integration)
- Test document fixtures with expected outcomes
- Quality metric calculation utilities
- Skip conditions for AI-gated tests
"""

from __future__ import annotations

import os
import json
import pytest
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# Add lib directory to path
import sys
LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from mcp_client import MCPClient


# =============================================================================
# Environment Configuration
# =============================================================================

AI_ASSESSMENT_ENABLED = os.getenv("AI_ASSESSMENT_ENABLED", "false").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_ASSESSMENT_MODEL = os.getenv("AI_ASSESSMENT_MODEL", "gpt-4o")

MCP_URL = os.getenv("MCP_URL", "http://localhost:3201/mcp/")

# Timeouts for extraction (longer for quality tests)
EXTRACTION_TIMEOUT = 120  # 2 minutes
POLL_INTERVAL = 3.0


# =============================================================================
# Skip Conditions
# =============================================================================

requires_ai = pytest.mark.skipif(
    not AI_ASSESSMENT_ENABLED or not OPENAI_API_KEY,
    reason="AI assessment disabled or OPENAI_API_KEY not set"
)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ExpectedEvent:
    """Expected event for quality validation."""
    id: str
    category: str
    description: str
    search_terms: List[str]
    actors: List[str]
    required: bool = True


@dataclass
class ExpectedEntity:
    """Expected entity for quality validation."""
    name: str
    type: str
    role: Optional[str] = None
    aliases: Optional[List[str]] = None


@dataclass
class TestDocument:
    """Test document with content and expected outcomes."""
    name: str
    content: str
    artifact_type: str
    expected_events: List[ExpectedEvent]
    expected_entities: List[ExpectedEntity]
    expected_counts: Dict[str, Any]

    @classmethod
    def load(cls, doc_name: str) -> "TestDocument":
        """Load document and expected outcomes from fixtures."""
        fixtures_path = Path(__file__).parent.parent / "lib" / "fixtures"

        # Find document file
        doc_path = None
        for subdir in ["meeting_notes", "emails", "chats", "technical"]:
            candidate = fixtures_path / "documents" / subdir / doc_name
            if candidate.exists():
                doc_path = candidate
                break

        if not doc_path:
            # Try direct path
            doc_path = fixtures_path / "documents" / doc_name

        if not doc_path.exists():
            raise FileNotFoundError(f"Document not found: {doc_name}")

        content = doc_path.read_text()

        # Load expected outcomes
        expected_name = doc_name.replace(".md", ".json")
        events_path = fixtures_path / "expected" / "events" / expected_name
        entities_path = fixtures_path / "expected" / "entities" / expected_name

        expected_events = []
        expected_entities = []
        expected_counts = {}

        if events_path.exists():
            events_data = json.loads(events_path.read_text())
            expected_events = [
                ExpectedEvent(
                    id=e.get("id", ""),
                    category=e.get("category", ""),
                    description=e.get("description", ""),
                    search_terms=e.get("search_terms", []),
                    actors=e.get("actors", []),
                    required=e.get("required", True)
                )
                for e in events_data.get("expected_events", [])
            ]
            expected_counts = events_data.get("expected_counts", {})

        if entities_path.exists():
            entities_data = json.loads(entities_path.read_text())
            expected_entities = [
                ExpectedEntity(
                    name=e.get("name", ""),
                    type=e.get("type", ""),
                    role=e.get("role"),
                    aliases=e.get("aliases")
                )
                for e in entities_data.get("expected_entities", [])
            ]

        return cls(
            name=doc_name,
            content=content,
            artifact_type="note",
            expected_events=expected_events,
            expected_entities=expected_entities,
            expected_counts=expected_counts
        )


# =============================================================================
# MCP Client Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def mcp_client() -> MCPClient:
    """Session-scoped MCP client."""
    client = MCPClient(base_url=MCP_URL)
    if not client.initialize():
        pytest.skip("Could not connect to MCP server")
    yield client
    client.close()


# =============================================================================
# AI Assessor Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def ai_assessor():
    """Session-scoped AI assessor (GPT-4o)."""
    if not AI_ASSESSMENT_ENABLED or not OPENAI_API_KEY:
        return None

    from .assessor import AIAssessor
    return AIAssessor(api_key=OPENAI_API_KEY, model=AI_ASSESSMENT_MODEL)


# =============================================================================
# Test Document Fixtures
# =============================================================================

@pytest.fixture
def product_launch_doc() -> TestDocument:
    """Product launch meeting notes with expected outcomes."""
    return TestDocument.load("product_launch.md")


@pytest.fixture
def sprint_planning_doc() -> TestDocument:
    """Sprint planning meeting with expected outcomes."""
    return TestDocument.load("sprint_planning.md")


@pytest.fixture
def project_status_doc() -> TestDocument:
    """Project status email thread with expected outcomes."""
    return TestDocument.load("project_status.md")


@pytest.fixture
def all_test_documents() -> List[TestDocument]:
    """Load all available test documents."""
    fixtures_path = Path(__file__).parent.parent / "lib" / "fixtures" / "documents"
    documents = []

    for subdir in ["meeting_notes", "emails"]:
        subdir_path = fixtures_path / subdir
        if subdir_path.exists():
            for doc_file in subdir_path.glob("*.md"):
                try:
                    doc = TestDocument.load(doc_file.name)
                    documents.append(doc)
                except Exception:
                    pass

    return documents


# =============================================================================
# Extraction Helper Fixtures
# =============================================================================

@pytest.fixture
def ingest_and_wait(mcp_client: MCPClient):
    """Factory to ingest document and wait for extraction."""
    def _ingest(content: str, title: str, artifact_type: str = "note") -> Dict:
        # Ingest document
        result = mcp_client.call_tool("artifact_ingest", {
            "content": content,
            "artifact_type": artifact_type,
            "source_system": "quality-test",
            "title": title,
            "source_id": f"quality-test-{title.replace(' ', '-').lower()}"
        })

        if not result.success:
            raise Exception(f"Ingest failed: {result.error}")

        artifact_uid = result.data.get("artifact_uid")
        job_id = result.data.get("job_id")

        if not artifact_uid:
            raise Exception("No artifact_uid in response")

        # Wait for extraction to complete
        import time
        start_time = time.time()
        while time.time() - start_time < EXTRACTION_TIMEOUT:
            if job_id:
                status_result = mcp_client.call_tool("job_status", {"job_id": job_id})
                if status_result.success:
                    status = status_result.data.get("status", "")
                    if status == "completed":
                        break
                    elif status == "failed":
                        raise Exception(f"Extraction job failed: {status_result.data}")

            time.sleep(POLL_INTERVAL)

        return {
            "artifact_uid": artifact_uid,
            "job_id": job_id
        }

    return _ingest


@pytest.fixture
def get_extracted_events(mcp_client: MCPClient):
    """Factory to get extracted events for an artifact."""
    def _get(artifact_uid: str) -> List[Dict]:
        result = mcp_client.call_tool("event_list_for_artifact", {
            "artifact_uid": artifact_uid,
            "include_evidence": True
        })

        if not result.success:
            return []

        return result.data.get("events", [])

    return _get


# =============================================================================
# Quality Metric Calculation
# =============================================================================

@dataclass
class QualityMetrics:
    """Quality metrics for extraction validation."""
    recall: float
    precision: float
    f1_score: float
    evidence_quality: float
    matched_events: List[str]
    missing_events: List[str]
    extra_events: int


@pytest.fixture
def calculate_quality_metrics():
    """Factory to calculate quality metrics."""
    def _calculate(
        extracted_events: List[Dict],
        expected_events: List[ExpectedEvent],
        source_content: str
    ) -> QualityMetrics:
        matched = []
        missing = []

        # Calculate recall - what % of expected events were found
        for expected in expected_events:
            found = False
            for extracted in extracted_events:
                if _events_match(expected, extracted):
                    found = True
                    matched.append(expected.id)
                    break

            if not found and expected.required:
                missing.append(expected.id)

        recall = len(matched) / len(expected_events) if expected_events else 1.0

        # Calculate precision - what % of extracted events are valid
        valid_count = 0
        for event in extracted_events:
            if _is_valid_event(event, source_content):
                valid_count += 1

        precision = valid_count / len(extracted_events) if extracted_events else 1.0

        # Calculate F1 score
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        # Calculate evidence quality
        evidence_quality = _calculate_evidence_quality(extracted_events, source_content)

        return QualityMetrics(
            recall=recall,
            precision=precision,
            f1_score=f1_score,
            evidence_quality=evidence_quality,
            matched_events=matched,
            missing_events=missing,
            extra_events=len(extracted_events) - len(matched)
        )

    return _calculate


def _events_match(expected: ExpectedEvent, extracted: Dict) -> bool:
    """Check if extracted event matches expected event."""
    # Category must match
    if extracted.get("category", "").lower() != expected.category.lower():
        return False

    # Check if any search terms appear in narrative
    narrative = extracted.get("narrative", "").lower()
    for term in expected.search_terms:
        if term.lower() in narrative:
            return True

    return False


def _is_valid_event(event: Dict, source_content: str) -> bool:
    """Check if event is valid (not hallucinated)."""
    # Must have category and narrative
    if not event.get("category") or not event.get("narrative"):
        return False

    # Must have valid category
    valid_categories = [
        "Commitment", "Execution", "Decision", "Collaboration",
        "QualityRisk", "Feedback", "Change", "Stakeholder"
    ]
    if event.get("category") not in valid_categories:
        return False

    # Evidence should exist in source (if provided)
    evidence = event.get("evidence", [])
    for ev in evidence:
        quote = ev.get("quote", "")
        if quote and quote not in source_content:
            return False

    return True


def _calculate_evidence_quality(events: List[Dict], source_content: str) -> float:
    """Calculate evidence quality score."""
    total = 0
    valid = 0

    for event in events:
        evidence = event.get("evidence", [])
        for ev in evidence:
            total += 1
            quote = ev.get("quote", "")
            if quote and quote in source_content:
                valid += 1

    return valid / total if total > 0 else 1.0


# =============================================================================
# Marker Registration
# =============================================================================

def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "quality: Quality assessment tests (may use GPT-4o)"
    )
    config.addinivalue_line(
        "markers",
        "requires_ai: Tests requiring AI assessment (GPT-4o)"
    )
    config.addinivalue_line(
        "markers",
        "extraction: Event extraction quality tests"
    )
    config.addinivalue_line(
        "markers",
        "entity: Entity resolution quality tests"
    )
