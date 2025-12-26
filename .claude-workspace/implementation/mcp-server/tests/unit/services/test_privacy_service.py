"""Unit tests for PrivacyFilterService."""

import pytest
from services.privacy_service import PrivacyFilterService


def test_filter_results_allows_all(privacy_service):
    """Test filter_results allows all results in v2."""
    results = ["result1", "result2", "result3"]
    user_context = {"user_id": "test_user"}

    filtered = privacy_service.filter_results(results, user_context)

    assert filtered == results
    assert len(filtered) == 3


def test_filter_results_empty_list(privacy_service):
    """Test filter_results with empty list."""
    filtered = privacy_service.filter_results([], {})
    assert filtered == []


def test_can_access_artifact_allows_all(privacy_service):
    """Test can_access_artifact always returns True in v2."""
    artifact_metadata = {
        "sensitivity": "highly_sensitive",
        "visibility_scope": "team"
    }
    user_context = {"user_id": "test_user"}

    allowed = privacy_service.can_access_artifact(artifact_metadata, user_context)

    assert allowed is True


def test_can_access_artifact_normal_sensitivity(privacy_service):
    """Test can_access_artifact with normal sensitivity."""
    artifact_metadata = {
        "sensitivity": "normal",
        "visibility_scope": "me"
    }

    allowed = privacy_service.can_access_artifact(artifact_metadata, {})

    assert allowed is True


def test_can_access_artifact_missing_fields(privacy_service):
    """Test can_access_artifact with missing metadata fields."""
    # Should use defaults and still allow
    allowed = privacy_service.can_access_artifact({}, {})
    assert allowed is True
