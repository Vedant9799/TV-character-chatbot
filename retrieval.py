#!/usr/bin/env python3
"""Shared retrieval logic for TV character RAG: ChromaDB query + character filter + topk or MMR.

Used by chatbot_server.py and run_eval.py. No FastAPI/transformers dependency.
Supports hybrid search (BM25 + Chroma + RRF) when strategy="hybrid".
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import chromadb
import numpy as np

# ---------------------------------------------------------------------------
# Character → show mapping (mirrors chatbot_server)
# ---------------------------------------------------------------------------

SHOW_MAP: Dict[str, str] = {
    "Michael": "The Office", "Dwight": "The Office", "Jim": "The Office",
    "Pam": "The Office", "Andy": "The Office", "Ryan": "The Office",
    "Kevin": "The Office", "Angela": "The Office",
    "Sheldon": "The Big Bang Theory", "Leonard": "The Big Bang Theory",
    "Penny": "The Big Bang Theory", "Howard": "The Big Bang Theory",
    "Raj": "The Big Bang Theory", "Bernadette": "The Big Bang Theory",
    "Amy": "The Big Bang Theory",
}

CHROMA_SHOW_KEY: Dict[str, str] = {
    "The Office": "the_office",
    "The Big Bang Theory": "big_bang_theory",
}

CANDIDATE_POOL = 60

# Lazy-built BM25 index per show (chroma_show -> (doc_ids, BM25Okapi))
_BM25_CACHE: Dict[str, Tuple[List[str], Any]] = {}


def _tokenize(text: str) -> List[str]:
    """Simple tokenization for BM25: lowercase, split on whitespace, strip punctuation."""
    if not text:
        return []
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return [w for w in cleaned.split() if w]


def _build_bm25_index(collection: Any, chroma_show: str) -> Tuple[List[str], Any]:
    """Build BM25 index for a show's docs. Cached per show."""
    if chroma_show in _BM25_CACHE:
        return _BM25_CACHE[chroma_show]
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        raise ImportError("rank_bm25 is required for hybrid search. Install with: pip install rank_bm25")

    result = collection.get(
        where={"show": chroma_show},
        include=["documents"],
    )
    doc_ids = result["ids"]
    documents = result["documents"]
    if not doc_ids or not documents:
        _BM25_CACHE[chroma_show] = ([], None)
        return [], None

    tokenized = [_tokenize(doc or "") for doc in documents]
    bm25 = BM25Okapi(tokenized)
    _BM25_CACHE[chroma_show] = (doc_ids, bm25)
    return doc_ids, bm25


def _rrf_merge(
    chroma_ranked_ids: List[str],
    bm25_ranked_ids: List[str],
    k: int = 60,
) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion: merge two ranked lists. Returns (doc_id, rrf_score) sorted by score desc."""
    scores: Dict[str, float] = {}
    for rank, doc_id in enumerate(chroma_ranked_ids, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    for rank, doc_id in enumerate(bm25_ranked_ids, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    sorted_items = sorted(scores.items(), key=lambda x: -x[1])
    return sorted_items


def _cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr))
    return float(np.dot(a_arr, b_arr) / denom) if denom > 0 else 0.0


def _mmr_select_indices(
    distances: List[float],
    embeddings: List[List[float]],
    n_select: int,
    lambda_mult: float = 0.6,
) -> List[int]:
    """Maximal Marginal Relevance: return indices of selected items (relevance + diversity)."""
    n = len(distances)
    if n <= n_select:
        return list(range(n))

    max_d = max(distances) or 1.0
    norm_dists = [d / max_d for d in distances]

    selected: List[int] = [0]
    remaining: List[int] = list(range(1, n))

    while len(selected) < n_select and remaining:
        scores = []
        for idx in remaining:
            relevance = 1.0 - norm_dists[idx]
            redundancy = max(_cosine_sim(embeddings[idx], embeddings[s]) for s in selected)
            scores.append((lambda_mult * relevance - (1 - lambda_mult) * redundancy, idx))
        best = max(scores, key=lambda x: x[0])[1]
        selected.append(best)
        remaining.remove(best)

    return selected


def build_retrieval_query(current_message: str, history: List[Dict[str, Any]]) -> str:
    """Build a retrieval query that includes recent conversation context."""
    if not history:
        return current_message
    recent = history[-6:]
    parts = []
    for msg in recent:
        role = msg.get("role", "")
        content = msg.get("content", "").strip()
        if not content:
            continue
        if role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
    if parts:
        return " ".join(parts) + " " + current_message
    return current_message


def retrieve(
    collection: Any,
    character: str,
    query: str,
    history: List[Dict[str, Any]],
    n_results: int = 4,
    strategy: str = "mmr",
    return_funnel_counts: bool = False,
    debug: bool = False,
) -> Union[List[Tuple[str, str]], Tuple[List[Tuple[str, str]], Dict[str, int]]]:
    """Retrieve scene examples for a character and query.

    Args:
        collection: ChromaDB collection (with embedding function if used at build time).
        character: Character name (e.g. Sheldon, Michael).
        query: User message / query text.
        history: Conversation history (list of {"role": "user"|"assistant", "content": "..."}).
        n_results: Number of scenes to return.
        strategy: "topk" (relevance only), "mmr" (relevance + diversity), or "hybrid" (BM25 + Chroma + RRF).
        return_funnel_counts: If True, return (results, funnel_counts_dict) for inspection.

    Returns:
        List of (doc_id, text) tuples in retrieval order; or if return_funnel_counts,
        (list, dict) with dict keys: n_chroma_results, n_after_character_filter, n_after_dedup, n_final.
    """
    query_with_context = build_retrieval_query(query, history)
    show = SHOW_MAP.get(character, "")
    chroma_show = CHROMA_SHOW_KEY.get(show, "")

    where = {"show": chroma_show} if chroma_show else None
    include_fields = ["documents", "metadatas", "distances"]
    if strategy in ("mmr", "hybrid"):
        include_fields.append("embeddings")
    kwargs: dict = dict(
        query_texts=[query_with_context],
        n_results=CANDIDATE_POOL,
        include=include_fields,
    )
    if where:
        kwargs["where"] = where
    # Topic-specific keyword filter: when query clearly targets a topic, restrict to docs containing it
    # (e.g. "downsizing" -> surfaces pilot "downsizing is a bitch" scene over semantic-only)
    _topic_keywords = [
        "downsizing", "bazinga", "dundie", "dundies", "scranton", "couch", "spot",
        "that's what she said", "thats what she said", "bears", "beets", "battlestar galactica",
    ]
    q_lower = query_with_context.lower()
    topic_keyword_used: Optional[str] = None
    for kw in _topic_keywords:
        if kw in q_lower:
            kwargs["where_document"] = {"$contains": kw}
            topic_keyword_used = kw
            break

    try:
        results = collection.query(**kwargs)
    except Exception as exc:
        print(f"[retrieval] ChromaDB query error: {exc}")
        if return_funnel_counts:
            return [], {"n_chroma_results": 0, "n_after_character_filter": 0, "n_after_dedup": 0, "n_final": 0}
        return []

    raw_ids = results["ids"][0]
    raw_docs = results["documents"][0]
    raw_metas = results["metadatas"][0]
    raw_distances = results["distances"][0]
    raw_embeddings = results["embeddings"][0] if "embeddings" in results else [[]] * len(raw_ids)

    # Hybrid: merge Chroma + BM25 via RRF, then fetch fused docs from Chroma
    if strategy == "hybrid" and chroma_show:
        chroma_ranked_ids = list(raw_ids)
        doc_ids_list, bm25 = _build_bm25_index(collection, chroma_show)
        if bm25 is not None and doc_ids_list:
            query_tokens = _tokenize(query_with_context)
            bm25_scores = bm25.get_scores(query_tokens)
            bm25_ranked = sorted(
                zip(doc_ids_list, bm25_scores),
                key=lambda x: -x[1],
            )
            bm25_ranked_ids = [did for did, _ in bm25_ranked[:CANDIDATE_POOL]]
            rrf_pairs = _rrf_merge(chroma_ranked_ids, bm25_ranked_ids)
            fused_ids = [pid for pid, _ in rrf_pairs[:CANDIDATE_POOL]]
            if fused_ids:
                fetched = collection.get(
                    ids=fused_ids,
                    include=["documents", "metadatas", "embeddings"],
                )
                id_to_doc = dict(zip(fetched["ids"], fetched["documents"]))
                id_to_meta = dict(zip(fetched["ids"], fetched["metadatas"]))
                id_to_emb = dict(zip(fetched["ids"], fetched["embeddings"]))
                rrf_scores = dict(rrf_pairs)
                max_rrf = max(rrf_scores.values()) or 1.0
                raw_ids = []
                raw_docs = []
                raw_metas = []
                raw_distances = []
                raw_embeddings = []
                for fid in fused_ids:
                    if fid in id_to_doc:
                        raw_ids.append(fid)
                        raw_docs.append(id_to_doc[fid])
                        raw_metas.append(id_to_meta.get(fid, {}))
                        raw_embeddings.append(id_to_emb.get(fid, []))
                        # Distance proxy: lower = better (1 - normalized RRF)
                        raw_distances.append(1.0 - (rrf_scores.get(fid, 0) / max_rrf))

    n_chroma_results = len(raw_ids)

    # Character filter + dedup by (season, episode, scene); prefer scenes where character speaks more
    seen: set = set()
    ids, docs, dists, embs = [], [], [], []
    n_after_character_filter = 0
    _stop = {"that", "this", "what", "with", "when", "have", "about", "from", "them", "they", "would", "could", "should", "think", "your", "tell"}
    query_words = [w.lower() for w in query_with_context.split() if len(w) >= 4 and w.lower() not in _stop]
    debug_info_by_id: Dict[str, Dict[str, Any]] = {}
    for doc_id, doc, meta, dist, emb in zip(
        raw_ids, raw_docs, raw_metas, raw_distances, raw_embeddings
    ):
        chars = json.loads(meta.get("characters_present", "[]"))
        if character and character not in chars:
            continue
        n_after_character_filter += 1
        key = (meta.get("season"), meta.get("episode"), meta.get("scene"))
        if key in seen:
            continue
        seen.add(key)
        # Boost relevance for scenes where this character has more lines (better voice examples).
        # character_line_fraction is populated by build_chromadb.py at ingestion time.
        line_frac = json.loads(meta.get("character_line_fraction", "{}"))
        frac = float(line_frac.get(character, 0.5))
        adjusted_dist = dist * (1.0 - 0.25 * frac)  # higher frac => lower dist => ranked higher
        keyword_boost = False
        doc_lower = (doc or "").lower()
        if any(w in doc_lower for w in query_words):
            adjusted_dist *= 0.65  # 35% boost for keyword match (surfaces topic-specific scenes)
            keyword_boost = True
        ids.append(doc_id)
        docs.append(doc)
        dists.append(adjusted_dist)
        embs.append(emb)
        debug_info_by_id[doc_id] = {
                "raw_dist": dist,
                "line_frac": frac,
                "keyword_boost": keyword_boost,
                "adjusted_dist": adjusted_dist,
                "preview": (doc or "")[:120] + "..." if len(doc or "") > 120 else (doc or ""),
            }

    n_after_dedup = len(ids)

    # Sort by adjusted distance (ascending) so best candidates are first for MMR
    sorted_pairs = sorted(zip(dists, ids, docs, embs), key=lambda x: x[0])
    dists, ids, docs, embs = (
        [x[0] for x in sorted_pairs],
        [x[1] for x in sorted_pairs],
        [x[2] for x in sorted_pairs],
        [x[3] for x in sorted_pairs],
    )

    if not docs:
        if return_funnel_counts:
            return [], {
                "n_chroma_results": n_chroma_results,
                "n_after_character_filter": n_after_character_filter,
                "n_after_dedup": 0,
                "n_final": 0,
            }
        return []

    if strategy == "topk":
        # Ascending distance = most relevant first; take first n_results
        selected_indices = list(range(min(n_results, len(docs))))
    else:
        # strategy == "mmr"
        selected_indices = _mmr_select_indices(dists, embs, n_select=n_results)

    result_list = [(ids[i], docs[i]) for i in selected_indices]
    n_final = len(result_list)

    # Debug logging: input, output, scoring, candidates (for agentic feedback loop)
    if debug or (os.environ.get("RETRIEVAL_DEBUG", "").lower() in ("1", "true", "yes")):
        try:
            from retrieval_logger import is_debug_enabled, log_retrieval
            if debug or is_debug_enabled():
                selected_ids = {ids[i] for i in selected_indices}
                force_log = debug and not is_debug_enabled()
                candidates = []
                for rank, doc_id in enumerate(ids, 1):
                    info = debug_info_by_id.get(doc_id, {})
                    candidates.append({
                        "rank": rank,
                        "doc_id": doc_id,
                        "selected": doc_id in selected_ids,
                        **info,
                    })
                log_retrieval({
                    "input": {
                        "query": query,
                        "query_with_context": query_with_context[:200] + "..." if len(query_with_context) > 200 else query_with_context,
                        "character": character,
                        "strategy": strategy,
                        "n_results": n_results,
                        "topic_keyword": topic_keyword_used,
                    },
                    "funnel": {
                        "n_chroma_results": n_chroma_results,
                        "n_after_character_filter": n_after_character_filter,
                        "n_after_dedup": n_after_dedup,
                        "n_final": n_final,
                    },
                    "output": {"doc_ids": [r[0] for r in result_list]},
                    "candidates": candidates,
                    "selected_previews": [debug_info_by_id.get(r[0], {}).get("preview", "") for r in result_list],
                }, force=force_log)
        except ImportError as e:
            if debug:
                print(f"[retrieval] Debug logging skipped (import failed): {e}")

    if return_funnel_counts:
        return result_list, {
            "n_chroma_results": n_chroma_results,
            "n_after_character_filter": n_after_character_filter,
            "n_after_dedup": n_after_dedup,
            "n_final": n_final,
        }
    return result_list
