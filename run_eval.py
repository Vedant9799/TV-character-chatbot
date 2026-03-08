#!/usr/bin/env python3
"""Run retrieval evaluation: compare topk vs MMR on eval_set.json.

Reports recall@1, recall@4, and MRR. Does not load the LLM; only ChromaDB + retrieval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import chromadb

from retrieval import retrieve

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    """1.0 if any of the top-k retrieved ids is in relevant_ids, else 0.0."""
    if not relevant_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    return 1.0 if any(rid in relevant_ids for rid in top_k) else 0.0


def mrr(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    """Mean Reciprocal Rank: 1/rank of first relevant doc, or 0 if none."""
    if not relevant_ids:
        return 0.0
    relevant_set = set(relevant_ids)
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_set:
            return 1.0 / rank
    return 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval: topk vs MMR")
    parser.add_argument("--persist-dir", default="./chroma_db")
    parser.add_argument("--collection", default="tv_scenes")
    parser.add_argument("--eval-set", default="./eval_set.json")
    parser.add_argument("--n-results", type=int, default=4)
    parser.add_argument("--debug", action="store_true", help="Log retrieval traces to retrieval_debug.log")
    args = parser.parse_args()

    eval_path = Path(args.eval_set)
    if not eval_path.exists():
        raise SystemExit(f"Eval set not found: {eval_path}")

    with open(eval_path) as f:
        eval_data = json.load(f)

    print(f"Connecting to ChromaDB at {args.persist_dir}...")
    client = chromadb.PersistentClient(path=args.persist_dir)
    collection = client.get_collection(args.collection)
    print(f"  Collection '{args.collection}': {collection.count()} docs\n")

    strategies = ["topk", "mmr", "hybrid"]
    # Per-strategy metrics: list of per-query values
    results: dict[str, dict[str, list[float]]] = {
        s: {"recall@1": [], "recall@4": [], "mrr": []} for s in strategies
    }

    for item in eval_data:
        query = item["query"]
        character = item["character"]
        relevant_ids = item.get("relevant_ids") or []
        history: list = []

        for strategy in strategies:
            pairs = retrieve(
                collection,
                character,
                query,
                history,
                n_results=args.n_results,
                strategy=strategy,
                debug=args.debug,
            )
            retrieved_ids = [doc_id for doc_id, _ in pairs]

            results[strategy]["recall@1"].append(recall_at_k(retrieved_ids, relevant_ids, 1))
            results[strategy]["recall@4"].append(recall_at_k(retrieved_ids, relevant_ids, args.n_results))
            results[strategy]["mrr"].append(mrr(retrieved_ids, relevant_ids))

    # Aggregate and print
    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    print("--- Retrieval comparison (eval_set.json) ---")
    print(f"  Examples: {len(eval_data)}  |  n_results: {args.n_results}\n")
    print("| Strategy | Recall@1 | Recall@4 | MRR    |")
    print("|----------|----------|----------|--------|")
    for strategy in strategies:
        r1 = mean(results[strategy]["recall@1"])
        r4 = mean(results[strategy]["recall@4"])
        m = mean(results[strategy]["mrr"])
        print(f"| {strategy:8} | {r1:.4f}    | {r4:.4f}    | {m:.4f}  |")
    print()


if __name__ == "__main__":
    main()
