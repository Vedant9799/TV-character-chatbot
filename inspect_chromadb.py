#!/usr/bin/env python3
"""Inspect the contents of the ChromaDB collection."""

import argparse
import json

import chromadb


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect ChromaDB tv_scenes collection")
    parser.add_argument("--persist-dir", default="./chroma_db")
    parser.add_argument("--collection", default="tv_scenes")
    parser.add_argument("--limit", type=int, default=5, help="Number of sample docs to show")
    parser.add_argument("--show", choices=["office", "bigbang", "both"], default="both")
    parser.add_argument("--preview-chars", type=int, default=300, help="Characters of text to preview per doc")
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=args.persist_dir)
    col = client.get_collection(args.collection)

    total = col.count()
    print(f"Total documents in '{args.collection}': {total}\n")

    # Per-show counts
    show_map = {
        "office": "the_office",
        "bigbang": "big_bang_theory",
    }
    for key, show_val in show_map.items():
        result = col.get(where={"show": show_val})
        print(f"  {show_val}: {len(result['ids'])} scenes")
    print()

    # Sample docs
    where_filter = None
    if args.show == "office":
        where_filter = {"show": "the_office"}
    elif args.show == "bigbang":
        where_filter = {"show": "big_bang_theory"}

    kwargs = dict(limit=args.limit, include=["documents", "metadatas"])
    if where_filter:
        kwargs["where"] = where_filter

    result = col.get(**kwargs)

    print(f"--- Sample ({args.limit} docs, show={args.show}) ---")
    for i, (doc_id, doc, meta) in enumerate(zip(result["ids"], result["documents"], result["metadatas"])):
        chars = json.loads(meta["characters_present"])
        print(f"\n[{i + 1}] {doc_id}")
        print(f"  Show    : {meta['show']}")
        print(f"  Episode : S{meta['season']:02d}E{meta['episode']:02d} - {meta['episode_title']}")
        print(f"  Scene   : {meta['scene']}")
        print(f"  Cast    : {', '.join(chars)}")
        preview = doc[: args.preview_chars].replace("\n", " | ")
        print(f"  Text    : {preview}{'...' if len(doc) > args.preview_chars else ''}")


if __name__ == "__main__":
    main()
