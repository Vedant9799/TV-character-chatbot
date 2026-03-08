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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "Beverley":          "Beverly",
    "Lesley":            "Leslie",
    "Dr Koothrappali":   "Raj",
    "Dr Hofstadter":     "Leonard",
    "Past Sheldon":      "Sheldon",
    "Past Leonard":      "Leonard",
    "Mrs Cooper":        "Mary",
}

# Canonical name for known aliases / artefacts in The Office CSV
_OFFICE_CHAR_ALIASES: Dict[str, str] = {
    "Deangelo":   "DeAngelo",
    "Michael:":   "Michael",
}

# Main cast per show — used to add has_<name> boolean flags to every doc.
# These flags enable direct ChromaDB where-clause filtering (no Python post-filter).
_BBT_MAIN_CHARS:    List[str] = ["Sheldon", "Leonard", "Penny", "Howard", "Raj", "Amy", "Bernadette"]
_OFFICE_MAIN_CHARS: List[str] = ["Michael", "Dwight", "Jim", "Pam", "Andy", "Ryan", "Kevin", "Angela"]

# Style exemplars — characters whose lines are stored as short voice-sample docs.
# All four chatbot characters get exemplar docs for the voice-anchoring RAG pass.
_EXEMPLAR_CHARS        = ["Sheldon", "Leonard", "Michael", "Dwight"]
_EXEMPLAR_CONTEXT_TURNS = 2      # preceding turns of context per exemplar
_EXEMPLAR_MIN_WORDS    = 5       # skip very short lines


def _char_flags(chars_in_scene: set, main_chars: List[str]) -> Dict[str, bool]:
    """Return {has_sheldon: True/False, has_leonard: True/False, ...} for every main char."""
    return {f"has_{c.lower()}": (c in chars_in_scene) for c in main_chars}


def _merge_consecutive_lines(lines: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Merge consecutive utterances by the same speaker into one turn.

    e.g. three consecutive Sheldon rows → one combined Sheldon utterance.
    This avoids artificially splitting a single speech act across multiple docs.
    """
    if not lines:
        return []
    merged: List[List] = [[lines[0][0], lines[0][1]]]
    for speaker, dialogue in lines[1:]:
        if speaker == merged[-1][0]:
            merged[-1][1] = merged[-1][1].rstrip() + " " + dialogue
        else:
            merged.append([speaker, dialogue])
    return [(s, d) for s, d in merged]


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
        raw_lines = list(zip(group["speaker"], group["line"]))
        merged    = _merge_consecutive_lines(raw_lines)
        text      = _build_scene_text(merged)
        if not text:
            continue

        chars_set  = {_norm_text(s) for s in group["speaker"] if _norm_text(s)}
        characters = sorted(chars_set)
        season_i   = _safe_int(season)
        episode_i  = _safe_int(episode)
        scene_i    = _safe_int(scene)

        docs.append(
            SceneDoc(
                doc_id=f"the_office_s{season_i:02d}e{episode_i:02d}sc{scene_i:03d}",
                text=text,
                metadata={
                    "show":               "the_office",
                    "doc_type":           "canon",
                    "season":             season_i,
                    "episode":            episode_i,
                    "scene":              scene_i,
                    "characters_present": json.dumps(characters),
                    "episode_title":      _norm_text(title),
                    **_char_flags(chars_set, _OFFICE_MAIN_CHARS),
                },
            )
        )

    return docs


def parse_bigbang_csv(csv_path: str) -> List[SceneDoc]:
    """Parse TBBTcleaned.csv which uses an explicit scene_id integer column.

    Column schema: season, episode, character, dialogue, scene_id
    (No "Scene" marker rows — scene boundaries are pre-encoded as scene_id.)
    """
    df = pd.read_csv(csv_path)

    required = {"season", "episode", "character", "dialogue", "scene_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {csv_path}: {sorted(missing)}")

    # ── Cleaning ─────────────────────────────────────────────────────────────
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

    # 4. Drop non-character rows (Scene markers, Stage Directions, etc.)
    df = df[~df["character"].str.lower().isin(_BBT_NON_CHARS)]

    # 5. Drop blank dialogue or blank character names
    df = df[(df["character"].str.strip() != "") & (df["dialogue"].str.strip() != "")]
    # ─────────────────────────────────────────────────────────────────────────

    docs: List[SceneDoc] = []

    # scene_id already encodes scene boundaries — group directly
    grouped = df.groupby(["season", "episode", "scene_id"], sort=True)
    for (season, episode, scene_id), group in grouped:
        season_i  = _safe_int(season)
        episode_i = _safe_int(episode)
        sc_num    = _safe_int(scene_id)

        raw_lines = list(zip(group["character"].tolist(), group["dialogue"].tolist()))
        merged    = _merge_consecutive_lines(raw_lines)
        if not merged:
            continue

        chars_set = {s for s, _ in merged}
        chars     = sorted(chars_set)
        text      = _build_scene_text(merged)
        if not text.strip():
            continue

        flags = _char_flags(chars_set, _BBT_MAIN_CHARS)

        # ── Canon scene document ─────────────────────────────────────────────
        docs.append(
            SceneDoc(
                doc_id=f"big_bang_theory_s{season_i:02d}e{episode_i:02d}sc{sc_num:03d}",
                text=text,
                metadata={
                    "show":               "big_bang_theory",
                    "doc_type":           "canon",
                    "season":             season_i,
                    "episode":            episode_i,
                    "scene":              sc_num,
                    "scene_setting":      "",
                    "characters_present": json.dumps(chars),
                    "episode_title":      "",
                    **flags,
                },
            )
        )

        # ── Style exemplar documents (one per qualifying line per exemplar char) ─
        # Each exemplar = 1-2 turns of context + the character's reply.
        # Used in the second retrieval pass to anchor voice without injecting
        # a full scene's worth of other characters' dialogue.
        for exemplar_char in _EXEMPLAR_CHARS:
            if exemplar_char not in chars_set:
                continue
            for turn_idx, (speaker, line) in enumerate(merged):
                if speaker != exemplar_char:
                    continue
                if len(line.split()) < _EXEMPLAR_MIN_WORDS:
                    continue
                ctx = merged[max(0, turn_idx - _EXEMPLAR_CONTEXT_TURNS):turn_idx]
                if not ctx:
                    continue
                ctx_text      = "\n".join(f"{s}: {d}" for s, d in ctx)
                exemplar_text = f"{ctx_text}\n{exemplar_char}: {line}"
                char_slug     = exemplar_char.lower()

                docs.append(
                    SceneDoc(
                        doc_id=(
                            f"bbt_ex_{char_slug}_s{season_i:02d}e{episode_i:02d}"
                            f"sc{sc_num:03d}_t{turn_idx:04d}"
                        ),
                        text=exemplar_text,
                        metadata={
                            "show":               "big_bang_theory",
                            "doc_type":           "exemplar",
                            "season":             season_i,
                            "episode":            episode_i,
                            "scene":              sc_num,
                            "scene_setting":      "",
                            "characters_present": json.dumps([exemplar_char]),
                            "episode_title":      "",
                            **_char_flags({exemplar_char}, _BBT_MAIN_CHARS),
                        },
                    )
                )

    return docs


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

    # Drop non-character rows (scene headings, stage directions, etc.)
    _NON_CHARS = _BBT_NON_CHARS | {"stage directions", "narrator", "both",
                                    "everyone", "group", "crowd", "all"}
    df = df[~df["character"].str.lower().isin(_NON_CHARS)]
    df = df[(df["character"].str.strip() != "") & (df["dialogue"].str.strip() != "")]
    # ──────────────────────────────────────────────────────────────────────────

    # Show → (chroma metadata key, main cast list for has_<char> flags)
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

    grouped = df.groupby(["show", "season", "episode", "scene"], sort=True)
    for (show, season, episode, scene), group in grouped:
        cfg = _SHOW_CONFIG.get(show)
        if cfg is None:
            continue   # skip unexpected show values

        season_i  = _safe_int(season)
        episode_i = _safe_int(episode)
        scene_i   = _safe_int(scene)
        prefix    = cfg["id_prefix"]

        raw_lines = list(zip(group["character"].tolist(), group["dialogue"].tolist()))
        merged    = _merge_consecutive_lines(raw_lines)
        if not merged:
            continue

        chars_set = {s for s, _ in merged}
        chars     = sorted(chars_set)
        text      = _build_scene_text(merged)
        if not text.strip():
            continue

        flags = _char_flags(chars_set, cfg["main_chars"])

        # ── Canon document ────────────────────────────────────────────────────
        docs.append(
            SceneDoc(
                doc_id=(
                    f"{prefix}_s{season_i:02d}e{episode_i:02d}"
                    f"sc{scene_i:05d}"
                ),
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

        # ── Style exemplar documents (one per qualifying line per target char) ─
        for exemplar_char in _EXEMPLAR_CHARS:
            if exemplar_char not in chars_set:
                continue
            for turn_idx, (speaker, line) in enumerate(merged):
                if speaker != exemplar_char:
                    continue
                if len(line.split()) < _EXEMPLAR_MIN_WORDS:
                    continue
                ctx = merged[max(0, turn_idx - _EXEMPLAR_CONTEXT_TURNS):turn_idx]
                if not ctx:
                    continue
                ctx_text      = "\n".join(f"{s}: {d}" for s, d in ctx)
                exemplar_text = f"{ctx_text}\n{exemplar_char}: {line}"
                char_slug     = exemplar_char.lower()

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

    return docs


def upsert_to_chroma(
    docs: List[SceneDoc],
    persist_dir: str,
    collection_name: str,
    reset: bool,
    workers: int = 4,
    batch_size: int = 500,
) -> None:
    """Upsert all docs into ChromaDB using a thread pool.

    Each worker thread embeds + writes its own batch concurrently.
    The main speedup comes from parallelising the sentence-transformer
    embedding step, which is the CPU bottleneck.

    workers    — number of concurrent upsert threads (default 4)
    batch_size — docs per batch; smaller batches → more parallelism,
                 larger batches → better embedding throughput per call
    """
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

    # Thread-safe progress counter
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
            n = future.result()          # re-raises any exception from the worker
            with lock:
                ingested_count += n
                pct = ingested_count * 100 // total
                print(f"  Ingested {ingested_count:,} / {total:,} docs ({pct}%)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build scene-level ChromaDB for TV dialogue CSVs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python build_chromadb.py --reset                          # default: merged CSV\n"
            "  python build_chromadb.py --merged-csv merged_tv_dialogues.csv --reset\n"
            "  python build_chromadb.py --source separate --reset        # use original CSVs\n"
        ),
    )
    # ── Primary mode: merged CSV (default) ────────────────────────────────────
    parser.add_argument(
        "--merged-csv", default="merged_tv_dialogues.csv",
        help="Path to the merged dialogue CSV (default: merged_tv_dialogues.csv). "
             "Used when --source=merged (the default).",
    )
    # ── Legacy mode: separate CSVs ────────────────────────────────────────────
    parser.add_argument(
        "--source", choices=["merged", "separate"], default="merged",
        help="'merged' (default) reads merged_tv_dialogues.csv; "
             "'separate' reads --office-csv and --bigbang-csv individually.",
    )
    parser.add_argument("--office-csv",  default="TheOffice.csv",   help="Path to The Office CSV (--source=separate only)")
    parser.add_argument("--bigbang-csv", default="TBBTcleaned.csv", help="Path to TBBT CSV (--source=separate only)")
    parser.add_argument("--show", choices=["office", "bigbang", "both"], default="both",
                        help="Which show(s) to load when --source=separate (default: both)")
    # ── Common options ─────────────────────────────────────────────────────────
    parser.add_argument("--persist-dir", default="./chroma_db")
    parser.add_argument("--collection",  default="tv_scenes")
    parser.add_argument("--reset", action="store_true",
                        help="Delete and recreate the collection before upsert")
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Number of concurrent upsert threads (default: 4). "
             "Set to 1 to disable concurrency.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500,
        help="Documents per upsert batch (default: 500).",
    )
    args = parser.parse_args()

    all_docs: List[SceneDoc] = []

    if args.source == "merged":
        print(f"Parsing merged CSV: {args.merged_csv}")
        all_docs = parse_merged_csv(args.merged_csv)
    else:
        # Legacy: separate CSV files
        if args.show in ("office", "both"):
            all_docs.extend(parse_office_csv(args.office_csv))
        if args.show in ("bigbang", "both"):
            all_docs.extend(parse_bigbang_csv(args.bigbang_csv))

    if not all_docs:
        raise SystemExit("No documents generated; check CSV paths/content.")

    upsert_to_chroma(
        all_docs,
        args.persist_dir,
        args.collection,
        args.reset,
        workers=args.workers,
        batch_size=args.batch_size,
    )

    # ── Summary ──────────────────────────────────────────────────────────────
    shows: Dict[str, dict] = {}
    all_characters: set    = set()
    for d in all_docs:
        show      = d.metadata.get("show", "unknown")
        doc_type  = d.metadata.get("doc_type", "canon")
        season    = d.metadata.get("season")
        ep        = d.metadata.get("episode")
        chars     = json.loads(d.metadata.get("characters_present", "[]"))

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