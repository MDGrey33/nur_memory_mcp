"""
Unit tests for V7 benchmark metrics.

These tests verify the metric calculations are correct and deterministic.
"""

import pytest
import sys
from pathlib import Path

# Add metrics to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'metrics'))

from extraction_metrics import (
    evaluate_extraction,
    evaluate_entity_extraction,
    aggregate_results,
    text_similarity,
    normalize_text,
    category_matches
)

from retrieval_metrics import (
    evaluate_retrieval,
    aggregate_retrieval_results,
    evaluate_graph_expansion,
    calculate_dcg,
    calculate_ndcg,
    calculate_mrr
)


class TestTextSimilarity:
    """Tests for text normalization and similarity."""

    def test_normalize_text_lowercase(self):
        assert normalize_text("HELLO World") == "hello world"

    def test_normalize_text_whitespace(self):
        assert normalize_text("hello   world") == "hello world"

    def test_normalize_text_punctuation(self):
        assert normalize_text("hello, world!") == "hello world"

    def test_similarity_identical(self):
        assert text_similarity("hello world", "hello world") == 1.0

    def test_similarity_case_insensitive(self):
        assert text_similarity("Hello World", "hello world") == 1.0

    def test_similarity_partial(self):
        sim = text_similarity("Alice decided to launch", "Alice decided we will launch")
        assert 0.7 < sim < 1.0

    def test_similarity_different(self):
        sim = text_similarity("completely different text", "nothing alike here")
        assert sim < 0.5


class TestCategoryMatching:
    """Tests for event category matching."""

    def test_exact_match(self):
        assert category_matches("Decision", "Decision") is True

    def test_case_insensitive(self):
        assert category_matches("decision", "DECISION") is True

    def test_alias_commitment(self):
        assert category_matches("Commitment", "action_item") is True

    def test_alias_risk(self):
        assert category_matches("QualityRisk", "Risk") is True

    def test_no_match(self):
        assert category_matches("Decision", "Commitment") is False


class TestExtractionMetrics:
    """Tests for extraction metric calculations."""

    def test_perfect_extraction(self):
        predicted = [
            {'category': 'Decision', 'narrative': 'Alice decided to launch on April 1st'},
            {'category': 'Commitment', 'narrative': 'Bob will complete API by March 25th'}
        ]
        ground_truth = [
            {'category': 'Decision', 'narrative': 'Alice decided to launch on April 1st'},
            {'category': 'Commitment', 'narrative': 'Bob will complete API by March 25th'}
        ]

        result = evaluate_extraction(predicted, ground_truth)
        assert result.precision == 1.0
        assert result.recall == 1.0
        assert result.f1 == 1.0

    def test_partial_match(self):
        predicted = [
            {'category': 'Decision', 'narrative': 'Alice decided on April 1st launch'},
        ]
        ground_truth = [
            {'category': 'Decision', 'narrative': 'Alice decided to launch on April 1st'},
            {'category': 'Commitment', 'narrative': 'Bob will complete API'}
        ]

        result = evaluate_extraction(predicted, ground_truth)
        assert result.true_positives == 1
        assert result.false_positives == 0
        assert result.false_negatives == 1
        assert result.precision == 1.0
        assert result.recall == 0.5

    def test_false_positives(self):
        predicted = [
            {'category': 'Decision', 'narrative': 'Something that was not in ground truth'},
            {'category': 'Decision', 'narrative': 'Alice decided to launch'}
        ]
        ground_truth = [
            {'category': 'Decision', 'narrative': 'Alice decided to launch on April 1st'}
        ]

        result = evaluate_extraction(predicted, ground_truth)
        assert result.true_positives == 1
        assert result.false_positives == 1
        assert result.false_negatives == 0

    def test_empty_predictions(self):
        result = evaluate_extraction([], [{'category': 'Decision', 'narrative': 'test'}])
        assert result.precision == 0.0
        assert result.recall == 0.0
        assert result.f1 == 0.0

    def test_empty_ground_truth(self):
        result = evaluate_extraction([{'category': 'Decision', 'narrative': 'test'}], [])
        assert result.precision == 0.0
        assert result.recall == 0.0

    def test_category_mismatch_no_match(self):
        predicted = [{'category': 'Decision', 'narrative': 'Something happened'}]
        ground_truth = [{'category': 'Commitment', 'narrative': 'Something happened'}]

        result = evaluate_extraction(predicted, ground_truth, require_category_match=True)
        assert result.true_positives == 0


class TestEntityExtraction:
    """Tests for entity extraction metrics."""

    def test_perfect_entity_match(self):
        predicted = [{'name': 'Alice Chen', 'role': 'PM'}]
        ground_truth = [{'name': 'Alice Chen', 'role': 'Product Manager'}]

        result = evaluate_entity_extraction(predicted, ground_truth)
        assert result.precision == 1.0
        assert result.recall == 1.0

    def test_alias_matching(self):
        predicted = [{'name': 'alice.chen@company.com'}]
        ground_truth = [{'name': 'Alice Chen', 'aliases': ['alice.chen@company.com']}]

        result = evaluate_entity_extraction(predicted, ground_truth)
        assert result.true_positives == 1


class TestRetrievalMetrics:
    """Tests for retrieval metric calculations."""

    def test_perfect_retrieval(self):
        retrieved = ['doc1', 'doc2', 'doc3']
        relevance = {'doc1': 3, 'doc2': 2, 'doc3': 1}

        result = evaluate_retrieval(retrieved, relevance)
        assert result.mrr == 1.0
        assert result.ndcg == 1.0
        assert result.precision_at_3 == 1.0

    def test_mrr_first_position(self):
        retrieved = ['doc1', 'doc2', 'doc3']
        relevance = {'doc1': 1}

        result = evaluate_retrieval(retrieved, relevance)
        assert result.mrr == 1.0
        assert result.first_relevant_rank == 1

    def test_mrr_second_position(self):
        retrieved = ['doc1', 'doc2', 'doc3']
        relevance = {'doc2': 1}

        result = evaluate_retrieval(retrieved, relevance)
        assert result.mrr == 0.5
        assert result.first_relevant_rank == 2

    def test_mrr_third_position(self):
        retrieved = ['doc1', 'doc2', 'doc3']
        relevance = {'doc3': 1}

        result = evaluate_retrieval(retrieved, relevance)
        assert abs(result.mrr - 1/3) < 0.01
        assert result.first_relevant_rank == 3

    def test_no_relevant_docs(self):
        retrieved = ['doc1', 'doc2']
        relevance = {'doc3': 1}  # Not in retrieved

        result = evaluate_retrieval(retrieved, relevance)
        assert result.mrr == 0.0
        assert result.first_relevant_rank is None

    def test_ndcg_calculation(self):
        # Perfect ordering: high relevance first
        retrieved_perfect = ['doc1', 'doc2', 'doc3']
        relevance = {'doc1': 3, 'doc2': 2, 'doc3': 1}

        ndcg_perfect = calculate_ndcg(retrieved_perfect, relevance)
        assert ndcg_perfect == 1.0

        # Suboptimal ordering
        retrieved_suboptimal = ['doc3', 'doc2', 'doc1']
        ndcg_suboptimal = calculate_ndcg(retrieved_suboptimal, relevance)
        assert ndcg_suboptimal < 1.0

    def test_precision_at_k(self):
        retrieved = ['doc1', 'doc2', 'doc3', 'doc4', 'doc5']
        relevance = {'doc1': 1, 'doc3': 1}  # Only 2 relevant

        result = evaluate_retrieval(retrieved, relevance)
        assert result.precision_at_1 == 1.0  # doc1 is relevant
        assert abs(result.precision_at_3 - 2/3) < 0.01  # 2 of 3 relevant

    def test_recall_at_k(self):
        retrieved = ['doc1', 'doc2', 'doc3']
        relevance = {'doc1': 1, 'doc4': 1, 'doc5': 1}  # 3 relevant total

        result = evaluate_retrieval(retrieved, relevance)
        assert abs(result.recall_at_5 - 1/3) < 0.01  # Found 1 of 3


class TestDCG:
    """Tests for DCG calculation."""

    def test_dcg_single_item(self):
        dcg = calculate_dcg([3])
        # DCG = 3 / log2(2) = 3
        assert dcg == 3.0

    def test_dcg_multiple_items(self):
        dcg = calculate_dcg([3, 2, 1])
        # DCG = 3/log2(2) + 2/log2(3) + 1/log2(4)
        # DCG = 3/1 + 2/1.585 + 1/2 = 3 + 1.262 + 0.5 = 4.762
        assert abs(dcg - 4.762) < 0.01

    def test_dcg_with_k(self):
        dcg = calculate_dcg([3, 2, 1, 1, 1], k=3)
        dcg_full = calculate_dcg([3, 2, 1])
        assert dcg == dcg_full


class TestGraphExpansion:
    """Tests for graph expansion metrics."""

    def test_perfect_expansion(self):
        retrieved = {'Alice', 'Bob', 'Carol'}
        expected = {'Alice', 'Bob', 'Carol'}

        result = evaluate_graph_expansion(retrieved, expected)
        assert result['precision'] == 1.0
        assert result['recall'] == 1.0
        assert result['f1'] == 1.0

    def test_partial_expansion(self):
        retrieved = {'Alice', 'Bob'}
        expected = {'Alice', 'Bob', 'Carol'}

        result = evaluate_graph_expansion(retrieved, expected)
        assert result['precision'] == 1.0  # All retrieved are correct
        assert abs(result['recall'] - 2/3) < 0.01  # Found 2 of 3

    def test_extra_entities(self):
        retrieved = {'Alice', 'Bob', 'David'}
        expected = {'Alice', 'Bob'}

        result = evaluate_graph_expansion(retrieved, expected)
        assert abs(result['precision'] - 2/3) < 0.01  # 2 of 3 correct
        assert result['recall'] == 1.0  # Found all expected

    def test_min_connections(self):
        retrieved = {'Alice'}
        expected = {'Alice', 'Bob', 'Carol'}

        result = evaluate_graph_expansion(retrieved, expected, min_connections=2)
        assert result['meets_minimum'] is False

        result2 = evaluate_graph_expansion(retrieved, expected, min_connections=1)
        assert result2['meets_minimum'] is True


class TestAggregation:
    """Tests for result aggregation."""

    def test_aggregate_extraction(self):
        from extraction_metrics import ExtractionResult

        results = [
            ExtractionResult(0.8, 0.6, 0.69, 3, 1, 2, [], [], []),
            ExtractionResult(1.0, 0.8, 0.89, 4, 0, 1, [], [], [])
        ]

        agg = aggregate_results(results)
        assert agg['num_documents'] == 2
        assert 0.7 < agg['precision'] < 0.95
        assert 0.6 < agg['recall'] < 0.8

    def test_aggregate_retrieval(self):
        from retrieval_metrics import RetrievalResult

        results = [
            RetrievalResult(1.0, 0.9, 0.85, 0.8, 1.0, 0.8, 0.7, 0.6, 0.7, 1, 5, 3, 3),
            RetrievalResult(0.5, 0.7, 0.65, 0.6, 0.5, 0.6, 0.5, 0.4, 0.5, 2, 5, 3, 2)
        ]

        agg = aggregate_retrieval_results(results)
        assert agg['num_queries'] == 2
        assert agg['mrr'] == 0.75
        assert agg['ndcg'] == 0.8


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
