#!/usr/bin/env python3
"""WebSocket chatbot server — Groq API + ChromaDB RAG.

Uses Groq's free OpenAI-compatible API for generation.
Set GROQ_API_KEY environment variable before running.

Usage:
    export GROQ_API_KEY=gsk_...
    python server.py

    # Use a different Groq model:
    python server.py --model llama-3.3-70b-versatile

    # By default the server reads character_profiles.json automatically.
    # Generate it first with:
    #   python character_profiler.py --characters "Sheldon:The Big Bang Theory,..."

    # Use a custom profiles path:
    python server.py --profiles /path/to/my_profiles.json

The server:
  - Serves the chat UI at http://localhost:8001/
  - Accepts WebSocket connections at ws://localhost:8001/ws
  - Retrieves relevant scenes from ChromaDB for each user message (RAG)
  - Streams the model's response token-by-token back to the client
"""

from __future__ import annotations

import argparse
import asyncio
import json
import queue as thread_queue
import re
from pathlib import Path
from threading import Thread
from typing import Dict, List, Optional

import numpy as np
import uvicorn

# ChromaDB — optional; only required when --backend chroma (default)
try:
    import chromadb as _chromadb_mod
    _CHROMADB_AVAILABLE = True
except ImportError:
    _CHROMADB_AVAILABLE = False

# Supabase + sentence-transformers — optional; only required when --backend supabase
try:
    from supabase import Client as _SupabaseClient
    from supabase import create_client as _create_supabase_client
    from sentence_transformers import SentenceTransformer as _SentenceTransformer
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False
from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Character metadata — populated at startup from character_profiles.json
# ---------------------------------------------------------------------------

# {character_name: description_string} — loaded from character_profiles.json
CHARACTER_DESCRIPTIONS: Dict[str, str] = {}

# {character_name: show_name} — derived from description text at startup
SHOW_MAP: Dict[str, str] = {}

# Show display name → database show key (same values used by both ChromaDB and
# Supabase backends).  Pre-seeded with the two known shows so the Supabase path
# works without a ChromaDB collection.  ChromaDB init may add discovered keys.
CHROMA_SHOW_KEY: Dict[str, str] = {
    "The Big Bang Theory": "big_bang_theory",
    "The Office":          "the_office",
}


def _discover_chroma_show_keys(col) -> Dict[str, str]:
    """Derive SHOW_MAP display-name → ChromaDB metadata key from the collection.

    Starts from the hardcoded fallback (so all known shows are always present),
    then supplements with any additional show keys found in a collection sample.
    Using only peek() was unreliable: peek returns the first N docs by insertion
    order, so if one show's docs are all inserted first the other show is never
    seen, leaving CHROMA_SHOW_KEY incomplete and RAG returning 0 for that show.
    """
    # Always start with the known mapping — this is the source of truth.
    known = {
        "The Office": "the_office",
        "The Big Bang Theory": "big_bang_theory",
    }
    try:
        sample = col.peek(limit=20)
        metas = sample.get("metadatas") or []
        for meta in metas:
            chroma_key = meta.get("show", "")
            if chroma_key and chroma_key not in known.values():
                # Unknown show discovered in collection — add it dynamically.
                display = chroma_key.replace("_", " ").title()
                known[display] = chroma_key
    except Exception:
        pass
    return known


def _infer_show_from_description(desc: str) -> str:
    """Best-effort show inference from a profile description string.

    Scans for distinctive proper nouns from each show.  Returns display name
    or empty string if uncertain.
    """
    lower = desc.lower()
    # Each list contains nouns unique to that show — not hand-curated tone
    # words, just proper nouns / place names that only appear in one show.
    if any(term in lower for term in (
        "dunder mifflin", "scranton", "schrute farms", "regional manager",
    )):
        return "The Office"
    if any(term in lower for term in (
        "caltech", "pasadena", "roommate agreement", "bazinga",
    )):
        return "The Big Bang Theory"
    return ""


def _parse_profile_sections(desc: str) -> Dict[str, str]:
    """Parse a synthesised profile into named parts.

    Recognises these headers (case-insensitive, with optional trailing spaces):
        IDENTITY:   SPEECH STYLE:   BEHAVIORAL TRIGGERS:   RULES:   RESPONSE STYLE:

    Returns a dict with keys ``identity``, ``speech_style``,
    ``behavioral_triggers``, ``rules``, ``response_style`` for whichever
    sections are present, plus ``raw`` which always holds the original full
    string.
    """
    # Split on the known section headers, keeping the delimiter tokens
    pattern = r"(?mi)^(IDENTITY|SPEECH STYLE|BEHAVIORAL TRIGGERS|RULES|RESPONSE STYLE)\s*:"
    parts = re.split(pattern, desc)

    result: Dict[str, str] = {"raw": desc}

    # parts layout after split: [preamble, header1, content1, header2, content2, ...]
    i = 1
    while i + 1 < len(parts):
        key   = parts[i].strip().lower().replace(" ", "_")  # e.g. "speech_style"
        value = parts[i + 1].strip()
        result[key] = value
        i += 2

    return result


# ---------------------------------------------------------------------------
# Description loader — reads character_profiles.json from character_profiler.py
# ---------------------------------------------------------------------------

def load_descriptions_from_file(path: str) -> Dict[str, str]:
    """Load character descriptions from a JSON file produced by character_profiler.py.

    The file must be the synthesised output — a flat dict of
    ``{character_name: description_string}``.

    Raises FileNotFoundError if the file does not exist.
    Raises ValueError if the file format is invalid.
    Skips (with a warning) any entries whose values are not strings.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Profiles file not found: {path}\n"
            "Generate it with:  python character_profiler.py "
            "--characters 'Character:Show,...'"
        )

    with p.open() as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}, got {type(data).__name__}")

    loaded: Dict[str, str] = {}
    skipped = []

    for char, value in data.items():
        if isinstance(value, str) and value.strip():
            loaded[char] = value.strip()
        else:
            skipped.append(char)

    if skipped:
        print(
            f"  [profiles] Skipped {len(skipped)} entries with non-string values: "
            f"{skipped}"
        )

    return loaded


# ---------------------------------------------------------------------------
# Globals set at startup
# ---------------------------------------------------------------------------

chroma_col = None
groq_model:  str = "qwen/qwen3-32b"   # overridden by --model
groq_client: OpenAI                   # initialised in main()

# Supabase-backend globals (None when falling back to chroma)
_rag_backend:    str    = "supabase"  # "chroma" | "supabase", resolved at startup
_supabase_client        = None        # supabase.Client instance
_sentence_model         = None        # SentenceTransformer instance

# ---------------------------------------------------------------------------
# RAG helpers (identical to chatbot_server.py)
# ---------------------------------------------------------------------------

def _cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr))
    return float(np.dot(a_arr, b_arr) / denom) if denom > 0 else 0.0


def _mmr_select(
    docs: List[str],
    distances: List[float],
    embeddings: List[List[float]],
    n_select: int,
    lambda_mult: float = 0.7,
) -> List[str]:
    """Maximal Marginal Relevance selection.

    Picks n_select items that balance:
      - Relevance  (low distance to query)
      - Diversity  (low cosine similarity to already-selected items)

    lambda_mult=1.0 → pure relevance, 0.0 → pure diversity.
    """
    if len(docs) <= n_select:
        return docs

    max_d = max(distances) or 1.0
    norm_dists = [d / max_d for d in distances]

    selected: List[int] = [0]
    remaining: List[int] = list(range(1, len(docs)))

    while len(selected) < n_select and remaining:
        scores = []
        for idx in remaining:
            relevance  = 1.0 - norm_dists[idx]
            redundancy = max(_cosine_sim(embeddings[idx], embeddings[s]) for s in selected)
            scores.append((lambda_mult * relevance - (1 - lambda_mult) * redundancy, idx))
        best = max(scores, key=lambda x: x[0])[1]
        selected.append(best)
        remaining.remove(best)

    return [docs[i] for i in selected]


# ---------------------------------------------------------------------------
# RAG — main retrieval function (identical to chatbot_server.py)
# ---------------------------------------------------------------------------

def retrieve_scene_examples(
    character: str, query: str, n_results: int = 4
) -> "tuple[str, str]":
    """Two-pass RAG pipeline.

    Pass 1 — Canon scenes (doc_type="canon"):
        Full scenes where the character appears, filtered at DB level via
        has_<name> boolean metadata flag. Returns 3 MMR-selected scenes.

    Pass 2 — Style exemplars (doc_type="exemplar"):
        Short character-line + context snippets for voice anchoring.
        Returns 2 MMR-selected exemplars.

    Returns:
        (canon_text, exemplar_text) — each a ``---``-separated block of
        retrieved passages, or an empty string when nothing was found.
    """
    CANON_POOL    = 20
    EXEMPLAR_POOL = 10
    CANON_N       = n_results - 1   # 3 canon scenes
    EXEMPLAR_N    = 2               # 2 style exemplars (was 1)

    show        = SHOW_MAP.get(character, "")
    chroma_show = CHROMA_SHOW_KEY.get(show, "")
    char_key    = f"has_{character.lower()}"   # e.g. "has_sheldon"

    def _query(doc_type: str, pool: int):
        where = {
            "$and": [
                {"show":     {"$eq": chroma_show}},
                {"doc_type": {"$eq": doc_type}},
                {char_key:   {"$eq": True}},
            ]
        }
        try:
            r = chroma_col.query(
                query_texts=[query],
                n_results=pool,
                include=["documents", "metadatas", "distances", "embeddings"],
                where=where,
            )
            return (
                r["documents"][0], r["metadatas"][0],
                r["distances"][0], r["embeddings"][0],
            )
        except Exception as exc:
            print(f"[RAG] {doc_type} query error: {exc}")
            return [], [], [], []

    # ── Pass 1: canon scenes ─────────────────────────────────────────────────
    c_docs, c_metas, c_dists, c_embs = _query("canon", CANON_POOL)

    seen: set = set()
    canon_docs, canon_dists, canon_embs = [], [], []
    for doc, meta, dist, emb in zip(c_docs, c_metas, c_dists, c_embs):
        key = (meta.get("season"), meta.get("episode"), meta.get("scene"))
        if key in seen:
            continue
        seen.add(key)
        canon_docs.append(doc)
        canon_dists.append(dist)
        canon_embs.append(emb)

    canon_selected = _mmr_select(canon_docs, canon_dists, canon_embs, n_select=CANON_N)

    # ── Pass 2: style exemplars ──────────────────────────────────────────────
    e_docs, e_metas, e_dists, e_embs = _query("exemplar", EXEMPLAR_POOL)

    ex_seen: set = set()
    ex_docs, ex_dists, ex_embs = [], [], []
    for doc, meta, dist, emb in zip(e_docs, e_metas, e_dists, e_embs):
        key = (meta.get("season"), meta.get("episode"), meta.get("scene"), meta.get("turn_idx"))
        if key in ex_seen:
            continue
        ex_seen.add(key)
        ex_docs.append(doc)
        ex_dists.append(dist)
        ex_embs.append(emb)

    exemplar_selected = _mmr_select(ex_docs, ex_dists, ex_embs, n_select=EXEMPLAR_N)

    print(
        f"[RAG] {character}: "
        f"canon pool={len(c_docs)} → MMR={len(canon_selected)} | "
        f"exemplar pool={len(e_docs)} → MMR={len(exemplar_selected)}"
    )

    if not canon_selected and not exemplar_selected:
        print(f"[RAG] No scenes found for character='{character}'")

    canon_text    = "\n\n---\n\n".join(canon_selected)
    exemplar_text = "\n\n---\n\n".join(exemplar_selected)
    return canon_text, exemplar_text


# ---------------------------------------------------------------------------
# RAG — Supabase pgvector backend
# ---------------------------------------------------------------------------

def _embed_query(query: str) -> List[float]:
    """Embed a single query string using the sentence-transformers model."""
    emb = _sentence_model.encode(query, convert_to_numpy=True, normalize_embeddings=True)
    return emb.tolist()


def retrieve_from_supabase(
    character: str, query: str, n_results: int = 4
) -> "tuple[str, str]":
    """Two-pass RAG pipeline using Supabase pgvector.

    Mirrors retrieve_scene_examples() exactly — same pass structure, same
    deduplication logic, same return format — but queries the Supabase
    ``tv_scenes`` table via the ``match_tv_scenes`` RPC instead of ChromaDB.

    Results from the RPC are already ordered by cosine distance (nearest
    first), so we do simple top-N selection after deduplication rather than
    MMR (document embeddings are not returned by the RPC).
    """
    CANON_POOL    = 20
    EXEMPLAR_POOL = 10
    CANON_N       = n_results - 1   # 3 canon scenes
    EXEMPLAR_N    = 2               # 2 style exemplars

    show        = SHOW_MAP.get(character, "")
    db_show_key = CHROMA_SHOW_KEY.get(show, "")
    char_col    = f"has_{character.lower()}"   # e.g. "has_sheldon"

    query_emb = _embed_query(query)

    def _rpc(doc_type: str, pool: int) -> list:
        try:
            resp = _supabase_client.rpc("match_tv_scenes", {
                "query_embedding": query_emb,
                "filter_show":     db_show_key,
                "filter_doc_type": doc_type,
                "filter_char_col": char_col,
                "match_count":     pool,
            }).execute()
            return resp.data or []
        except Exception as exc:
            print(f"[RAG/Supabase] {doc_type} query error: {exc}")
            return []

    # ── Pass 1: canon scenes ─────────────────────────────────────────────────
    canon_rows = _rpc("canon", CANON_POOL)
    seen: set = set()
    canon_docs: List[str] = []
    for row in canon_rows:
        key = (row.get("season"), row.get("episode"), row.get("scene"))
        if key in seen:
            continue
        seen.add(key)
        canon_docs.append(row["content"])
    canon_selected = canon_docs[:CANON_N]

    # ── Pass 2: style exemplars ──────────────────────────────────────────────
    ex_rows = _rpc("exemplar", EXEMPLAR_POOL)
    ex_seen: set = set()
    ex_docs: List[str] = []
    for row in ex_rows:
        key = (row.get("season"), row.get("episode"), row.get("scene"), row.get("turn_idx"))
        if key in ex_seen:
            continue
        ex_seen.add(key)
        ex_docs.append(row["content"])
    exemplar_selected = ex_docs[:EXEMPLAR_N]

    print(
        f"[RAG/Supabase] {character}: "
        f"canon pool={len(canon_rows)} → top={len(canon_selected)} | "
        f"exemplar pool={len(ex_rows)} → top={len(exemplar_selected)}"
    )

    if not canon_selected and not exemplar_selected:
        print(f"[RAG/Supabase] No scenes found for character='{character}'")

    canon_text    = "\n\n---\n\n".join(canon_selected)
    exemplar_text = "\n\n---\n\n".join(exemplar_selected)
    return canon_text, exemplar_text


# ---------------------------------------------------------------------------
# Generation — Groq streaming via background thread + queue
# ---------------------------------------------------------------------------

def _groq_stream_thread(
    model_name: str,
    messages: List[Dict],
    out_q: "thread_queue.Queue[Optional[str]]",
) -> None:
    """Runs in a background thread.

    Collects the full Groq response first, strips all <think>…</think>
    blocks and character-name prefixes via regex on the complete text,
    then pushes the clean result onto *out_q* word-by-word so the client
    still sees a progressive typing effect.

    Previous approach streamed token-by-token with an in-flight state
    machine, but Qwen3 inserts inline <think> tags mid-word (e.g.
    ``Schr<think>ute</think>,``) which silently eats characters.
    Cleaning the full text after generation avoids this entirely.
    """
    try:
        stream = groq_client.chat.completions.create(
            model=model_name,
            messages=messages,
            stream=True,
        )
        # ── Collect full response ────────────────────────────────────────────
        raw = ""
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                raw += content

        # ── Clean up ─────────────────────────────────────────────────────────
        # 1. Strip ALL <think>…</think> blocks (initial + any inline ones)
        clean = re.sub(r"<think>[\s\S]*?</think>", "", raw)
        # 2. Remove character-name prefix the model sometimes adds
        #    e.g. "**Dwight Schrute**: …" or "Dwight: …"
        clean = re.sub(r"^\s*\*{0,2}[\w\s']+\*{0,2}\s*:\s*", "", clean, count=1)
        # 3. Strip asterisk formatting but keep the text inside.
        #    The model uses *word* for emphasis — removing the content
        #    destroys the sentence.  Just drop the marker characters.
        clean = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", clean)
        # 4. Remove bracketed stage directions  e.g. [looks around]
        clean = re.sub(r"\[[^\]]{1,60}\]", "", clean)
        # 5. Collapse extra whitespace left by removals
        clean = re.sub(r"  +", " ", clean).strip()

        # ── Push word-by-word for typing effect ──────────────────────────────
        if clean:
            words = clean.split(" ")
            for i, word in enumerate(words):
                out_q.put(word + (" " if i < len(words) - 1 else ""))

    except Exception as exc:
        out_q.put(f"\n[Groq error: {exc}]")
    finally:
        out_q.put(None)   # sentinel — tells the consumer we're done


async def stream_reply(
    ws: WebSocket,
    character: str,
    history: List[Dict],
    user_msg: str,
) -> str:
    """Build RAG-grounded prompt, stream Groq response to the WebSocket client."""
    show = SHOW_MAP.get(character, "a TV show")
    desc = CHARACTER_DESCRIPTIONS.get(character, f"You are {character}.")

    # ── RAG: enrich query with last bot reply for better retrieval relevance ──
    last_bot_reply = next(
        (m["content"] for m in reversed(history) if m["role"] == "assistant"), ""
    )
    rag_query = f"{last_bot_reply} {user_msg}".strip() if last_bot_reply else user_msg

    if _rag_backend == "supabase":
        canon_text, exemplar_text = await asyncio.to_thread(
            retrieve_from_supabase, character, rag_query
        )
    else:
        canon_text, exemplar_text = await asyncio.to_thread(
            retrieve_scene_examples, character, rag_query
        )

    # ── Parse profile into named sections (handles both new 4-section format
    #    from character_profiler.py) ──
    sections = _parse_profile_sections(desc)
    has_sections = "identity" in sections or "speech_style" in sections

    # ── Build structured system prompt ────────────────────────────────────────
    parts: List[str] = [
        # Hard roleplay contract — always first
        f"You are roleplaying as {character} from {show}. "
        f"Stay fully in character at all times. "
        f"Never break character, and never refer to yourself as an AI, "
        f"a language model, or a chatbot.",
        "",
    ]

    if has_sections:
        # Structured profile: lay out sections with clear labels so the model
        # knows exactly what each block is for.
        if "identity" in sections:
            parts += [f"CHARACTER: {sections['identity']}", ""]
        if "speech_style" in sections:
            parts += [f"SPEECH STYLE: {sections['speech_style']}", ""]
        if "behavioral_triggers" in sections:
            # Trigger pairs sit between speech style and hard constraints so
            # the model sees them as active situational cues, not just rules.
            parts += [
                f"BEHAVIORAL TRIGGERS — when these situations arise, react exactly as described:",
                sections["behavioral_triggers"],
                "",
            ]
        if "rules" in sections:
            # RULES get their own prominent block — models follow explicit
            # constraint lists much better than rules buried in prose.
            parts += [
                "CONSTRAINTS — follow every rule below without exception:",
                sections["rules"],
                "",
            ]
    else:
        # Profile without section headers — use as-is
        parts += [desc, ""]

    # RAG — canon scenes (world knowledge & vocabulary calibration)
    if canon_text:
        parts += [
            f"REFERENCE SCENES — real dialogue from {show} featuring {character}. "
            f"Use these to calibrate vocabulary, topics, and situational knowledge:",
            canon_text,
            "",
        ]

    # RAG — style exemplars (voice anchoring)
    if exemplar_text:
        parts += [
            f"VOICE EXEMPLARS — individual lines showing exactly how {character} "
            f"constructs sentences. Mirror this voice closely:",
            exemplar_text,
            "",
        ]

    # Closing instruction — response style + hard format rules
    if has_sections and "response_style" in sections:
        parts.append(f"RESPONSE STYLE: {sections['response_style']}")
    else:
        parts.append(f"Respond as {character} would — natural and in character.")

    parts += [
        "",
        "FORMAT RULES — non-negotiable:",
        "- Output ONLY the words your character speaks out loud. Nothing else.",
        "- Do NOT prefix with a character name (e.g. never write 'Dwight:' or '**Dwight**:').",
        "- No stage directions, no action descriptions, no asterisks (e.g. never write *smiles* or [looks around]).",
        "- Use natural spoken English with contractions (don't, can't, it's, I'm). Never sound robotic or like a list.",
        "- This is a CHAT. 1-4 sentences. Reply directly to what was just said.",
        "- The person you are talking to is NOT a character from the show. Do NOT call them Jim, Pam, Leonard, or any other character's name. You don't know who they are.",
    ]

    system = "\n".join(parts)

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    # /no_think suppresses Qwen3's <think> reasoning block for cleaner output.
    # Added only to the API payload — not stored in history.
    messages.append({"role": "user", "content": user_msg + " /no_think"})

    # Spin up producer thread; drain tokens via run_in_executor so the event
    # loop stays free while waiting for the next chunk from Groq.
    out_q: thread_queue.Queue[Optional[str]] = thread_queue.Queue()
    Thread(
        target=_groq_stream_thread,
        args=(groq_model, messages, out_q),
        daemon=True,
    ).start()

    full_response = ""
    loop = asyncio.get_running_loop()   # get_event_loop() is deprecated in 3.10+

    while True:
        token: Optional[str] = await loop.run_in_executor(None, out_q.get)
        if token is None:
            break
        full_response += token
        await ws.send_text(json.dumps({"type": "token", "content": token}))

    await ws.send_text(json.dumps({"type": "done"}))
    return full_response


# ---------------------------------------------------------------------------
# FastAPI app (identical routes to chatbot_server.py)
# ---------------------------------------------------------------------------

app = FastAPI(title="TV Character Chatbot (Groq)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    """Liveness probe — also returns the active model name for the compare UI."""
    return {"status": "ok", "model": groq_model}


@app.get("/characters")
async def list_characters():
    grouped: Dict[str, List[str]] = {}
    for char in CHARACTER_DESCRIPTIONS:
        show = SHOW_MAP.get(char, "Unknown")
        grouped.setdefault(show, []).append(char)
    return grouped


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    history: List[Dict] = []
    character = "Sheldon"

    try:
        while True:
            raw = await ws.receive_text()
            payload = json.loads(raw)

            # --- Character selection ---
            if payload.get("type") == "set_character":
                character = payload.get("character", character)
                history = []   # fresh conversation per character
                await ws.send_text(json.dumps({"type": "character_set", "character": character}))
                continue

            # --- Chat message ---
            user_msg = payload.get("message", "").strip()
            if not user_msg:
                continue

            full_response = await stream_reply(ws, character, history, user_msg)

            # Maintain rolling history (last 10 turns = 20 messages)
            history.append({"role": "user",      "content": user_msg})
            history.append({"role": "assistant", "content": full_response})
            if len(history) > 20:
                history = history[-20:]

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_text(json.dumps({"type": "error", "content": str(exc)}))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SPA static files — mounted LAST so all API routes above take priority.
# html=True enables the SPA fallback: any unmatched path returns index.html
# so React Router (or the root index) handles client-side navigation.
# Only active when ./static/ exists (i.e. inside Docker / after npm build).
# ---------------------------------------------------------------------------

_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="spa")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import os
    load_dotenv()
    global chroma_col, groq_model, groq_client, CHARACTER_DESCRIPTIONS, SHOW_MAP, \
           CHROMA_SHOW_KEY, _rag_backend, _supabase_client, _sentence_model

    parser = argparse.ArgumentParser(description="TV Character Chatbot Server (Groq)")
    parser.add_argument(
        "--model", default="qwen/qwen3-32b",
        help="Groq model to use (default: qwen/qwen3-32b). "
             "See https://console.groq.com/docs/models for available models.",
    )
    parser.add_argument(
        "--profiles", default="character_profiles.json", metavar="PATH",
        help="Path to character_profiles.json produced by character_profiler.py. "
             "Defaults to 'character_profiles.json' in the current directory.",
    )
    parser.add_argument(
        "--backend", default="supabase", choices=["chroma", "supabase"],
        help="RAG vector backend. Defaults to 'supabase' and falls back to "
             "'chroma' if Supabase is unavailable. Supabase requires "
             "SUPABASE_URL and SUPABASE_SERVICE_KEY.",
    )
    parser.add_argument("--persist-dir",  default="./chroma_db")
    parser.add_argument("--collection",   default="tv_scenes")
    parser.add_argument("--host",         default="0.0.0.0")
    parser.add_argument("--port",         type=int, default=8001)
    args = parser.parse_args()

    groq_model   = args.model
    _rag_backend = args.backend

    # ── Load character descriptions from JSON ────────────────────────────────
    print(f"Loading character descriptions from '{args.profiles}' ...")
    file_descs = load_descriptions_from_file(args.profiles)

    for char, desc in file_descs.items():
        CHARACTER_DESCRIPTIONS[char] = desc
        if char not in SHOW_MAP:
            inferred = _infer_show_from_description(desc)
            if inferred:
                SHOW_MAP[char] = inferred

    print(f"  Loaded {len(CHARACTER_DESCRIPTIONS)} character(s): {list(CHARACTER_DESCRIPTIONS)}")

    # ── Initialise Groq client ────────────────────────────────────────────────
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise SystemExit(
            "ERROR: GROQ_API_KEY environment variable is not set.\n"
            "Get a free key at https://console.groq.com and set it with:\n"
            "  export GROQ_API_KEY=gsk_..."
        )
    groq_client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    print(f"Groq client ready — model: {groq_model}")

    # ── Initialise RAG backend ────────────────────────────────────────────────
    def _init_supabase() -> tuple[bool, str]:
        global _supabase_client, _sentence_model, _rag_backend
        if not _SUPABASE_AVAILABLE:
            return False, "Supabase packages are not installed"

        supa_url = os.environ.get("SUPABASE_URL", "").strip()
        supa_key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
        if not supa_url or not supa_key:
            return False, "SUPABASE_URL or SUPABASE_SERVICE_KEY is missing"

        print(f"\nConnecting to Supabase ({supa_url}) ...")
        _supabase_client = _create_supabase_client(supa_url, supa_key)
        print("  Connected.")

        print("Loading sentence-transformers model (all-MiniLM-L6-v2) ...")
        _sentence_model = _SentenceTransformer("all-MiniLM-L6-v2")
        print(f"  Embedding dim: {_sentence_model.get_sentence_embedding_dimension()}")
        print(f"  Show keys: {CHROMA_SHOW_KEY}\n")

        _rag_backend = "supabase"
        print(f"Starting server at http://{args.host}:{args.port}")
        print(f"  Model : {groq_model}")
        print("  RAG   : Supabase pgvector\n")
        return True, ""

    def _init_chroma() -> tuple[bool, str]:
        global chroma_col, CHROMA_SHOW_KEY, _rag_backend
        if not _CHROMADB_AVAILABLE:
            return False, "chromadb is not installed"

        print(f"\nConnecting to ChromaDB at {args.persist_dir} ...")
        chroma_client = _chromadb_mod.PersistentClient(path=args.persist_dir)
        chroma_col = chroma_client.get_collection(args.collection)
        print(f"  Collection '{args.collection}': {chroma_col.count()} docs")

        discovered = _discover_chroma_show_keys(chroma_col)
        CHROMA_SHOW_KEY.update(discovered)
        print(f"  Show keys: {CHROMA_SHOW_KEY}\n")

        _rag_backend = "chroma"
        print(f"Starting server at http://{args.host}:{args.port}")
        print(f"  Model : {groq_model}")
        print(f"  RAG   : ChromaDB ({args.persist_dir})\n")
        return True, ""

    if args.backend == "supabase":
        ok, reason = _init_supabase()
        if not ok:
            print(f"Supabase unavailable, falling back to ChromaDB: {reason}")
            ok, chroma_reason = _init_chroma()
            if not ok:
                raise SystemExit(
                    "ERROR: Supabase unavailable and ChromaDB fallback failed.\n"
                    f"Supabase: {reason}\n"
                    f"ChromaDB: {chroma_reason}"
                )
    else:
        ok, reason = _init_chroma()
        if not ok:
            raise SystemExit(
                "ERROR: ChromaDB backend is unavailable.\n"
                f"Reason: {reason}"
            )

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
