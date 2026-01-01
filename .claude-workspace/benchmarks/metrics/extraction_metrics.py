"""
Extraction Metrics for V7 Quality Benchmarks

Measures how well the system extracts events and entities from documents.
Uses fuzzy matching to handle LLM output variations while maintaining
deterministic evaluation.
"""

import json
import re
from dataclasses import dataclass
from typing import Optional
from difflib import SequenceMatcher


@dataclass
class ExtractionResult:
    """Results from extraction metric evaluation."""
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int
    matched_pairs: list  # [(predicted, ground_truth, similarity)]
    unmatched_predicted: list
    unmatched_ground_truth: list


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    # Lowercase
    text = text.lower()
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove punctuation except essential ones
    text = re.sub(r'[^\w\s\-@.]', '', text)
    return text


def text_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two text strings."""
    norm1 = normalize_text(text1)
    norm2 = normalize_text(text2)
    return SequenceMatcher(None, norm1, norm2).ratio()


def category_matches(pred_category: str, truth_category: str) -> bool:
    """Check if event categories match (with aliases)."""
    # Normalize categories
    pred = pred_category.lower().strip()
    truth = truth_category.lower().strip()

    # Direct match
    if pred == truth:
        return True

    # Common aliases
    aliases = {
        'commitment': ['commitment', 'action_item', 'action', 'task'],
        'decision': ['decision', 'decided', 'agreed'],
        'qualityrisk': ['qualityrisk', 'risk', 'concern', 'issue'],
        'execution': ['execution', 'update', 'status', 'progress'],
        'feedback': ['feedback', 'request', 'suggestion'],
        'change': ['change', 'modification', 'update'],
        'stakeholder': ['stakeholder', 'partner', 'external'],
        'collaboration': ['collaboration', 'coordination']
    }

    for canonical, variants in aliases.items():
        if pred in variants and truth in variants:
            return True

    return False


def match_event(
    predicted: dict,
    ground_truth: dict,
    narrative_threshold: float = 0.6,
    require_category_match: bool = True
) -> tuple[bool, float]:
    """
    Match a predicted event against ground truth.

    Returns (is_match, similarity_score)
    """
    # Check category match if required
    if require_category_match:
        pred_cat = predicted.get('category', '')
        truth_cat = ground_truth.get('category', '')
        if not category_matches(pred_cat, truth_cat):
            return False, 0.0

    # Compare narratives
    pred_narrative = predicted.get('narrative', '')
    truth_narrative = ground_truth.get('narrative', '')

    similarity = text_similarity(pred_narrative, truth_narrative)

    # Boost similarity if actors match
    pred_actor = predicted.get('actor', '')
    truth_actor = ground_truth.get('actor', '')
    if pred_actor and truth_actor:
        actor_sim = text_similarity(str(pred_actor), str(truth_actor))
        if actor_sim > 0.8:
            similarity = min(1.0, similarity + 0.1)

    # Boost if evidence quotes overlap
    pred_evidence = predicted.get('evidence_quote', '')
    truth_evidence = ground_truth.get('evidence_quote', '')
    if pred_evidence and truth_evidence:
        evidence_sim = text_similarity(pred_evidence, truth_evidence)
        if evidence_sim > 0.5:
            similarity = min(1.0, similarity + 0.1)

    is_match = similarity >= narrative_threshold
    return is_match, similarity


def evaluate_extraction(
    predicted_events: list[dict],
    ground_truth_events: list[dict],
    narrative_threshold: float = 0.6,
    require_category_match: bool = True
) -> ExtractionResult:
    """
    Evaluate event extraction quality.

    Uses greedy best-match algorithm to pair predicted events with ground truth.
    """
    # Calculate all pairwise similarities
    similarities = []
    for i, pred in enumerate(predicted_events):
        for j, truth in enumerate(ground_truth_events):
            is_match, sim = match_event(
                pred, truth, narrative_threshold, require_category_match
            )
            if is_match:
                similarities.append((i, j, sim))

    # Sort by similarity (highest first) for greedy matching
    similarities.sort(key=lambda x: x[2], reverse=True)

    # Greedy matching
    matched_pred = set()
    matched_truth = set()
    matched_pairs = []

    for pred_idx, truth_idx, sim in similarities:
        if pred_idx not in matched_pred and truth_idx not in matched_truth:
            matched_pred.add(pred_idx)
            matched_truth.add(truth_idx)
            matched_pairs.append((
                predicted_events[pred_idx],
                ground_truth_events[truth_idx],
                sim
            ))

    # Calculate metrics
    true_positives = len(matched_pairs)
    false_positives = len(predicted_events) - true_positives
    false_negatives = len(ground_truth_events) - true_positives

    precision = true_positives / len(predicted_events) if predicted_events else 0.0
    recall = true_positives / len(ground_truth_events) if ground_truth_events else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Collect unmatched items
    unmatched_predicted = [
        predicted_events[i] for i in range(len(predicted_events))
        if i not in matched_pred
    ]
    unmatched_ground_truth = [
        ground_truth_events[j] for j in range(len(ground_truth_events))
        if j not in matched_truth
    ]

    return ExtractionResult(
        precision=precision,
        recall=recall,
        f1=f1,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        matched_pairs=matched_pairs,
        unmatched_predicted=unmatched_predicted,
        unmatched_ground_truth=unmatched_ground_truth
    )


def evaluate_entity_extraction(
    predicted_entities: list[dict],
    ground_truth_entities: list[dict],
    name_threshold: float = 0.8
) -> ExtractionResult:
    """
    Evaluate entity extraction quality.

    Matches entities by name similarity, considering aliases.
    """
    matched_pairs = []
    matched_pred = set()
    matched_truth = set()

    for i, pred in enumerate(predicted_entities):
        pred_name = pred.get('name', '')
        pred_aliases = pred.get('aliases', [])
        all_pred_names = [pred_name] + pred_aliases

        best_match_idx = -1
        best_similarity = 0.0

        for j, truth in enumerate(ground_truth_entities):
            if j in matched_truth:
                continue

            truth_name = truth.get('name', '')
            truth_aliases = truth.get('aliases', [])
            all_truth_names = [truth_name] + truth_aliases

            # Find best similarity across all name combinations
            for pn in all_pred_names:
                for tn in all_truth_names:
                    sim = text_similarity(str(pn), str(tn))
                    if sim > best_similarity:
                        best_similarity = sim
                        best_match_idx = j

        if best_similarity >= name_threshold and best_match_idx >= 0:
            matched_pred.add(i)
            matched_truth.add(best_match_idx)
            matched_pairs.append((
                pred,
                ground_truth_entities[best_match_idx],
                best_similarity
            ))

    true_positives = len(matched_pairs)
    false_positives = len(predicted_entities) - true_positives
    false_negatives = len(ground_truth_entities) - true_positives

    precision = true_positives / len(predicted_entities) if predicted_entities else 0.0
    recall = true_positives / len(ground_truth_entities) if ground_truth_entities else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    unmatched_predicted = [
        predicted_entities[i] for i in range(len(predicted_entities))
        if i not in matched_pred
    ]
    unmatched_ground_truth = [
        ground_truth_entities[j] for j in range(len(ground_truth_entities))
        if j not in matched_truth
    ]

    return ExtractionResult(
        precision=precision,
        recall=recall,
        f1=f1,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        matched_pairs=matched_pairs,
        unmatched_predicted=unmatched_predicted,
        unmatched_ground_truth=unmatched_ground_truth
    )


def aggregate_results(results: list[ExtractionResult]) -> dict:
    """Aggregate multiple extraction results into summary statistics."""
    if not results:
        return {
            'precision': 0.0,
            'recall': 0.0,
            'f1': 0.0,
            'macro_f1': 0.0,
            'total_tp': 0,
            'total_fp': 0,
            'total_fn': 0
        }

    # Micro-average (aggregate counts then compute)
    total_tp = sum(r.true_positives for r in results)
    total_fp = sum(r.false_positives for r in results)
    total_fn = sum(r.false_negatives for r in results)

    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    micro_f1 = 2 * micro_precision * micro_recall / (micro_precision + micro_recall) \
        if (micro_precision + micro_recall) > 0 else 0.0

    # Macro-average (average of per-document F1)
    macro_f1 = sum(r.f1 for r in results) / len(results)

    return {
        'precision': micro_precision,
        'recall': micro_recall,
        'f1': micro_f1,
        'macro_f1': macro_f1,
        'total_tp': total_tp,
        'total_fp': total_fp,
        'total_fn': total_fn,
        'num_documents': len(results)
    }


if __name__ == '__main__':
    # Example usage
    predicted = [
        {'category': 'Decision', 'narrative': 'Alice decided to launch on April 1st', 'actor': 'Alice Chen'},
        {'category': 'Commitment', 'narrative': 'Bob will complete API by March 25', 'actor': 'Bob Smith'},
        {'category': 'Risk', 'narrative': 'Timeline might slip', 'actor': None}  # Extra false positive
    ]

    ground_truth = [
        {'category': 'Decision', 'narrative': 'Alice decided we will launch on April 1st', 'actor': 'Alice Chen'},
        {'category': 'Commitment', 'narrative': 'Bob committed to complete API refactor by March 25th', 'actor': 'Bob Smith'},
        {'category': 'Decision', 'narrative': 'Team agreed to use freemium model', 'actor': 'Team'}  # Missed
    ]

    result = evaluate_extraction(predicted, ground_truth)
    print(f"Precision: {result.precision:.2f}")
    print(f"Recall: {result.recall:.2f}")
    print(f"F1: {result.f1:.2f}")
    print(f"TP: {result.true_positives}, FP: {result.false_positives}, FN: {result.false_negatives}")
