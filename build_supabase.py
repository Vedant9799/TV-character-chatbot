#!/usr/bin/env python3
"""Build the Supabase pgvector store from merged_tv_dialogues.csv.

Run ``supabase_schema.sql`` in the Supabase SQL Editor first, then run this
script to embed and upsert all TV scene documents.

Usage:
    python build_supabase.py --csv merged_tv_dialogues.csv
    python build_supabase.py --csv merged_tv_dialogues.csv --reset
    python build_supabase.py --csv merged_tv_dialogues.csv --batch-size 50

Set in .env (or export to environment):
    SUPABASE_URL=https://<project-ref>.supabase.co
    SUPABASE_SERVICE_KEY=<service-role-key>

The service-role key (not the anon key) is required to bypass row-level
security and write directly to the table.

Embedding model: all-MiniLM-L6-v2 (384-dim, same as ChromaDB default).
This must match the vector(384) column in supabase_schema.sql.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from supabase import Client, create_client

# Re-use the CSV parser and data model from build_chromadb.py — no duplication.
try:
    from build_chromadb import SceneDoc, parse_merged_csv
except ImportError:
    sys.exit(
        "ERROR: build_chromadb.py not found in the current directory.\n"
        "build_supabase.py imports parse_merged_csv from it — both files must"
        " live in the same directory."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────────────────
_DEFAULT_CSV        = "merged_tv_dialogues.csv"
_DEFAULT_BATCH_SIZE = 100
_EMBED_MODEL        = "all-MiniLM-L6-v2"   # 384-dim — must match schema
_TABLE              = "tv_scenes"


# ─────────────────────────────────────────────────────────────────────────────
# Row builder
# ─────────────────────────────────────────────────────────────────────────────

def _doc_to_row(doc: SceneDoc, embedding: List[float]) -> dict:
    """Convert a SceneDoc + its 384-dim embedding into a Supabase row dict."""
    m = doc.metadata
    return {
        "id":                  doc.doc_id,
        "content":             doc.text,
        "embedding":           embedding,            # list[float], len 384
        # Core metadata
        "show":                m.get("show",                ""),
        "doc_type":            m.get("doc_type",            ""),
        "season":              int(m.get("season",          0)),
        "episode":             int(m.get("episode",         0)),
        "scene":               int(m.get("scene",           0)),
        "characters_present":  m.get("characters_present",  "[]"),
        "episode_title":       m.get("episode_title",       ""),
        "turn_idx":            m.get("turn_idx",            None),
        # Character-presence flags — supported characters only
        # Add a new entry here + a column in supabase_schema.sql when adding a character
        "has_sheldon": bool(m.get("has_sheldon", False)),
        "has_michael": bool(m.get("has_michael", False)),
        "has_dwight":  bool(m.get("has_dwight",  False)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main ingest
# ─────────────────────────────────────────────────────────────────────────────

def ingest(
    csv_path:   str,
    sb:         Client,
    model:      SentenceTransformer,
    batch_size: int,
    reset:      bool,
) -> None:
    """Parse CSV, embed, and upsert all docs into Supabase."""

    # ── Optional reset ────────────────────────────────────────────────────────
    if reset:
        print("Truncating tv_scenes table ...")
        # Use a DELETE with a filter that matches all rows (both doc_type values).
        # This avoids the PostgREST schema-cache issue with freshly-created RPC
        # functions.  The service-role key bypasses RLS so this always works.
        sb.table(_TABLE).delete().in_("doc_type", ["canon", "exemplar"]).execute()
        print("  Done.\n")

    # ── Parse CSV ────────────────────────────────────────────────────────────
    print(f"Parsing {csv_path} ...")
    t0   = time.perf_counter()
    docs = parse_merged_csv(csv_path)
    print(f"  {len(docs):,} docs parsed in {time.perf_counter() - t0:.1f}s")

    # ── Count by doc_type for info ────────────────────────────────────────────
    n_canon    = sum(1 for d in docs if d.metadata.get("doc_type") == "canon")
    n_exemplar = sum(1 for d in docs if d.metadata.get("doc_type") == "exemplar")
    print(f"  canon={n_canon:,}  exemplar={n_exemplar:,}")

    # ── Embed + upsert in batches ─────────────────────────────────────────────
    total    = len(docs)
    upserted = 0
    errors   = 0
    t0       = time.perf_counter()

    for batch_start in range(0, total, batch_size):
        batch_docs = docs[batch_start : batch_start + batch_size]
        texts      = [d.text for d in batch_docs]

        # Encode the batch — returns float32 numpy array, shape (batch, 384)
        embeddings = model.encode(
            texts,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,   # unit-normalise for cosine similarity
        )

        rows = [
            _doc_to_row(doc, emb.tolist())
            for doc, emb in zip(batch_docs, embeddings)
        ]

        try:
            sb.table(_TABLE).upsert(rows, on_conflict="id").execute()
            upserted += len(rows)
        except Exception as exc:
            errors += len(rows)
            print(f"\n  [ERROR] batch starting at {batch_start}: {exc}")

        elapsed = time.perf_counter() - t0
        pct     = (batch_start + len(batch_docs)) / total * 100
        rate    = upserted / elapsed if elapsed > 0 else 0
        print(
            f"  [{upserted:>6,}/{total:,}]  {pct:5.1f}%  ({rate:.0f} docs/s)",
            end="\r",
            flush=True,
        )

    elapsed = time.perf_counter() - t0
    print(f"\n  Upserted {upserted:,} docs in {elapsed:.1f}s  "
          f"({upserted / elapsed:.0f} docs/s)")
    if errors:
        print(f"  WARNING: {errors} docs failed — re-run to retry.")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Ingest TV scene documents into Supabase pgvector"
    )
    p.add_argument(
        "--csv", default=_DEFAULT_CSV,
        help=f"Path to merged_tv_dialogues.csv (default: {_DEFAULT_CSV})",
    )
    p.add_argument(
        "--batch-size", type=int, default=_DEFAULT_BATCH_SIZE,
        metavar="N",
        help=f"Docs per upsert batch (default: {_DEFAULT_BATCH_SIZE}). "
             "Lower this if you hit Supabase payload-size limits.",
    )
    p.add_argument(
        "--reset", action="store_true",
        help="Truncate the tv_scenes table before reingest (full rebuild).",
    )
    return p


if __name__ == "__main__":
    load_dotenv()
    args = _build_cli().parse_args()

    # ── Credentials ───────────────────────────────────────────────────────────
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

    if not url or not key:
        raise SystemExit(
            "ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.\n"
            "Add them to your .env file:\n"
            "  SUPABASE_URL=https://<project-ref>.supabase.co\n"
            "  SUPABASE_SERVICE_KEY=<service-role-key>\n"
            "\n"
            "The service-role key is in: Supabase Dashboard → Settings → API."
        )

    # ── Connect ───────────────────────────────────────────────────────────────
    print(f"Connecting to Supabase ({url}) ...")
    sb_client = create_client(url, key)
    print("  Connected.")

    # ── Load embedding model ──────────────────────────────────────────────────
    print(f"\nLoading embedding model '{_EMBED_MODEL}' ...")
    embed_model = SentenceTransformer(_EMBED_MODEL)
    dim = embed_model.get_sentence_embedding_dimension()
    print(f"  Embedding dim: {dim}")
    if dim != 384:
        raise SystemExit(
            f"ERROR: model '{_EMBED_MODEL}' has dim={dim}, but the schema "
            "expects vector(384).  Check your model or schema."
        )

    # ── Run ingest ────────────────────────────────────────────────────────────
    print()
    ingest(
        csv_path=args.csv,
        sb=sb_client,
        model=embed_model,
        batch_size=args.batch_size,
        reset=args.reset,
    )

    print("\nDone.")
