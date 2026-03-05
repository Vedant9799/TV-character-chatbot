#!/usr/bin/env python3
"""Build a scene-level ChromaDB collection from TV show dialogue CSV files.

Expected output document shape:
{
  "text": "The full dialogue of the scene (all characters' lines together)",
  "metadata": {
    "show": "big_bang_theory",
    "season": 3,
    "episode": 14,
    "scene": 2,
    "characters_present": ["Sheldon", "Leonard", "Penny"],
    "episode_title": "The Einstein Approximation"
  }
}

Note: Chroma metadata values cannot be arrays, so characters_present is stored
as a JSON string in the metadata under the same key.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import chromadb
import pandas as pd


@dataclass
class SceneDoc:
    doc_id: str
    text: str
    metadata: Dict[str, object]


# ---------------------------------------------------------------------------
# Text cleaning helpers  (ported from dialogue_token_analysis.ipynb)
# ---------------------------------------------------------------------------

def _norm_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _safe_int(value: object) -> int:
    text = _norm_text(value)
    if not text:
        return 0
    return int(float(text))


def _clean_dialogue(text: str) -> str:
    """Remove CSV noise from a dialogue line (mirrors notebook clean_dialogue)."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"[\"']+", "", text)    # stray quotes
    text = re.sub(r",{2,}", ",", text)    # collapsed commas
    text = re.sub(r"[ \t]+", " ", text)   # collapsed whitespace
    return text.strip()


def _strip_parentheticals(name: str) -> str:
    """'Sheldon (mouths)' → 'Sheldon',  'Leonard (mouths back)' → 'Leonard'."""
    return re.sub(r"\s*\(.*?\)", "", name).strip()


def _build_scene_text(lines: Iterable[Tuple[str, str]]) -> str:
    formatted = []
    for speaker, line in lines:
        speaker = _norm_text(speaker)
        line    = _norm_text(line)
        if not line:
            continue
        if speaker:
            formatted.append(f"{speaker}: {line}")
        else:
            formatted.append(line)
    return "\n".join(formatted).strip()


# ---------------------------------------------------------------------------
# Character normalisation maps
# ---------------------------------------------------------------------------

# Rows to treat as non-dialogue in the BBT CSV
_BBT_NON_CHARS = {"scene", "stage direction", "all"}

# Canonical name for known aliases / typos in BBT
_BBT_CHAR_ALIASES: Dict[str, str] = {
    # Spelling variants
    "Beverley":          "Beverly",       # Leonard's mom (typo)
    "Lesley":            "Leslie",        # Leslie Winkle (typo)
    # Formal titles → first names used in the show
    "Dr Koothrappali":   "Raj",
    "Dr Hofstadter":     "Leonard",
    # Flashback tags → canonical character
    "Past Sheldon":      "Sheldon",
    "Past Leonard":      "Leonard",
    # Sheldon's mom appears under two names
    "Mrs Cooper":        "Mary",
}

# Canonical name for known aliases / artefacts in The Office CSV
_OFFICE_CHAR_ALIASES: Dict[str, str] = {
    "Deangelo":   "DeAngelo",    # capitalisation inconsistency
    "Michael:":   "Michael",     # trailing-colon artefact
}


def parse_office_csv(csv_path: str) -> List[SceneDoc]:
    df = pd.read_csv(csv_path)

    # Drop trailing unnamed columns (artefact of a trailing comma in the CSV)
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

    required = {"season", "episode", "title", "scene", "speaker", "line"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {csv_path}: {sorted(missing)}")

    # ── Cleaning (mirrors dialogue_token_analysis.ipynb §2.2) ────────────────
    for col in df.select_dtypes("object").columns:
        df[col] = df[col].str.strip()

    # Normalise speaker names: aliases → canonical, then strip
    df["speaker"] = (
        df["speaker"]
        .map(lambda s: _OFFICE_CHAR_ALIASES.get(s, s) if isinstance(s, str) else s)
    )

    # Clean dialogue text
    df["line"] = df["line"].apply(_clean_dialogue)

    # Drop rows with null/empty speakers or blank dialogue
    df = df.dropna(subset=["speaker", "line"])
    df = df[(df["speaker"].str.strip() != "") & (df["line"].str.strip() != "")]
    # ─────────────────────────────────────────────────────────────────────────

    docs: List[SceneDoc] = []

    grouped = df.groupby(["season", "episode", "title", "scene"], sort=True, dropna=False)
    for (season, episode, title, scene), group in grouped:
        lines = list(zip(group["speaker"], group["line"]))
        text = _build_scene_text(lines)
        if not text:
            continue

        characters = sorted({_norm_text(s) for s in group["speaker"] if _norm_text(s)})
        season_i  = _safe_int(season)
        episode_i = _safe_int(episode)
        scene_i   = _safe_int(scene)

        docs.append(
            SceneDoc(
                doc_id=f"the_office_s{season_i:02d}e{episode_i:02d}sc{scene_i:03d}",
                text=text,
                metadata={
                    "show": "the_office",
                    "season": season_i,
                    "episode": episode_i,
                    "scene": scene_i,
                    "characters_present": json.dumps(characters),
                    "episode_title": _norm_text(title),
                },
            )
        )

    return docs


def parse_bigbang_csv(csv_path: str) -> List[SceneDoc]:
    df = pd.read_csv(csv_path)

    required = {"season", "episode", "episode_title", "character", "dialogue"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {csv_path}: {sorted(missing)}")

    # ── Cleaning (mirrors dialogue_token_analysis.ipynb §1.2) ────────────────
    for col in df.select_dtypes("object").columns:
        df[col] = df[col].str.strip()

    # 1. Strip parenthetical stage-direction suffixes from character names
    #    e.g. "Sheldon (mouths)" → "Sheldon", "Penny (to Raj)" → "Penny"
    df["character"] = df["character"].apply(
        lambda c: _strip_parentheticals(_norm_text(c))
    )

    # 2. Apply alias map: spelling variants, formal titles, flashback tags
    df["character"] = df["character"].map(
        lambda c: _BBT_CHAR_ALIASES.get(c, c)
    )

    # 3. Clean dialogue text
    df["dialogue"] = df["dialogue"].apply(_clean_dialogue)

    # 4. Drop blank dialogue or blank character names
    df = df[(df["character"].str.strip() != "") & (df["dialogue"].str.strip() != "")]
    # ─────────────────────────────────────────────────────────────────────────

    docs: List[SceneDoc] = []

    # Scene boundaries are inferred: a row where character == "Scene" (case-insensitive)
    # or any other non-dialogue marker starts a new scene.
    grouped = df.groupby(["season", "episode", "episode_title"], sort=True, dropna=False)
    for (season, episode, title), group in grouped:
        group = group.reset_index(drop=True)

        scenes: Dict[int, List[Tuple[str, str]]] = {}
        scene_characters: Dict[int, set] = {}

        scene_num = 1
        scenes[scene_num] = []
        scene_characters[scene_num] = set()

        for _, row in group.iterrows():
            character = _norm_text(row["character"])
            dialogue  = _norm_text(row["dialogue"])
            if not dialogue:
                continue

            # Treat "Scene", "Stage Direction", "All" etc. as scene-boundary markers
            char_lower = character.lower()
            is_non_char = char_lower in _BBT_NON_CHARS

            if is_non_char:
                # "Scene" marker → start a new scene (only if current scene has content)
                if char_lower == "scene" and scenes[scene_num]:
                    scene_num += 1
                    scenes[scene_num] = []
                    scene_characters[scene_num] = set()
                # Skip the non-character row entirely (don't add to scene text)
                continue

            scenes[scene_num].append((character, dialogue))
            scene_characters[scene_num].add(character)

        season_i  = _safe_int(season)
        episode_i = _safe_int(episode)

        for sc_num in sorted(scenes.keys()):
            text = _build_scene_text(scenes[sc_num])
            if not text:
                continue
            chars = sorted(scene_characters.get(sc_num, set()))

            docs.append(
                SceneDoc(
                    doc_id=f"big_bang_theory_s{season_i:02d}e{episode_i:02d}sc{sc_num:03d}",
                    text=text,
                    metadata={
                        "show": "big_bang_theory",
                        "season": season_i,
                        "episode": episode_i,
                        "scene": sc_num,
                        "characters_present": json.dumps(chars),
                        "episode_title": _norm_text(title),
                    },
                )
            )

    return docs


def upsert_to_chroma(docs: List[SceneDoc], persist_dir: str, collection_name: str, reset: bool) -> None:
    os.makedirs(persist_dir, exist_ok=True)
    client = chromadb.PersistentClient(path=persist_dir)

    if reset:
        existing = {c.name for c in client.list_collections()}
        if collection_name in existing:
            client.delete_collection(name=collection_name)

    collection = client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})

    # Batch to avoid large single writes.
    batch_size = 1000
    total = len(docs)
    for start in range(0, total, batch_size):
        batch = docs[start : start + batch_size]
        collection.upsert(
            ids=[d.doc_id for d in batch],
            documents=[d.text for d in batch],
            metadatas=[d.metadata for d in batch],
        )
        end = min(start + batch_size, total)
        print(f"  Ingested {end:,} / {total:,} docs ({end * 100 // total}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build scene-level ChromaDB for TV dialogue CSVs")
    parser.add_argument("--office-csv", default="TheOffice.csv", help="Path to The Office CSV")
    parser.add_argument(
        "--bigbang-csv",
        default="TheBigBangTheory_scraped.csv",
        help="Path to Big Bang Theory CSV",
    )
    parser.add_argument("--show", choices=["office", "bigbang", "both"], default="both")
    parser.add_argument("--persist-dir", default="./chroma_db")
    parser.add_argument("--collection", default="tv_scenes")
    parser.add_argument("--reset", action="store_true", help="Delete and recreate collection before upsert")
    args = parser.parse_args()

    all_docs: List[SceneDoc] = []

    if args.show in ("office", "both"):
        all_docs.extend(parse_office_csv(args.office_csv))

    if args.show in ("bigbang", "both"):
        all_docs.extend(parse_bigbang_csv(args.bigbang_csv))

    if not all_docs:
        raise SystemExit("No documents generated; check CSV paths/content.")

    upsert_to_chroma(all_docs, args.persist_dir, args.collection, args.reset)

    # ── Summary ──────────────────────────────────────────────────────────────
    shows = {}
    all_characters: set = set()
    for d in all_docs:
        show   = d.metadata.get("show", "unknown")
        season = d.metadata.get("season")
        ep     = d.metadata.get("episode")
        chars  = json.loads(d.metadata.get("characters_present", "[]"))

        if show not in shows:
            shows[show] = {"scenes": 0, "episodes": set(), "characters": set()}
        shows[show]["scenes"]   += 1
        shows[show]["episodes"].add((season, ep))
        shows[show]["characters"].update(chars)
        all_characters.update(chars)

    print(f"\n{'─' * 50}")
    print(f"  Collection : '{args.collection}'")
    print(f"  Location   : {args.persist_dir}")
    print(f"  Distance   : cosine")
    print(f"  Total docs : {len(all_docs):,}")
    print(f"{'─' * 50}")
    for show, stats in shows.items():
        label = show.replace("_", " ").title()
        print(f"  {label}")
        print(f"    Scenes     : {stats['scenes']:,}")
        print(f"    Episodes   : {len(stats['episodes']):,}")
        print(f"    Characters : {len(stats['characters'])} — {sorted(stats['characters'])}")
    print(f"{'─' * 50}")
    print(f"  Unique characters across all shows : {len(all_characters)}")
    print(f"{'─' * 50}\n")


if __name__ == "__main__":
    main()