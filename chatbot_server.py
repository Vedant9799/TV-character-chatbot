#!/usr/bin/env python3
"""WebSocket chatbot server — Qwen2.5-7B-Instruct + ChromaDB RAG.

Usage:
    # Base model + RAG (no fine-tuning required, no HF token needed)
    python chatbot_server.py

    # Use Hugging Face Inference API (no local model download; requires HF_TOKEN in .env)
    python chatbot_server.py --use-inference-api

    # Fine-tuned LoRA adapters + RAG
    python chatbot_server.py --adapter-path ./finetuned_model

The server:
  - Serves the chat UI at http://localhost:8000/
  - Accepts WebSocket connections at ws://localhost:8000/ws
  - Retrieves relevant scenes from ChromaDB for each user message (RAG)
  - Streams the model's response token-by-token back to the client
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from threading import Thread
from typing import Dict, List, Optional

import chromadb
import torch
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
# peft is imported lazily inside load_model() — only when LoRA adapters are present.
# Importing it at the top level pulls in torch.distributed.tensor → sympy, adding
# ~10 s of startup overhead even when no adapters are used.

# ---------------------------------------------------------------------------
# Character metadata (mirrors finetune.py)
# ---------------------------------------------------------------------------

CHARACTER_DESCRIPTIONS: Dict[str, str] = {
    "Michael": (
        "You are Michael Scott, the Regional Manager of Dunder Mifflin Scranton. "
        "You are enthusiastic, cringe-worthy, and desperately want to be liked. "
        "You believe you are everyone's best friend and the world's greatest boss. "
        "You often say 'That's what she said' and reference movies inappropriately. "
        "You often deflect serious topics with inappropriate humor."
    ),
    "Dwight": (
        "You are Dwight Schrute, Assistant (to the) Regional Manager at Dunder Mifflin. "
        "You are intensely loyal, own a beet farm, are a volunteer sheriff's deputy. "
        "You take everything with extreme seriousness and believe you are destined for greatness. "
        "You mention bears, beets, and Battlestar Galactica."
    ),
    "Jim": (
        "You are Jim Halpert, a salesman at Dunder Mifflin Scranton. "
        "You are sardonic, laid-back, and love pranking Dwight. "
        "You often react to absurdity with a knowing glance and dry wit."
    ),
    "Pam": (
        "You are Pam Beesly, the receptionist at Dunder Mifflin. "
        "You are kind, artistic, quietly funny, and often the voice of reason."
    ),
    "Andy": (
        "You are Andy Bernard, a salesman at Dunder Mifflin. "
        "You went to Cornell (which you mention constantly), love a cappella singing, "
        "and are eager to impress everyone."
    ),
    "Ryan": (
        "You are Ryan Howard, who started as a temp at Dunder Mifflin. "
        "You are self-absorbed, ambitious, and constantly reinventing your image."
    ),
    "Kevin": (
        "You are Kevin Malone, an accountant at Dunder Mifflin. "
        "You are simple-minded, lovable, passionate about food, poker, and your band Scrantonicity."
    ),
    "Angela": (
        "You are Angela Martin, head of accounting at Dunder Mifflin. "
        "You are uptight, judgmental, and obsessively devoted to your cats."
    ),
    "Sheldon": (
        "You are Sheldon Cooper, a theoretical physicist at Caltech with an IQ of 187. "
        "You lack social awareness, follow rigid routines, have a spot on the couch, "
        "and say 'Bazinga!' when joking. You believe you are intellectually superior to everyone. "
        "You are condescending when explaining things, often saying 'As I explained to Penny' or 'It's quite simple, really.'"
    ),
    "Leonard": (
        "You are Leonard Hofstadter, an experimental physicist at Caltech. "
        "You are insecure, romantic, and constantly caught between Sheldon's demands "
        "and trying to have a normal life."
    ),
    "Penny": (
        "You are Penny, an aspiring actress working as a waitress at The Cheesecake Factory. "
        "You are street-smart, fun, and perpetually bemused by your genius neighbors."
    ),
    "Howard": (
        "You are Howard Wolowitz, an aerospace engineer at Caltech and NASA astronaut. "
        "You are a self-proclaimed ladies' man and a mama's boy who still lives with his mother."
    ),
    "Raj": (
        "You are Raj Koothrappali, an astrophysicist at Caltech from New Delhi. "
        "You cannot speak to women unless you have had alcohol. "
        "You are deeply sentimental, romantic, and love Bollywood."
    ),
    "Bernadette": (
        "You are Bernadette Rostenkowski-Wolowitz, a microbiologist and Howard's wife. "
        "You have a sweet, high-pitched voice that belies a fierce, no-nonsense personality."
    ),
    "Amy": (
        "You are Amy Farrah Fowler, a neurobiologist and Sheldon's girlfriend. "
        "You desperately crave normal friendships despite your painfully awkward academic demeanor."
    ),
}

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

# ---------------------------------------------------------------------------
# Globals set at startup
# ---------------------------------------------------------------------------

model: Optional[AutoModelForCausalLM] = None
tokenizer: Optional[AutoTokenizer] = None
chroma_col = None
use_inference_api: bool = False
retrieval_strategy: str = "mmr"
retrieval_debug: bool = False
hf_inference_model_id: str = "Qwen/Qwen2.5-7B-Instruct"

# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def _detect_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_model(model_id: str, adapter_path: Optional[str], load_in_4bit: bool = False) -> None:
    global model, tokenizer

    device = _detect_device()
    print(f"Device: {device}")

    tok_source = adapter_path if (adapter_path and os.path.exists(adapter_path)) else model_id
    print(f"Loading tokenizer from: {tok_source}")
    tokenizer = AutoTokenizer.from_pretrained(tok_source)
    tokenizer.pad_token = tokenizer.eos_token

    print(f"Loading base model: {model_id}")

    if load_in_4bit:
        if device != "cuda":
            print("WARNING: --load-in-4bit requires CUDA. Falling back to bf16.")
            load_in_4bit = False

    if load_in_4bit:
        from transformers import BitsAndBytesConfig
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        base = AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=bnb_config,
            device_map="auto",
        )
        print("Loaded in 4-bit (NF4).")
    else:
        dtype = torch.float16 if device == "mps" else torch.bfloat16
        base = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=dtype,
            device_map="auto" if device == "cuda" else None,
        )
        if device != "cuda":
            base = base.to(device)
        print(f"Loaded in {dtype}, device={device}.")

    if adapter_path and os.path.exists(os.path.join(adapter_path, "adapter_config.json")):
        from peft import PeftModel  # lazy import — avoids heavy torch.distributed.tensor chain
        print(f"Loading LoRA adapters from: {adapter_path}")
        model = PeftModel.from_pretrained(base, adapter_path)
        print("Fine-tuned model loaded.")
    else:
        print("No LoRA adapters found — using base model with RAG prompting.")
        model = base

    model.eval()
    print("Model ready.\n")

# ---------------------------------------------------------------------------
# RAG — formatting and retrieval (retrieval logic in retrieval.py)
# ---------------------------------------------------------------------------

def _format_rag_as_fewshot(scene_block: str, character: str) -> str:
    """Format retrieved scenes as explicit few-shot examples for the model."""
    scenes = [s.strip() for s in scene_block.split("\n\n---\n\n") if s.strip()]
    if not scenes:
        return ""
    lines = [f"\n\nHere are example dialogues showing how {character} speaks and responds:"]
    for i, scene in enumerate(scenes, 1):
        lines.append(f"\nExample {i}:\n")
        lines.append(scene)
    lines.append(
        f"\n\nNow respond to the user as {character} would, in the same style as the examples above. "
        "Stay strictly in character. Use the examples as your primary guide. "
        "The show is set in 2005–2013; avoid references to real people or events from outside that era unless the examples include them."
    )
    return "".join(lines)


def retrieve_scene_examples(
    character: str,
    query: str,
    history: List[Dict],
    n_results: int = 8,
) -> str:
    """RAG retrieval via shared retrieval module (MMR strategy). More scenes = richer character voice in the prompt."""
    from retrieval import retrieve as retrieval_retrieve

    pairs = retrieval_retrieve(
        chroma_col, character, query, history, n_results=n_results, strategy=retrieval_strategy, debug=retrieval_debug
    )
    if not pairs:
        print(f"[RAG] No scenes found for character='{character}'")
        return ""
    texts = [text for _, text in pairs]
    print(f"[RAG] {character}: retrieved {len(texts)} scenes ({retrieval_strategy})")
    return "\n\n---\n\n".join(texts)

# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _run_generation(
    input_ids: torch.Tensor,
    attention_mask: torch.Tensor,
    streamer: TextIteratorStreamer,
) -> None:
    model.generate(
        input_ids=input_ids,
        attention_mask=attention_mask,
        streamer=streamer,
        max_new_tokens=300,
        temperature=0.8,
        top_p=0.9,
        do_sample=True,
        repetition_penalty=1.15,
        pad_token_id=tokenizer.eos_token_id,
    )


async def _stream_reply_via_inference_api(
    ws: WebSocket,
    messages: List[Dict],
) -> str:
    """Stream reply using Hugging Face Inference API (no local model)."""
    from huggingface_hub import AsyncInferenceClient

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN is not set. Add it to .env or set the environment variable.")

    client = AsyncInferenceClient(token=token)
    full_response = ""

    stream = await client.chat.completions.create(
        model=hf_inference_model_id,
        messages=messages,
        stream=True,
        max_tokens=300,
        temperature=0.8,
        top_p=0.9,
    )

    async for chunk in stream:
        if chunk.choices and len(chunk.choices) > 0:
            delta = chunk.choices[0].delta
            if delta and getattr(delta, "content", None):
                content = delta.content
                full_response += content
                await ws.send_text(json.dumps({"type": "token", "content": content}))

    await ws.send_text(json.dumps({"type": "done"}))
    return full_response


async def stream_reply(
    ws: WebSocket,
    character: str,
    history: List[Dict],
    user_msg: str,
) -> str:
    """Build prompt, generate, and stream tokens to the WebSocket client."""
    show = SHOW_MAP.get(character, "a TV show")
    desc = CHARACTER_DESCRIPTIONS.get(character, f"You are {character}.")

    # RAG context — formatted as explicit few-shot examples
    scene_block = await asyncio.to_thread(retrieve_scene_examples, character, user_msg, history)
    rag_section = _format_rag_as_fewshot(scene_block, character) if scene_block else ""

    system = (
        f"{desc} Stay fully in character as {character} from {show}. "
        f"Keep responses concise and natural — as if speaking in a real conversation.{rag_section}"
    )

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_msg})

    if use_inference_api:
        return await _stream_reply_via_inference_api(ws, messages)

    # Local model path
    # apply_chat_template returns a BatchEncoding (dict-like) for Qwen2.5,
    # not a raw tensor — so we must use return_dict=True and extract explicitly.
    tokenized = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    )
    input_ids      = tokenized["input_ids"].to(model.device)
    attention_mask = tokenized["attention_mask"].to(model.device)

    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    thread = Thread(target=_run_generation, args=(input_ids, attention_mask, streamer), daemon=True)
    thread.start()

    # Drain the streamer; yield control to the event loop between tokens
    full_response = ""
    streamer_iter = iter(streamer)
    loop = asyncio.get_event_loop()

    while True:
        token: Optional[str] = await loop.run_in_executor(None, next, streamer_iter, None)
        if token is None:
            break
        full_response += token
        await ws.send_text(json.dumps({"type": "token", "content": token}))

    await ws.send_text(json.dumps({"type": "done"}))
    return full_response

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="TV Character Chatbot")

# Serve static files (index.html etc.) from ./static
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = static_dir / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>index.html not found in ./static/</h1>", status_code=404)
    return HTMLResponse(html_path.read_text())


@app.get("/characters")
async def list_characters():
    grouped = {}
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
                history = []  # fresh conversation per character
                await ws.send_text(json.dumps({"type": "character_set", "character": character}))
                continue

            # --- Chat message ---
            user_msg = payload.get("message", "").strip()
            if not user_msg:
                continue

            full_response = await stream_reply(ws, character, history, user_msg)

            # Maintain rolling history (last 10 turns = 20 messages)
            history.append({"role": "user", "content": user_msg})
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
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="TV Character Chatbot Server")
    parser.add_argument(
        "--model-id", default="Qwen/Qwen2.5-7B-Instruct",
        help="HuggingFace model ID (default: Qwen/Qwen2.5-7B-Instruct)"
    )
    parser.add_argument(
        "--adapter-path", default="./finetuned_model",
        help="Path to LoRA adapters from finetune.ipynb (optional)"
    )
    parser.add_argument("--persist-dir", default="./chroma_db")
    parser.add_argument("--collection", default="tv_scenes")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--load-in-4bit", action="store_true",
        help="Load model in 4-bit NF4 quantisation for faster inference (CUDA only)",
    )
    parser.add_argument(
        "--use-inference-api", action="store_true",
        help="Use Hugging Face Inference API instead of loading model locally (requires HF_TOKEN in .env)",
    )
    parser.add_argument(
        "--retrieval-strategy", choices=["topk", "mmr", "hybrid"], default="mmr",
        help="Retrieval strategy: topk, mmr (default), or hybrid (BM25 + Chroma + RRF)",
    )
    parser.add_argument(
        "--retrieval-debug", action="store_true",
        help="Log retrieval input, output, scoring, and candidates to retrieval_debug.log (agentic feedback)",
    )
    args = parser.parse_args()

    global chroma_col, use_inference_api, hf_inference_model_id, retrieval_strategy, retrieval_debug
    print(f"Connecting to ChromaDB at {args.persist_dir}...")
    chroma_client = chromadb.PersistentClient(path=args.persist_dir)
    chroma_col = chroma_client.get_collection(args.collection)
    print(f"  Collection '{args.collection}': {chroma_col.count()} docs")
    retrieval_strategy = args.retrieval_strategy
    retrieval_debug = args.retrieval_debug
    print(f"  Retrieval strategy: {retrieval_strategy}")
    if retrieval_debug:
        try:
            from retrieval_logger import get_log_path
            print(f"  Retrieval debug: ON (logs → {get_log_path().resolve()})")
        except ImportError:
            print(f"  Retrieval debug: ON (retrieval_logger not found; logs may not be captured)")
    print()

    if args.use_inference_api:
        use_inference_api = True
        hf_inference_model_id = args.model_id
        if not os.environ.get("HF_TOKEN"):
            raise SystemExit("--use-inference-api requires HF_TOKEN. Add it to .env or set the environment variable.")
        print(f"Using Hugging Face Inference API (model: {hf_inference_model_id}). No local model loaded.\n")
    else:
        load_model(args.model_id, args.adapter_path, args.load_in_4bit)

    print(f"Starting server at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
