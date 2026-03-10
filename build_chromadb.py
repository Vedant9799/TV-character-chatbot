#!/usr/bin/env python3
"""Build a scene-level ChromaDB collection from merged_tv_dialogues.csv.

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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import chromadb
import pandas as pd


@dataclass
class SceneDoc:
    doc_id: str
    text: str
    metadata: Dict[str, object]


# ---------------------------------------------------------------------------
# Text cleaning helpers
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
    """Remove CSV noise from a dialogue line."""
    if not isinstance(text, str):
        return ""
    # Only strip double quotes (CSV artefacts). Single quotes / apostrophes
    # must be kept — they appear in contractions (don't, it's, I'm) and
    # possessives (Schrute's). Stripping them produces "Ive", "Thats", etc.
    text = re.sub(r'"+', "", text)        # stray double quotes only
    text = re.sub(r",{2,}", ",", text)    # collapsed commas
    text = re.sub(r"[ \t]+", " ", text)   # collapsed whitespace
    return text.strip()


def _strip_parentheticals(name: str) -> str:
    """'Sheldon (mouths)' → 'Sheldon'"""
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

# Rows to treat as non-dialogue
_NON_CHARS = {"scene", "stage direction", "stage directions", "all",
              "narrator", "both", "everyone", "group", "crowd"}

# Canonical name for known aliases / typos in BBT
_BBT_CHAR_ALIASES: Dict[str, str] = {
    "Beverley":          "Beverly",
    "Lesley":            "Leslie",
    "Dr Koothrappali":   "Raj",
    "Dr Hofstadter":     "Leonard",
    "Past Sheldon":      "Sheldon",
    "Past Leonard":      "Leonard",
    "Mrs Cooper":        "Mary",
}

# Canonical name for known aliases / artefacts in The Office
_OFFICE_CHAR_ALIASES: Dict[str, str] = {
    "Deangelo":   "DeAngelo",
    "Michael:":   "Michael",
}

# Main cast per show — used to add has_<name> boolean flags to every doc.
# These flags enable direct ChromaDB where-clause filtering.
_BBT_MAIN_CHARS:    List[str] = ["Sheldon", "Leonard", "Penny", "Howard", "Raj", "Amy", "Bernadette"]
_OFFICE_MAIN_CHARS: List[str] = ["Michael", "Dwight", "Jim", "Pam", "Andy", "Ryan", "Kevin", "Angela"]

# Style exemplars — characters whose lines are stored as short voice-sample docs.
_EXEMPLAR_CHARS          = ["Sheldon", "Leonard", "Michael", "Dwight"]
_EXEMPLAR_CONTEXT_TURNS  = 2    # preceding turns of context per exemplar
_EXEMPLAR_MIN_WORDS      = 5    # min words for a line with preceding context
_EXEMPLAR_MIN_WORDS_SOLO = 15   # min words for a standalone monologue (no prior ctx)

# The Office CSV uses a global scene counter — individual "scenes" are tiny
# beats/shots, not full scenes.  Merge consecutive scenes within an episode
# until each chunk reaches this many lines so canon docs have useful context.
_OFFICE_MIN_SCENE_LINES  = 8


def _char_flags(chars_in_scene: set, main_chars: List[str]) -> Dict[str, bool]:
    """Return {has_sheldon: True/False, ...} for every main char."""
    return {f"has_{c.lower()}": (c in chars_in_scene) for c in main_chars}


def _chunk_episode_scenes(
    scene_lines: List[Tuple[int, List[Tuple[str, str]]]],
    min_lines: int,
) -> List[Tuple[int, List[Tuple[str, str]]]]:
    """Merge consecutive (scene_id, lines) pairs until each chunk has ≥ min_lines.

    Used for The Office where individual scene beats are often 1-4 lines.
    Returns list of (first_scene_id_in_chunk, merged_lines).
    The last partial chunk is appended to the previous one to avoid
    orphan stubs; if there's only one chunk it's kept as-is.
    """
    chunks: List[Tuple[int, List[Tuple[str, str]]]] = []
    cur_scene = scene_lines[0][0]
    cur_lines: List[Tuple[str, str]] = []

    for scene_id, lines in scene_lines:
        if not cur_lines:
            cur_scene = scene_id
        cur_lines.extend(lines)
        if len(cur_lines) >= min_lines:
            chunks.append((cur_scene, cur_lines))
            cur_lines = []

    # Flush any remaining lines
    if cur_lines:
        if chunks:
            # Append to last chunk instead of creating a tiny stub
            chunks[-1] = (chunks[-1][0], chunks[-1][1] + cur_lines)
        else:
            chunks.append((cur_scene, cur_lines))

    return chunks


def _merge_consecutive_lines(lines: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Merge consecutive utterances by the same speaker into one turn."""
    if not lines:
        return []
    merged: List[List] = [[lines[0][0], lines[0][1]]]
    for speaker, dialogue in lines[1:]:
        if speaker == merged[-1][0]:
            merged[-1][1] = merged[-1][1].rstrip() + " " + dialogue
        else:
            merged.append([speaker, dialogue])
    return [(s, d) for s, d in merged]


# ---------------------------------------------------------------------------
# Parser — merged CSV only
# ---------------------------------------------------------------------------

def parse_merged_csv(csv_path: str) -> List[SceneDoc]:
    """Parse merged_tv_dialogues.csv — the unified TBBT + Office CSV.

    Column schema: show, season, episode, scene, character, dialogue

    Produces canon scene docs and style-exemplar docs for every character in
    _EXEMPLAR_CHARS.  Both shows are handled in a single pass by grouping on
    (show, season, episode, scene), which is unique across the merged file.

    Show metadata written to ChromaDB:
        "The Big Bang Theory"  →  "big_bang_theory"
        "The Office"           →  "the_office"
    """
    df = pd.read_csv(csv_path)

    required = {"show", "season", "episode", "scene", "character", "dialogue"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Missing required columns in {csv_path}: {sorted(missing)}\n"
            "Expected merged_tv_dialogues.csv with columns: "
            "show, season, episode, scene, character, dialogue"
        )

    # ── Cleaning ──────────────────────────────────────────────────────────────
    for col in df.select_dtypes("object").columns:
        df[col] = df[col].fillna("").astype(str).str.strip()

    # Strip parenthetical stage-direction suffixes from character names
    df["character"] = df["character"].apply(
        lambda c: _strip_parentheticals(_norm_text(c))
    )

    # Apply show-specific alias maps
    df.loc[df["show"] == "The Big Bang Theory", "character"] = (
        df.loc[df["show"] == "The Big Bang Theory", "character"]
        .map(lambda c: _BBT_CHAR_ALIASES.get(c, c))
    )
    df.loc[df["show"] == "The Office", "character"] = (
        df.loc[df["show"] == "The Office", "character"]
        .map(lambda c: _OFFICE_CHAR_ALIASES.get(c, c))
    )

    # Clean dialogue text
    df["dialogue"] = df["dialogue"].apply(_clean_dialogue)

    # Drop non-character rows and blank entries
    df = df[~df["character"].str.lower().isin(_NON_CHARS)]
    df = df[(df["character"].str.strip() != "") & (df["dialogue"].str.strip() != "")]
    # ──────────────────────────────────────────────────────────────────────────

    # Show → chroma metadata config
    _SHOW_CONFIG: Dict[str, Dict] = {
        "The Big Bang Theory": {
            "chroma_key":  "big_bang_theory",
            "main_chars":  _BBT_MAIN_CHARS,
            "id_prefix":   "big_bang_theory",
        },
        "The Office": {
            "chroma_key":  "the_office",
            "main_chars":  _OFFICE_MAIN_CHARS,
            "id_prefix":   "the_office",
        },
    }

    docs: List[SceneDoc] = []

    def _emit_docs(
        cfg: Dict,
        season_i: int,
        episode_i: int,
        scene_i: int,
        merged: List[Tuple[str, str]],
    ) -> None:
        """Emit one canon doc + all qualifying exemplar docs for a scene chunk."""
        if not merged:
            return
        prefix    = cfg["id_prefix"]
        chars_set = {s for s, _ in merged}
        chars     = sorted(chars_set)
        text      = _build_scene_text(merged)
        if not text.strip():
            return
        flags = _char_flags(chars_set, cfg["main_chars"])

        # ── Canon document ────────────────────────────────────────────────────
        docs.append(
            SceneDoc(
                doc_id=f"{prefix}_s{season_i:02d}e{episode_i:02d}sc{scene_i:05d}",
                text=text,
                metadata={
                    "show":               cfg["chroma_key"],
                    "doc_type":           "canon",
                    "season":             season_i,
                    "episode":            episode_i,
                    "scene":              scene_i,
                    "characters_present": json.dumps(chars),
                    "episode_title":      "",
                    **flags,
                },
            )
        )

        # ── Style exemplar documents ──────────────────────────────────────────
        for exemplar_char in _EXEMPLAR_CHARS:
            if exemplar_char not in chars_set:
                continue
            for turn_idx, (speaker, line) in enumerate(merged):
                if speaker != exemplar_char:
                    continue
                words = len(line.split())
                ctx   = merged[max(0, turn_idx - _EXEMPLAR_CONTEXT_TURNS):turn_idx]

                if ctx:
                    # Normal case: line with preceding dialogue context
                    if words < _EXEMPLAR_MIN_WORDS:
                        continue
                    ctx_text      = "\n".join(f"{s}: {d}" for s, d in ctx)
                    exemplar_text = f"{ctx_text}\n{exemplar_char}: {line}"
                else:
                    # No preceding context — only keep substantial solo monologues
                    # (talking-head confessionals in The Office, cold-open speeches, etc.)
                    if words < _EXEMPLAR_MIN_WORDS_SOLO:
                        continue
                    exemplar_text = f"{exemplar_char}: {line}"

                char_slug = exemplar_char.lower()
                docs.append(
                    SceneDoc(
                        doc_id=(
                            f"{prefix}_ex_{char_slug}"
                            f"_s{season_i:02d}e{episode_i:02d}"
                            f"sc{scene_i:05d}_t{turn_idx:04d}"
                        ),
                        text=exemplar_text,
                        metadata={
                            "show":               cfg["chroma_key"],
                            "doc_type":           "exemplar",
                            "season":             season_i,
                            "episode":            episode_i,
                            "scene":              scene_i,
                            "characters_present": json.dumps([exemplar_char]),
                            "episode_title":      "",
                            **_char_flags({exemplar_char}, cfg["main_chars"]),
                        },
                    )
                )

    # ── Main parsing loop ─────────────────────────────────────────────────────
    # TBBT: scenes are already full-sized → one doc per scene.
    # The Office: scenes are tiny beats (median 4 lines, 39% have 1-2 lines)
    # with a global scene counter.  Merge consecutive scenes within each episode
    # into chunks of ≥ _OFFICE_MIN_SCENE_LINES for richer canon docs.

    # ── TBBT pass ────────────────────────────────────────────────────────────
    bbt_cfg = _SHOW_CONFIG["The Big Bang Theory"]
    bbt_df  = df[df["show"] == "The Big Bang Theory"]
    for (season, episode, scene), group in bbt_df.groupby(
        ["season", "episode", "scene"], sort=True
    ):
        raw   = list(zip(group["character"].tolist(), group["dialogue"].tolist()))
        merged = _merge_consecutive_lines(raw)
        _emit_docs(bbt_cfg, _safe_int(season), _safe_int(episode), _safe_int(scene), merged)

    # ── The Office pass ───────────────────────────────────────────────────────
    off_cfg = _SHOW_CONFIG["The Office"]
    off_df  = df[df["show"] == "The Office"]
    for (season, episode), ep_group in off_df.groupby(["season", "episode"], sort=True):
        season_i  = _safe_int(season)
        episode_i = _safe_int(episode)

        # Collect (scene_id, raw_lines) pairs in scene order
        scene_pairs: List[Tuple[int, List[Tuple[str, str]]]] = []
        for scene, sc_group in ep_group.groupby("scene", sort=True):
            raw = list(zip(sc_group["character"].tolist(), sc_group["dialogue"].tolist()))
            if raw:
                scene_pairs.append((_safe_int(scene), raw))

        if not scene_pairs:
            continue

        # Merge tiny scenes into chunks
        chunks = _chunk_episode_scenes(scene_pairs, _OFFICE_MIN_SCENE_LINES)
        for first_scene_id, chunk_lines in chunks:
            merged = _merge_consecutive_lines(chunk_lines)
            _emit_docs(off_cfg, season_i, episode_i, first_scene_id, merged)

    return docs


# ---------------------------------------------------------------------------
# ChromaDB upsert
# ---------------------------------------------------------------------------

def upsert_to_chroma(
    docs: List[SceneDoc],
    persist_dir: str,
    collection_name: str,
    reset: bool,
    workers: int = 4,
    batch_size: int = 1000,
) -> None:
    """Upsert all docs into ChromaDB using a thread pool."""
    os.makedirs(persist_dir, exist_ok=True)
    client = chromadb.PersistentClient(path=persist_dir)

    if reset:
        existing = {c.name for c in client.list_collections()}
        if collection_name in existing:
            client.delete_collection(name=collection_name)

    collection = client.get_or_create_collection(
        name=collection_name, metadata={"hnsw:space": "cosine"}
    )

    total   = len(docs)
    batches = [docs[i : i + batch_size] for i in range(0, total, batch_size)]

    ingested_count = 0
    lock = threading.Lock()

    def _upsert_batch(batch: List[SceneDoc]) -> int:
        collection.upsert(
            ids=[d.doc_id for d in batch],
            documents=[d.text for d in batch],
            metadatas=[d.metadata for d in batch],
        )
        return len(batch)

    print(
        f"  Upserting {total:,} docs in {len(batches)} batches "
        f"({batch_size} docs/batch, {workers} workers) …"
    )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_upsert_batch, b): b for b in batches}
        for future in as_completed(futures):
            n = future.result()
            with lock:
                ingested_count += n
                pct = ingested_count * 100 // total
                print(f"  Ingested {ingested_count:,} / {total:,} docs ({pct}%)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build scene-level ChromaDB from merged_tv_dialogues.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python build_chromadb.py --reset\n"
            "  python build_chromadb.py --csv merged_tv_dialogues.csv --reset\n"
        ),
    )
    parser.add_argument(
        "--csv", default="merged_tv_dialogues.csv",
        help="Path to merged_tv_dialogues.csv (default: merged_tv_dialogues.csv)",
    )
    parser.add_argument("--persist-dir", default="./chroma_db")
    parser.add_argument("--collection",  default="tv_scenes")
    parser.add_argument("--reset", action="store_true",
                        help="Delete and recreate the collection before upsert")
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Number of concurrent upsert threads (default: 4)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500,
        help="Documents per upsert batch (default: 500)",
    )
    args = parser.parse_args()

    print(f"Parsing merged CSV: {args.csv}")
    all_docs = parse_merged_csv(args.csv)

    if not all_docs:
        raise SystemExit("No documents generated; check CSV path/content.")

    upsert_to_chroma(
        all_docs,
        args.persist_dir,
        args.collection,
        args.reset,
        workers=args.workers,
        batch_size=args.batch_size,
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    shows: Dict[str, dict] = {}
    all_characters: set    = set()
    for d in all_docs:
        show     = d.metadata.get("show", "unknown")
        doc_type = d.metadata.get("doc_type", "canon")
        season   = d.metadata.get("season")
        ep       = d.metadata.get("episode")
        chars    = json.loads(d.metadata.get("characters_present", "[]"))

        if show not in shows:
            shows[show] = {"canon": 0, "exemplar": 0, "episodes": set(), "characters": set()}
        shows[show][doc_type]      = shows[show].get(doc_type, 0) + 1
        shows[show]["episodes"].add((season, ep))
        shows[show]["characters"].update(chars)
        all_characters.update(chars)

    canon_total    = sum(s.get("canon",    0) for s in shows.values())
    exemplar_total = sum(s.get("exemplar", 0) for s in shows.values())

    print(f"\n{'─' * 54}")
    print(f"  Collection : '{args.collection}'")
    print(f"  Location   : {args.persist_dir}")
    print(f"  Distance   : cosine")
    print(f"  Total docs : {len(all_docs):,}  (canon: {canon_total:,}  exemplar: {exemplar_total:,})")
    print(f"{'─' * 54}")
    for show, stats in shows.items():
        label = show.replace("_", " ").title()
        print(f"  {label}")
        print(f"    Canon scenes : {stats.get('canon', 0):,}")
        print(f"    Exemplars    : {stats.get('exemplar', 0):,}")
        print(f"    Episodes     : {len(stats['episodes']):,}")
        print(f"    Characters   : {len(stats['characters'])} — {sorted(stats['characters'])}")
    print(f"{'─' * 54}")
    print(f"  Unique characters across all shows : {len(all_characters)}")
    print(f"{'─' * 54}\n")


if __name__ == "__main__":
    main()
