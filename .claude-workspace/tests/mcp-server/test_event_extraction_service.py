"""
Unit tests for EventExtractionService.

Tests event extraction (Prompt A), canonicalization (Prompt B),
validation, and error handling.
"""

import pytest
from unittest.mock import MagicMock, patch
import json

from services.event_extraction_service import EventExtractionService, EVENT_CATEGORIES


# ============================================================================
# Service Initialization Tests
# ============================================================================

def test_service_initialization():
    """Test that EventExtractionService initializes correctly."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        service = EventExtractionService(
            api_key="test_key",
            model="gpt-4o-mini",
            temperature=0.0,
            timeout=60
        )

        mock_openai.assert_called_once_with(api_key="test_key", timeout=60)
        assert service.model == "gpt-4o-mini"
        assert service.temperature == 0.0


# ============================================================================
# Extract from Chunk Tests (Prompt A)
# ============================================================================

def test_extract_from_chunk_success(sample_chunk_text, sample_extracted_events):
    """Test successful event extraction from a chunk."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({
                        "events": [
                            {
                                "category": "Decision",
                                "narrative": "Team decided to adopt freemium pricing model",
                                "event_time": "2024-03-15T00:00:00Z",
                                "subject": {"type": "project", "ref": "pricing-model"},
                                "actors": [{"ref": "Alice Chen", "role": "owner"}],
                                "confidence": 0.95,
                                "evidence": [
                                    {
                                        "quote": "decided to adopt a freemium pricing model",
                                        "start_char": 50,
                                        "end_char": 95
                                    }
                                ]
                            }
                        ]
                    })
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        events = service.extract_from_chunk(
            chunk_text=sample_chunk_text,
            chunk_index=0,
            chunk_id="chunk_001",
            start_char=100
        )

        assert len(events) == 1
        assert events[0]["category"] == "Decision"
        assert events[0]["narrative"] == "Team decided to adopt freemium pricing model"
        # Check that offsets were adjusted
        assert events[0]["evidence"][0]["start_char"] == 150  # 50 + 100
        assert events[0]["evidence"][0]["end_char"] == 195  # 95 + 100
        assert events[0]["evidence"][0]["chunk_id"] == "chunk_001"


def test_extract_from_chunk_with_multiple_events(sample_chunk_text):
    """Test extraction of multiple events from a chunk."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({
                        "events": [
                            {
                                "category": "Decision",
                                "narrative": "Event 1",
                                "event_time": None,
                                "subject": {"type": "project", "ref": "test"},
                                "actors": [{"ref": "Alice", "role": "owner"}],
                                "confidence": 0.9,
                                "evidence": [{"quote": "quote1", "start_char": 0, "end_char": 10}]
                            },
                            {
                                "category": "Commitment",
                                "narrative": "Event 2",
                                "event_time": None,
                                "subject": {"type": "project", "ref": "test"},
                                "actors": [{"ref": "Bob", "role": "owner"}],
                                "confidence": 0.85,
                                "evidence": [{"quote": "quote2", "start_char": 20, "end_char": 30}]
                            }
                        ]
                    })
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        events = service.extract_from_chunk(
            chunk_text=sample_chunk_text,
            chunk_index=0,
            chunk_id="chunk_001",
            start_char=0
        )

        assert len(events) == 2
        assert events[0]["category"] == "Decision"
        assert events[1]["category"] == "Commitment"


def test_extract_from_chunk_handles_json_parse_error(sample_chunk_text):
    """Test that extract_from_chunk handles JSON parse errors gracefully."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Invalid JSON{"))
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        events = service.extract_from_chunk(
            chunk_text=sample_chunk_text,
            chunk_index=0,
            chunk_id="chunk_001",
            start_char=0
        )

        assert events == []


def test_extract_from_chunk_handles_missing_events_key(sample_chunk_text):
    """Test that extract_from_chunk handles missing 'events' key."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps({"results": []})))
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        events = service.extract_from_chunk(
            chunk_text=sample_chunk_text,
            chunk_index=0,
            chunk_id="chunk_001",
            start_char=0
        )

        assert events == []


def test_extract_from_chunk_calls_openai_with_correct_params(sample_chunk_text):
    """Test that extract_from_chunk calls OpenAI with correct parameters."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps({"events": []})))
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        service = EventExtractionService(
            api_key="test_key",
            model="gpt-4o-mini",
            temperature=0.0
        )

        service.extract_from_chunk(
            chunk_text=sample_chunk_text,
            chunk_index=0,
            chunk_id="chunk_001",
            start_char=0
        )

        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "gpt-4o-mini"
        assert call_args.kwargs["temperature"] == 0.0
        assert call_args.kwargs["response_format"] == {"type": "json_object"}
        assert len(call_args.kwargs["messages"]) == 2
        assert call_args.kwargs["messages"][0]["role"] == "system"
        assert call_args.kwargs["messages"][1]["role"] == "user"


# ============================================================================
# Canonicalize Events Tests (Prompt B)
# ============================================================================

def test_canonicalize_events_success(sample_extracted_events, sample_canonical_events):
    """Test successful canonicalization of events."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({"events": sample_canonical_events})
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        chunk_events = [sample_extracted_events[:2], sample_extracted_events[2:]]
        canonical = service.canonicalize_events(chunk_events)

        assert len(canonical) == 2
        # Check that second event has merged evidence
        assert len(canonical[1]["evidence"]) == 2


def test_canonicalize_events_with_empty_input():
    """Test that canonicalize_events returns empty list for empty input."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        chunk_events = [[], []]
        canonical = service.canonicalize_events(chunk_events)

        assert canonical == []
        # OpenAI should not be called
        mock_client.chat.completions.create.assert_not_called()


def test_canonicalize_events_handles_json_parse_error(sample_extracted_events):
    """Test that canonicalize_events falls back on JSON parse error."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Invalid JSON{"))
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        chunk_events = [sample_extracted_events]
        canonical = service.canonicalize_events(chunk_events)

        # Should return all events without deduplication
        assert len(canonical) == len(sample_extracted_events)


def test_canonicalize_events_flattens_chunk_events(sample_extracted_events):
    """Test that canonicalize_events flattens events from all chunks."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({"events": sample_extracted_events})
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        # Split events across 3 chunks
        chunk_events = [
            [sample_extracted_events[0]],
            [sample_extracted_events[1]],
            [sample_extracted_events[2]]
        ]

        service.canonicalize_events(chunk_events)

        # Check that all events were sent to OpenAI
        call_args = mock_client.chat.completions.create.call_args
        user_message = call_args.kwargs["messages"][1]["content"]
        assert "3 chunks" in user_message


def test_canonicalize_events_calls_openai_with_correct_params(sample_extracted_events):
    """Test that canonicalize_events calls OpenAI with correct parameters."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps({"events": []})))
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        service = EventExtractionService(
            api_key="test_key",
            model="gpt-4o-mini",
            temperature=0.0
        )

        chunk_events = [sample_extracted_events]
        service.canonicalize_events(chunk_events)

        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "gpt-4o-mini"
        assert call_args.kwargs["temperature"] == 0.0
        assert call_args.kwargs["response_format"] == {"type": "json_object"}


# ============================================================================
# Event Validation Tests
# ============================================================================

def test_validate_event_with_valid_event():
    """Test that validate_event returns True for valid event."""
    service = EventExtractionService(api_key="test_key")

    valid_event = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": [
            {
                "quote": "test quote",
                "start_char": 0,
                "end_char": 10
            }
        ]
    }

    assert service.validate_event(valid_event) is True


def test_validate_event_with_missing_required_field():
    """Test that validate_event returns False for missing required field."""
    service = EventExtractionService(api_key="test_key")

    invalid_event = {
        "category": "Decision",
        "narrative": "Test event",
        # Missing subject
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(invalid_event) is False


def test_validate_event_with_invalid_category():
    """Test that validate_event returns False for invalid category."""
    service = EventExtractionService(api_key="test_key")

    invalid_event = {
        "category": "InvalidCategory",
        "narrative": "Test event",
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(invalid_event) is False


def test_validate_event_with_invalid_confidence():
    """Test that validate_event returns False for invalid confidence."""
    service = EventExtractionService(api_key="test_key")

    # Confidence > 1.0
    invalid_event1 = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 1.5,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(invalid_event1) is False

    # Confidence < 0.0
    invalid_event2 = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": -0.1,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(invalid_event2) is False


def test_validate_event_with_invalid_subject_structure():
    """Test that validate_event returns False for invalid subject."""
    service = EventExtractionService(api_key="test_key")

    # Subject missing 'type'
    invalid_event1 = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": {"ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(invalid_event1) is False

    # Subject is not a dict
    invalid_event2 = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": "test",
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(invalid_event2) is False


def test_validate_event_with_invalid_actors_structure():
    """Test that validate_event returns False for invalid actors."""
    service = EventExtractionService(api_key="test_key")

    # Actors not a list
    invalid_event1 = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": {"type": "project", "ref": "test"},
        "actors": "Alice",
        "confidence": 0.9,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(invalid_event1) is False

    # Actor missing 'ref'
    invalid_event2 = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"role": "owner"}],
        "confidence": 0.9,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(invalid_event2) is False


def test_validate_event_with_invalid_evidence():
    """Test that validate_event returns False for invalid evidence."""
    service = EventExtractionService(api_key="test_key")

    # Empty evidence
    invalid_event1 = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": []
    }

    assert service.validate_event(invalid_event1) is False

    # Evidence missing 'quote'
    invalid_event2 = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": [{"start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(invalid_event2) is False

    # Invalid offsets (end <= start)
    invalid_event3 = {
        "category": "Decision",
        "narrative": "Test event",
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": [{"quote": "test", "start_char": 10, "end_char": 5}]
    }

    assert service.validate_event(invalid_event3) is False


def test_validate_event_with_all_valid_categories():
    """Test that validate_event accepts all valid event categories."""
    service = EventExtractionService(api_key="test_key")

    for category in EVENT_CATEGORIES:
        valid_event = {
            "category": category,
            "narrative": f"Test {category} event",
            "subject": {"type": "project", "ref": "test"},
            "actors": [{"ref": "Alice", "role": "owner"}],
            "confidence": 0.9,
            "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
        }

        assert service.validate_event(valid_event) is True, f"Category {category} should be valid"


def test_validate_event_with_optional_event_time():
    """Test that validate_event accepts events with or without event_time."""
    service = EventExtractionService(api_key="test_key")

    # With event_time
    event_with_time = {
        "category": "Decision",
        "narrative": "Test event",
        "event_time": "2024-03-15T14:30:00Z",
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(event_with_time) is True

    # Without event_time (or None)
    event_without_time = {
        "category": "Decision",
        "narrative": "Test event",
        "event_time": None,
        "subject": {"type": "project", "ref": "test"},
        "actors": [{"ref": "Alice", "role": "owner"}],
        "confidence": 0.9,
        "evidence": [{"quote": "test", "start_char": 0, "end_char": 5}]
    }

    assert service.validate_event(event_without_time) is True


# ============================================================================
# Error Handling Tests
# ============================================================================

def test_extract_from_chunk_raises_on_openai_error(sample_chunk_text):
    """Test that extract_from_chunk raises exception on OpenAI API error."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        with pytest.raises(Exception, match="API error"):
            service.extract_from_chunk(
                chunk_text=sample_chunk_text,
                chunk_index=0,
                chunk_id="chunk_001",
                start_char=0
            )


def test_canonicalize_events_raises_on_openai_error(sample_extracted_events):
    """Test that canonicalize_events raises exception on OpenAI API error."""
    with patch("services.event_extraction_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        mock_openai.return_value = mock_client

        service = EventExtractionService(api_key="test_key")

        with pytest.raises(Exception, match="API error"):
            service.canonicalize_events([sample_extracted_events])
