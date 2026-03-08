#!/usr/bin/env python3
"""WebSocket chatbot server — Ollama + ChromaDB RAG.

Identical WebSocket/REST API to chatbot_server.py but uses a locally-running
Ollama model for generation instead of a HuggingFace model. No GPU / PyTorch
required — Ollama handles all model management.

Usage:
    # Make sure Ollama is running and the model is pulled first:
    #   ollama serve          (in a separate terminal if not already running)
    #   ollama pull tinyllama:1.1b

    python chatbot_server_ollama.py

    # Use a different model (any model you have pulled in Ollama):
    python chatbot_server_ollama.py --model llama3.2:3b
    python chatbot_server_ollama.py --model mistral:7b

    # By default the server reads character_profiles.json automatically.
    # Generate it first with:
    #   python character_profiler.py --synthesize

    # Use a custom profiles path:
    python chatbot_server_ollama.py --profiles /path/to/my_profiles.json

    # Skip the JSON file entirely and use only built-in descriptions:
    python chatbot_server_ollama.py --profiles none

    # Both flags together:
    python chatbot_server_ollama.py --model llama3:latest --profiles character_profiles.json

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

import chromadb
import numpy as np
import ollama
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Character metadata (mirrors chatbot_server.py)
# ---------------------------------------------------------------------------

CHARACTER_DESCRIPTIONS: Dict[str, str] = {
    # ── The Big Bang Theory ───────────────────────────────────────────────────
    "Sheldon": (
        "You are Sheldon Cooper, a theoretical physicist at Caltech with an IQ of 187. "
        "You lack social awareness, follow rigid routines, and have a designated spot on the couch. "
        "You believe you are intellectually superior to everyone. "
        "You only say 'Bazinga!' on rare occasions — specifically when you reveal that a previous "
        "statement was a deliberate deception or joke. "
        "Never use 'Bazinga!' as a general exclamation, never end a response with it, and never "
        "use it more than once per conversation."
    ),
    "Leonard": (
        "You are Leonard Hofstadter, an experimental physicist at Caltech and Sheldon's roommate. "
        "You are insecure yet warm-hearted, deeply romantic, and perpetually caught between "
        "accommodating Sheldon's impossible demands and trying to have a normal social life. "
        "You wear glasses, have lactose intolerance, and grew up with an emotionally cold "
        "mother — a fact you bring up more than you'd like to admit. "
        "You speak in a self-deprecating, slightly neurotic tone and often serve as the "
        "voice of reason in the group."
    ),
    # ── The Office ────────────────────────────────────────────────────────────
    "Michael": (
        "You are Michael Scott, the Regional Manager of Dunder Mifflin Scranton. "
        "You are enthusiastic, deeply cringe-worthy, and desperately need to be liked by everyone. "
        "You believe you are the world's greatest boss and everyone's best friend, "
        "despite constant evidence to the contrary. "
        "You frequently say 'That's what she said', misquote movies, and declare yourself "
        "a 'great man' in the same breath as embarrassing yourself. "
        "You are simultaneously oblivious and oddly lovable."
    ),
    "Dwight": (
        "You are Dwight Schrute, Assistant (to the) Regional Manager at Dunder Mifflin. "
        "You own Schrute Farms — a working beet farm and bed-and-breakfast — and serve as "
        "a volunteer sheriff's deputy. "
        "You are fanatically loyal to Michael, intensely competitive with Jim, and take "
        "every task — no matter how trivial — with life-or-death seriousness. "
        "You pepper your speech with facts about beets, survivalism, and the superiority "
        "of the Schrute bloodline, and you believe you are destined for greatness."
    ),
}

SHOW_MAP: Dict[str, str] = {
    "Sheldon": "The Big Bang Theory",
    "Leonard": "The Big Bang Theory",
    "Michael": "The Office",
    "Dwight":  "The Office",
}

CHROMA_SHOW_KEY: Dict[str, str] = {
    "The Office": "the_office",
    "The Big Bang Theory": "big_bang_theory",
}

# Fallback response-style hints used when the profile has no RESPONSE STYLE section
# (i.e. when using the hardcoded CHARACTER_DESCRIPTIONS rather than a synthesised profile).
_RESPONSE_STYLE_HINTS: Dict[str, str] = {
    "Sheldon": (
        "Your responses can be lengthy — Sheldon thinks out loud, explains rigorously, "
        "and never truncates an idea just to seem brief."
    ),
    "Leonard": (
        "Keep responses moderate in length — Leonard is articulate and warm, "
        "but not long-winded."
    ),
    "Michael": (
        "Your responses tend to ramble — Michael goes off on tangents, makes unexpected "
        "pop-culture references, and circles back to himself."
    ),
    "Dwight": (
        "Your responses are clipped and authoritative — Dwight states facts directly "
        "with no filler or hedging."
    ),
}


def _parse_profile_sections(desc: str) -> Dict[str, str]:
    """Parse a synthesised 4-section profile into named parts.

    Recognises these headers (case-insensitive, with optional trailing spaces):
        IDENTITY:   SPEECH STYLE:   RULES:   RESPONSE STYLE:

    Returns a dict with keys ``identity``, ``speech_style``, ``rules``,
    ``response_style`` for whichever sections are present, plus ``raw``
    which always holds the original full string.
    """
    # Split on the known section headers, keeping the delimiter tokens
    pattern = r"(?mi)^(IDENTITY|SPEECH STYLE|RULES|RESPONSE STYLE)\s*:"
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

    The file must be the *synthesised* output — a flat dict of
    ``{character_name: description_string}``.  If the file contains the raw
    stats dict (values are dicts, not strings) the function skips those entries
    and warns instead of crashing.

    Returns a dict of only the entries that contain a usable string description.
    Missing characters fall back to the hardcoded CHARACTER_DESCRIPTIONS.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"--profiles file not found: {path}\n"
            "Run:  python character_profiler.py --synthesize"
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
            # Could be raw stats dict — skip silently (but collect for warning)
            skipped.append(char)

    if skipped:
        print(
            f"  [profiles] Skipped {len(skipped)} entries with non-string values "
            f"(raw stats?): {skipped}\n"
            "  Run character_profiler.py with --synthesize to generate descriptions."
        )

    return loaded


# ---------------------------------------------------------------------------
# Globals set at startup
# ---------------------------------------------------------------------------

chroma_col = None
ollama_model: str = "llama3:latest"   # overridden by --model

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
# Generation — Ollama streaming via background thread + queue
# ---------------------------------------------------------------------------

def _ollama_stream_thread(
    model_name: str,
    messages: List[Dict],
    out_q: "thread_queue.Queue[Optional[str]]",
) -> None:
    """Runs in a background thread.

    Streams tokens from Ollama and puts each chunk onto ``out_q``.
    Puts ``None`` as a sentinel when the stream is exhausted or on error.
    """
    try:
        for chunk in ollama.chat(model=model_name, messages=messages, stream=True):
            content = chunk.message.content
            if content:
                out_q.put(content)
    except Exception as exc:
        out_q.put(f"\n[Ollama error: {exc}]")
    finally:
        out_q.put(None)   # sentinel — tells the consumer we're done


async def stream_reply(
    ws: WebSocket,
    character: str,
    history: List[Dict],
    user_msg: str,
) -> str:
    """Build RAG-grounded prompt, stream Ollama response to the WebSocket client."""
    show = SHOW_MAP.get(character, "a TV show")
    desc = CHARACTER_DESCRIPTIONS.get(character, f"You are {character}.")

    # ── RAG: enrich query with last bot reply for better retrieval relevance ──
    last_bot_reply = next(
        (m["content"] for m in reversed(history) if m["role"] == "assistant"), ""
    )
    rag_query = f"{last_bot_reply} {user_msg}".strip() if last_bot_reply else user_msg

    canon_text, exemplar_text = await asyncio.to_thread(
        retrieve_scene_examples, character, rag_query
    )

    # ── Parse profile into named sections (handles both new 4-section format
    #    from character_profiler.py and the plain-prose hardcoded fallbacks) ──
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
        if "rules" in sections:
            # RULES get their own prominent block — models follow explicit
            # constraint lists much better than rules buried in prose.
            parts += [
                "CONSTRAINTS — follow every rule below without exception:",
                sections["rules"],
                "",
            ]
    else:
        # Plain-prose fallback (hardcoded CHARACTER_DESCRIPTIONS)
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

    # Closing instruction — character-aware response length guidance
    if has_sections and "response_style" in sections:
        parts.append(f"RESPONSE STYLE: {sections['response_style']}")
    else:
        hint = _RESPONSE_STYLE_HINTS.get(
            character,
            f"Respond as {character} would — natural and in character.",
        )
        parts.append(hint)

    system = "\n".join(parts)

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_msg})

    # Spin up producer thread; drain tokens via run_in_executor so the event
    # loop stays free while waiting for the next chunk from Ollama.
    out_q: thread_queue.Queue[Optional[str]] = thread_queue.Queue()
    Thread(
        target=_ollama_stream_thread,
        args=(ollama_model, messages, out_q),
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

app = FastAPI(title="TV Character Chatbot (Ollama)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
async def health():
    """Lightweight liveness probe used by start.sh and monitoring tools."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = static_dir / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>index.html not found in ./static/</h1>", status_code=404)
    return HTMLResponse(html_path.read_text())


@app.get("/characters")
async def list_characters():
    grouped: Dict[str, List[str]] = {}
    for char, show in SHOW_MAP.items():
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
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global chroma_col, ollama_model, CHARACTER_DESCRIPTIONS

    parser = argparse.ArgumentParser(description="TV Character Chatbot Server (Ollama)")
    parser.add_argument(
        "--model", default="llama3:latest",
        help="Ollama model tag to use (default: llama3:latest). "
             "Must already be pulled: ollama pull <model>",
    )
    parser.add_argument(
        "--profiles", default="character_profiles.json", metavar="PATH",
        help="Path to character_profiles.json produced by character_profiler.py "
             "(--synthesize output).  Defaults to 'character_profiles.json' in the "
             "current directory.  If the file is not found the built-in descriptions "
             "are used as a fallback.  Pass --profiles none to skip the file entirely.",
    )
    parser.add_argument("--persist-dir",  default="./chroma_db")
    parser.add_argument("--collection",   default="tv_scenes")
    parser.add_argument("--host",         default="0.0.0.0")
    parser.add_argument("--port",         type=int, default=8001)
    args = parser.parse_args()

    ollama_model = args.model

    # ── Load character descriptions from JSON (default: character_profiles.json) ─
    profiles_path = args.profiles.strip() if args.profiles else ""
    skip_file = profiles_path.lower() in ("", "none", "false")

    if skip_file:
        print("Using built-in character descriptions.")
    else:
        print(f"Loading character descriptions from '{profiles_path}' ...")
        try:
            file_descs = load_descriptions_from_file(profiles_path)

            # Heuristic show assignment for characters not already in SHOW_MAP.
            # Check the description text for known show identifiers.
            _OFFICE_MARKERS = {"dunder mifflin", "the office", "scranton",
                                "schrute farms", "regional manager", "beet"}

            overridden, kept = [], []
            for char, desc in file_descs.items():
                CHARACTER_DESCRIPTIONS[char] = desc
                overridden.append(char)
                if char not in SHOW_MAP:
                    desc_lower = desc.lower()
                    if any(m in desc_lower for m in _OFFICE_MARKERS):
                        SHOW_MAP[char] = "The Office"
                    else:
                        SHOW_MAP[char] = "The Big Bang Theory"

            for char in CHARACTER_DESCRIPTIONS:
                if char not in file_descs:
                    kept.append(char)

            print(f"  Loaded  from file : {overridden or '(none)'}")
            if kept:
                print(f"  Using built-in for: {kept}")

        except FileNotFoundError:
            # File not found is fine when using the default path — just use built-ins
            print(
                f"  '{profiles_path}' not found — using built-in descriptions.\n"
                "  Run `python character_profiler.py --synthesize` to generate it."
            )
        except ValueError as exc:
            print(f"  WARNING: Could not parse '{profiles_path}': {exc}")
            print("  Falling back to built-in descriptions.")

    # Verify Ollama is reachable and the model is available
    print(f"Checking Ollama model '{ollama_model}' ...")
    try:
        available = [m.model for m in ollama.list().models]
        if not any(ollama_model in m for m in available):
            print(
                f"  WARNING: '{ollama_model}' not found in local Ollama models.\n"
                f"  Run: ollama pull {ollama_model}\n"
                f"  Available: {available}"
            )
        else:
            print(f"  Model '{ollama_model}' is available.")
    except Exception as exc:
        print(f"  WARNING: Could not reach Ollama — is it running? ({exc})")
        print("  Start Ollama with: ollama serve")

    # Connect to ChromaDB
    print(f"\nConnecting to ChromaDB at {args.persist_dir} ...")
    chroma_client = chromadb.PersistentClient(path=args.persist_dir)
    chroma_col    = chroma_client.get_collection(args.collection)
    print(f"  Collection '{args.collection}': {chroma_col.count()} docs\n")

    print(f"Starting Ollama chatbot server at http://{args.host}:{args.port}")
    print(f"  Model : {ollama_model}")
    print(f"  RAG   : ChromaDB ({args.persist_dir})\n")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
