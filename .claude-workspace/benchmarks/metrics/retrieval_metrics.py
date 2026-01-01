"""
Retrieval Metrics for V7 Quality Benchmarks

Measures how well the system retrieves relevant documents for queries.
Implements standard IR metrics: MRR, NDCG, Precision@K, Recall@K.
"""

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class RetrievalResult:
    """Results from retrieval metric evaluation."""
    mrr: float                    # Mean Reciprocal Rank
    ndcg: float                   # Normalized Discounted Cumulative Gain
    ndcg_at_3: float              # NDCG@3
    ndcg_at_5: float              # NDCG@5
    precision_at_1: float         # Precision@1
    precision_at_3: float         # Precision@3
    precision_at_5: float         # Precision@5
    recall_at_5: float            # Recall@5
    recall_at_10: float           # Recall@10
    first_relevant_rank: Optional[int]  # Rank of first relevant doc (1-indexed)
    num_retrieved: int
    num_relevant: int
    relevant_retrieved: int       # Number of relevant docs in results


def calculate_dcg(relevance_scores: list[float], k: Optional[int] = None) -> float:
    """
    Calculate Discounted Cumulative Gain.

    DCG = sum(rel_i / log2(i + 1)) for i in 1..k
    """
    if k is not None:
        relevance_scores = relevance_scores[:k]

    dcg = 0.0
    for i, rel in enumerate(relevance_scores, start=1):
        dcg += rel / math.log2(i + 1)

    return dcg


def calculate_idcg(relevance_judgments: dict[str, int], k: Optional[int] = None) -> float:
    """
    Calculate Ideal DCG (perfect ranking).

    IDCG is DCG with documents sorted by relevance (highest first).
    """
    sorted_rels = sorted(relevance_judgments.values(), reverse=True)
    return calculate_dcg(sorted_rels, k)


def calculate_ndcg(
    retrieved_docs: list[str],
    relevance_judgments: dict[str, int],
    k: Optional[int] = None
) -> float:
    """
    Calculate Normalized Discounted Cumulative Gain.

    NDCG = DCG / IDCG
    """
    # Get relevance scores for retrieved documents
    if k is not None:
        retrieved_docs = retrieved_docs[:k]

    relevance_scores = [
        relevance_judgments.get(doc, 0) for doc in retrieved_docs
    ]

    dcg = calculate_dcg(relevance_scores)
    idcg = calculate_idcg(relevance_judgments, k)

    if idcg == 0:
        return 0.0

    return dcg / idcg


def calculate_mrr(
    retrieved_docs: list[str],
    relevant_docs: set[str]
) -> tuple[float, Optional[int]]:
    """
    Calculate Mean Reciprocal Rank.

    MRR = 1 / rank_of_first_relevant_doc
    Returns (mrr, first_relevant_rank)
    """
    for i, doc in enumerate(retrieved_docs, start=1):
        if doc in relevant_docs:
            return 1.0 / i, i

    return 0.0, None


def calculate_precision_at_k(
    retrieved_docs: list[str],
    relevant_docs: set[str],
    k: int
) -> float:
    """
    Calculate Precision@K.

    P@K = |relevant ∩ retrieved[:k]| / k
    """
    retrieved_at_k = set(retrieved_docs[:k])
    relevant_retrieved = len(retrieved_at_k & relevant_docs)
    return relevant_retrieved / k if k > 0 else 0.0


def calculate_recall_at_k(
    retrieved_docs: list[str],
    relevant_docs: set[str],
    k: int
) -> float:
    """
    Calculate Recall@K.

    R@K = |relevant ∩ retrieved[:k]| / |relevant|
    """
    if not relevant_docs:
        return 0.0

    retrieved_at_k = set(retrieved_docs[:k])
    relevant_retrieved = len(retrieved_at_k & relevant_docs)
    return relevant_retrieved / len(relevant_docs)


def evaluate_retrieval(
    retrieved_docs: list[str],
    relevance_judgments: dict[str, int]
) -> RetrievalResult:
    """
    Evaluate retrieval quality for a single query.

    Args:
        retrieved_docs: List of document IDs in ranked order
        relevance_judgments: Dict of {doc_id: relevance_score}
            where relevance_score > 0 means relevant
            and higher scores mean more relevant

    Returns:
        RetrievalResult with all computed metrics
    """
    # Get set of relevant documents (any with score > 0)
    relevant_docs = {doc for doc, score in relevance_judgments.items() if score > 0}

    # Calculate MRR
    mrr, first_rank = calculate_mrr(retrieved_docs, relevant_docs)

    # Calculate NDCG variants
    ndcg = calculate_ndcg(retrieved_docs, relevance_judgments)
    ndcg_at_3 = calculate_ndcg(retrieved_docs, relevance_judgments, k=3)
    ndcg_at_5 = calculate_ndcg(retrieved_docs, relevance_judgments, k=5)

    # Calculate Precision@K
    p_at_1 = calculate_precision_at_k(retrieved_docs, relevant_docs, k=1)
    p_at_3 = calculate_precision_at_k(retrieved_docs, relevant_docs, k=3)
    p_at_5 = calculate_precision_at_k(retrieved_docs, relevant_docs, k=5)

    # Calculate Recall@K
    r_at_5 = calculate_recall_at_k(retrieved_docs, relevant_docs, k=5)
    r_at_10 = calculate_recall_at_k(retrieved_docs, relevant_docs, k=10)

    # Count relevant docs in results
    retrieved_set = set(retrieved_docs)
    relevant_retrieved = len(retrieved_set & relevant_docs)

    return RetrievalResult(
        mrr=mrr,
        ndcg=ndcg,
        ndcg_at_3=ndcg_at_3,
        ndcg_at_5=ndcg_at_5,
        precision_at_1=p_at_1,
        precision_at_3=p_at_3,
        precision_at_5=p_at_5,
        recall_at_5=r_at_5,
        recall_at_10=r_at_10,
        first_relevant_rank=first_rank,
        num_retrieved=len(retrieved_docs),
        num_relevant=len(relevant_docs),
        relevant_retrieved=relevant_retrieved
    )


def aggregate_retrieval_results(results: list[RetrievalResult]) -> dict:
    """Aggregate multiple retrieval results into summary statistics."""
    if not results:
        return {
            'mrr': 0.0,
            'ndcg': 0.0,
            'ndcg_at_3': 0.0,
            'ndcg_at_5': 0.0,
            'precision_at_1': 0.0,
            'precision_at_3': 0.0,
            'precision_at_5': 0.0,
            'recall_at_5': 0.0,
            'recall_at_10': 0.0,
            'num_queries': 0
        }

    n = len(results)

    return {
        'mrr': sum(r.mrr for r in results) / n,
        'ndcg': sum(r.ndcg for r in results) / n,
        'ndcg_at_3': sum(r.ndcg_at_3 for r in results) / n,
        'ndcg_at_5': sum(r.ndcg_at_5 for r in results) / n,
        'precision_at_1': sum(r.precision_at_1 for r in results) / n,
        'precision_at_3': sum(r.precision_at_3 for r in results) / n,
        'precision_at_5': sum(r.precision_at_5 for r in results) / n,
        'recall_at_5': sum(r.recall_at_5 for r in results) / n,
        'recall_at_10': sum(r.recall_at_10 for r in results) / n,
        'num_queries': n,
        'queries_with_relevant_result': sum(1 for r in results if r.first_relevant_rank is not None)
    }


def evaluate_graph_expansion(
    retrieved_entities: set[str],
    expected_entities: set[str],
    min_connections: int = 1
) -> dict:
    """
    Evaluate graph expansion quality.

    Args:
        retrieved_entities: Entities found through graph expansion
        expected_entities: Ground truth connected entities
        min_connections: Minimum expected connections

    Returns:
        Dict with precision, recall, and connectivity metrics
    """
    if not expected_entities:
        return {
            'precision': 1.0 if not retrieved_entities else 0.0,
            'recall': 1.0,
            'f1': 1.0 if not retrieved_entities else 0.0,
            'found_connections': len(retrieved_entities),
            'expected_connections': 0,
            'meets_minimum': True
        }

    intersection = retrieved_entities & expected_entities
    precision = len(intersection) / len(retrieved_entities) if retrieved_entities else 0.0
    recall = len(intersection) / len(expected_entities)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'found_connections': len(retrieved_entities),
        'expected_connections': len(expected_entities),
        'meets_minimum': len(intersection) >= min_connections
    }


if __name__ == '__main__':
    # Example usage
    retrieved = [
        'meetings/meeting_001.txt',
        'emails/email_001.txt',
        'meetings/meeting_005.txt',
        'conversations/conversation_001.txt',
        'decisions/decision_002.txt'
    ]

    relevance = {
        'meetings/meeting_001.txt': 3,  # Highly relevant
        'meetings/meeting_005.txt': 2,  # Relevant
        'emails/email_001.txt': 2,      # Relevant
        'decisions/decision_002.txt': 1  # Somewhat relevant
        # Note: conversation_001 not in judgments = irrelevant
    }

    result = evaluate_retrieval(retrieved, relevance)

    print(f"MRR: {result.mrr:.3f}")
    print(f"NDCG: {result.ndcg:.3f}")
    print(f"NDCG@3: {result.ndcg_at_3:.3f}")
    print(f"NDCG@5: {result.ndcg_at_5:.3f}")
    print(f"P@1: {result.precision_at_1:.3f}")
    print(f"P@3: {result.precision_at_3:.3f}")
    print(f"R@5: {result.recall_at_5:.3f}")
    print(f"First relevant at rank: {result.first_relevant_rank}")
