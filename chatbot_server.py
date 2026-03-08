# #!/usr/bin/env python3
# """WebSocket chatbot server — SmolLM2 1.7B Instruct + ChromaDB RAG.

# Usage:
#     # Base model + RAG (no fine-tuning required, no HF token needed)
#     python chatbot_server.py

#     # Fine-tuned LoRA adapters + RAG
#     python chatbot_server.py --adapter-path ./finetuned_model

# The server:
#   - Serves the chat UI at http://localhost:8000/
#   - Accepts WebSocket connections at ws://localhost:8000/ws
#   - Retrieves relevant scenes from ChromaDB for each user message (RAG)
#   - Streams the model's response token-by-token back to the client
# """

# from __future__ import annotations

# import argparse
# import asyncio
# import json
# import os
# from pathlib import Path
# from threading import Thread
# from typing import Dict, List, Optional

# import chromadb
# import numpy as np
# import torch
# import uvicorn
# from fastapi import FastAPI, WebSocket, WebSocketDisconnect
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.responses import HTMLResponse
# from fastapi.staticfiles import StaticFiles
# from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
# # peft is imported lazily inside load_model() — only when LoRA adapters are present.
# # Importing it at the top level pulls in torch.distributed.tensor → sympy, adding
# # ~10 s of startup overhead even when no adapters are used.

# # ---------------------------------------------------------------------------
# # Character metadata (mirrors finetune.py)
# # ---------------------------------------------------------------------------

# CHARACTER_DESCRIPTIONS: Dict[str, str] = {
#     "Michael": (
#         "You are Michael Scott, the Regional Manager of Dunder Mifflin Scranton. "
#         "You are enthusiastic, cringe-worthy, and desperately want to be liked. "
#         "You believe you are everyone's best friend and the world's greatest boss. "
#         "You often say 'That's what she said' and reference movies inappropriately."
#     ),
#     "Dwight": (
#         "You are Dwight Schrute, Assistant (to the) Regional Manager at Dunder Mifflin. "
#         "You are intensely loyal, own a beet farm, are a volunteer sheriff's deputy. "
#         "You take everything with extreme seriousness and believe you are destined for greatness."
#     ),
#     "Jim": (
#         "You are Jim Halpert, a salesman at Dunder Mifflin Scranton. "
#         "You are sardonic, laid-back, and love pranking Dwight. "
#         "You often react to absurdity with a knowing glance and dry wit."
#     ),
#     "Pam": (
#         "You are Pam Beesly, the receptionist at Dunder Mifflin. "
#         "You are kind, artistic, quietly funny, and often the voice of reason."
#     ),
#     "Andy": (
#         "You are Andy Bernard, a salesman at Dunder Mifflin. "
#         "You went to Cornell (which you mention constantly), love a cappella singing, "
#         "and are eager to impress everyone."
#     ),
#     "Ryan": (
#         "You are Ryan Howard, who started as a temp at Dunder Mifflin. "
#         "You are self-absorbed, ambitious, and constantly reinventing your image."
#     ),
#     "Kevin": (
#         "You are Kevin Malone, an accountant at Dunder Mifflin. "
#         "You are simple-minded, lovable, passionate about food, poker, and your band Scrantonicity."
#     ),
#     "Angela": (
#         "You are Angela Martin, head of accounting at Dunder Mifflin. "
#         "You are uptight, judgmental, and obsessively devoted to your cats."
#     ),
#     "Sheldon": (
#         "You are Sheldon Cooper, a theoretical physicist at Caltech with an IQ of 187. "
#         "You lack social awareness, follow rigid routines, and have a designated spot on the couch. "
#         "You believe you are intellectually superior to everyone. "
#         "You only say 'Bazinga!' on rare occasions — specifically when you reveal that a previous statement was a deliberate deception or joke. "
#         "Never use 'Bazinga!' as a general exclamation, never end a response with it, and never use it more than once per conversation."
#     ),
#     "Leonard": (
#         "You are Leonard Hofstadter, an experimental physicist at Caltech. "
#         "You are insecure, romantic, and constantly caught between Sheldon's demands "
#         "and trying to have a normal life."
#     ),
#     "Penny": (
#         "You are Penny, an aspiring actress working as a waitress at The Cheesecake Factory. "
#         "You are street-smart, fun, and perpetually bemused by your genius neighbors."
#     ),
#     "Howard": (
#         "You are Howard Wolowitz, an aerospace engineer at Caltech and NASA astronaut. "
#         "You are a self-proclaimed ladies' man and a mama's boy who still lives with his mother."
#     ),
#     "Raj": (
#         "You are Raj Koothrappali, an astrophysicist at Caltech from New Delhi. "
#         "You cannot speak to women unless you have had alcohol. "
#         "You are deeply sentimental, romantic, and love Bollywood."
#     ),
#     "Bernadette": (
#         "You are Bernadette Rostenkowski-Wolowitz, a microbiologist and Howard's wife. "
#         "You have a sweet, high-pitched voice that belies a fierce, no-nonsense personality."
#     ),
#     "Amy": (
#         "You are Amy Farrah Fowler, a neurobiologist and Sheldon's girlfriend. "
#         "You desperately crave normal friendships despite your painfully awkward academic demeanor."
#     ),
# }

# SHOW_MAP: Dict[str, str] = {
#     "Michael": "The Office", "Dwight": "The Office", "Jim": "The Office",
#     "Pam": "The Office", "Andy": "The Office", "Ryan": "The Office",
#     "Kevin": "The Office", "Angela": "The Office",
#     "Sheldon": "The Big Bang Theory", "Leonard": "The Big Bang Theory",
#     "Penny": "The Big Bang Theory", "Howard": "The Big Bang Theory",
#     "Raj": "The Big Bang Theory", "Bernadette": "The Big Bang Theory",
#     "Amy": "The Big Bang Theory",
# }

# CHROMA_SHOW_KEY: Dict[str, str] = {
#     "The Office": "the_office",
#     "The Big Bang Theory": "big_bang_theory",
# }

# # ---------------------------------------------------------------------------
# # Globals set at startup
# # ---------------------------------------------------------------------------

# model: Optional[AutoModelForCausalLM] = None
# tokenizer: Optional[AutoTokenizer] = None
# chroma_col = None

# # ---------------------------------------------------------------------------
# # Model loading
# # ---------------------------------------------------------------------------

# def _detect_device() -> str:
#     if torch.cuda.is_available():
#         return "cuda"
#     if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
#         return "mps"
#     return "cpu"


# def load_model(model_id: str, adapter_path: Optional[str], load_in_4bit: bool = False) -> None:
#     global model, tokenizer

#     device = _detect_device()
#     print(f"Device: {device}")

#     tok_source = adapter_path if (adapter_path and os.path.exists(adapter_path)) else model_id
#     print(f"Loading tokenizer from: {tok_source}")
#     tokenizer = AutoTokenizer.from_pretrained(tok_source)
#     tokenizer.pad_token = tokenizer.eos_token

#     print(f"Loading base model: {model_id}")

#     if load_in_4bit:
#         if device != "cuda":
#             print("WARNING: --load-in-4bit requires CUDA. Falling back to bf16.")
#             load_in_4bit = False

#     if load_in_4bit:
#         from transformers import BitsAndBytesConfig
#         bnb_config = BitsAndBytesConfig(
#             load_in_4bit=True,
#             bnb_4bit_quant_type="nf4",
#             bnb_4bit_use_double_quant=True,
#             bnb_4bit_compute_dtype=torch.bfloat16,
#         )
#         base = AutoModelForCausalLM.from_pretrained(
#             model_id,
#             quantization_config=bnb_config,
#             device_map="auto",
#         )
#         print("Loaded in 4-bit (NF4).")
#     else:
#         dtype = torch.float16 if device == "mps" else torch.bfloat16
#         base = AutoModelForCausalLM.from_pretrained(
#             model_id,
#             torch_dtype=dtype,
#             device_map="auto" if device == "cuda" else None,
#         )
#         if device != "cuda":
#             base = base.to(device)
#         print(f"Loaded in {dtype}, device={device}.")

#     if adapter_path and os.path.exists(os.path.join(adapter_path, "adapter_config.json")):
#         from peft import PeftModel  # lazy import — avoids heavy torch.distributed.tensor chain
#         print(f"Loading LoRA adapters from: {adapter_path}")
#         model = PeftModel.from_pretrained(base, adapter_path)
#         print("Fine-tuned model loaded.")
#     else:
#         print("No LoRA adapters found — using base model with RAG prompting.")
#         model = base

#     model.eval()
#     print("Model ready.\n")

# # ---------------------------------------------------------------------------
# # RAG helpers
# # ---------------------------------------------------------------------------

# def _cosine_sim(a: List[float], b: List[float]) -> float:
#     """Cosine similarity between two embedding vectors."""
#     a_arr = np.array(a, dtype=np.float32)
#     b_arr = np.array(b, dtype=np.float32)
#     denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr))
#     return float(np.dot(a_arr, b_arr) / denom) if denom > 0 else 0.0


# def _mmr_select(
#     docs: List[str],
#     distances: List[float],
#     embeddings: List[List[float]],
#     n_select: int,
#     lambda_mult: float = 0.6,
# ) -> List[str]:
#     """Maximal Marginal Relevance selection.

#     Picks n_select items that balance:
#       - Relevance  (low distance to query)
#       - Diversity  (low cosine similarity to already-selected items)

#     lambda_mult=1.0 → pure relevance, 0.0 → pure diversity.
#     """
#     if len(docs) <= n_select:
#         return docs

#     # Normalise distances to [0, 1] so they're on the same scale as cosine sim
#     max_d = max(distances) or 1.0
#     norm_dists = [d / max_d for d in distances]

#     selected: List[int] = [0]          # always start with the most relevant doc
#     remaining: List[int] = list(range(1, len(docs)))

#     while len(selected) < n_select and remaining:
#         scores = []
#         for idx in remaining:
#             relevance  = 1.0 - norm_dists[idx]
#             redundancy = max(_cosine_sim(embeddings[idx], embeddings[s]) for s in selected)
#             scores.append((lambda_mult * relevance - (1 - lambda_mult) * redundancy, idx))
#         best = max(scores, key=lambda x: x[0])[1]
#         selected.append(best)
#         remaining.remove(best)

#     return [docs[i] for i in selected]


# # ---------------------------------------------------------------------------
# # RAG — main retrieval function
# # ---------------------------------------------------------------------------

# def retrieve_scene_examples(character: str, query: str, n_results: int = 4) -> str:
#     """Two-pass RAG pipeline:

#     Pass 1 — Canon scenes (doc_type="canon"):
#         Full scenes where the character appears, filtered directly at the DB level
#         using the has_<name> boolean flag stored in metadata.
#         Returns 3 scenes (MMR-selected from top 20).

#     Pass 2 — Style exemplars (doc_type="exemplar"):
#         Short Sheldon-line + context snippets that anchor voice without injecting
#         a full scene of other characters' dialogue.
#         Returns 1 exemplar (MMR-selected from top 10).

#     Both passes use has_<character> = True as a DB-level filter — no Python
#     post-filtering needed because build_chromadb.py stores individual boolean
#     flags per main character in every document's metadata.
#     """
#     CANON_POOL    = 20
#     EXEMPLAR_POOL = 10
#     CANON_N       = n_results - 1   # 3 canon scenes
#     EXEMPLAR_N    = 1               # 1 style exemplar

#     show        = SHOW_MAP.get(character, "")
#     chroma_show = CHROMA_SHOW_KEY.get(show, "")
#     char_key    = f"has_{character.lower()}"  # e.g. "has_sheldon"

#     def _query(doc_type: str, pool: int):
#         where = {
#             "$and": [
#                 {"show":     {"$eq": chroma_show}},
#                 {"doc_type": {"$eq": doc_type}},
#                 {char_key:   {"$eq": True}},
#             ]
#         }
#         try:
#             r = chroma_col.query(
#                 query_texts=[query],
#                 n_results=pool,
#                 include=["documents", "metadatas", "distances", "embeddings"],
#                 where=where,
#             )
#             return (
#                 r["documents"][0], r["metadatas"][0],
#                 r["distances"][0], r["embeddings"][0],
#             )
#         except Exception as exc:
#             print(f"[RAG] {doc_type} query error: {exc}")
#             return [], [], [], []

#     # ── Pass 1: canon scenes ─────────────────────────────────────────────────
#     c_docs, c_metas, c_dists, c_embs = _query("canon", CANON_POOL)

#     seen: set = set()
#     canon_docs, canon_dists, canon_embs = [], [], []
#     for doc, meta, dist, emb in zip(c_docs, c_metas, c_dists, c_embs):
#         key = (meta.get("season"), meta.get("episode"), meta.get("scene"))
#         if key in seen:
#             continue
#         seen.add(key)
#         canon_docs.append(doc)
#         canon_dists.append(dist)
#         canon_embs.append(emb)

#     canon_selected = _mmr_select(canon_docs, canon_dists, canon_embs, n_select=CANON_N)

#     # ── Pass 2: style exemplars ──────────────────────────────────────────────
#     e_docs, e_metas, e_dists, e_embs = _query("exemplar", EXEMPLAR_POOL)

#     ex_seen: set = set()
#     ex_docs, ex_dists, ex_embs = [], [], []
#     for doc, meta, dist, emb in zip(e_docs, e_metas, e_dists, e_embs):
#         key = (meta.get("season"), meta.get("episode"), meta.get("scene"), meta.get("turn_idx"))
#         if key in ex_seen:
#             continue
#         ex_seen.add(key)
#         ex_docs.append(doc)
#         ex_dists.append(dist)
#         ex_embs.append(emb)

#     exemplar_selected = _mmr_select(ex_docs, ex_dists, ex_embs, n_select=EXEMPLAR_N)

#     print(
#         f"[RAG] {character}: "
#         f"canon pool={len(c_docs)} → MMR={len(canon_selected)} | "
#         f"exemplar pool={len(e_docs)} → MMR={len(exemplar_selected)}"
#     )

#     selected = canon_selected + exemplar_selected
#     if not selected:
#         print(f"[RAG] No scenes found for character='{character}'")
#         return ""

#     return "\n\n---\n\n".join(selected)

# # ---------------------------------------------------------------------------
# # Generation
# # ---------------------------------------------------------------------------

# def _run_generation(
#     input_ids: torch.Tensor,
#     attention_mask: torch.Tensor,
#     streamer: TextIteratorStreamer,
# ) -> None:
#     model.generate(
#         input_ids=input_ids,
#         attention_mask=attention_mask,
#         streamer=streamer,
#         max_new_tokens=300,
#         temperature=0.8,
#         top_p=0.9,
#         do_sample=True,
#         repetition_penalty=1.15,
#         pad_token_id=tokenizer.eos_token_id,
#     )


# async def stream_reply(
#     ws: WebSocket,
#     character: str,
#     history: List[Dict],
#     user_msg: str,
# ) -> str:
#     """Build prompt, generate, and stream tokens to the WebSocket client."""
#     show = SHOW_MAP.get(character, "a TV show")
#     desc = CHARACTER_DESCRIPTIONS.get(character, f"You are {character}.")

#     # RAG context
#     scene_block = await asyncio.to_thread(retrieve_scene_examples, character, user_msg)
#     rag_section = (
#         f"\n\nHere are some example scenes featuring {character} to help you stay in character:\n"
#         f"{scene_block}"
#         if scene_block
#         else ""
#     )

#     system = (
#         f"{desc} Stay fully in character as {character} from {show}. "
#         f"Keep responses concise and natural — as if speaking in a real conversation.{rag_section}"
#     )

#     messages = [{"role": "system", "content": system}]
#     messages.extend(history)
#     messages.append({"role": "user", "content": user_msg})

#     # apply_chat_template returns a BatchEncoding (dict-like) for Qwen2.5,
#     # not a raw tensor — so we must use return_dict=True and extract explicitly.
#     tokenized = tokenizer.apply_chat_template(
#         messages,
#         add_generation_prompt=True,
#         return_tensors="pt",
#         return_dict=True,
#     )
#     input_ids      = tokenized["input_ids"].to(model.device)
#     attention_mask = tokenized["attention_mask"].to(model.device)

#     streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
#     thread = Thread(target=_run_generation, args=(input_ids, attention_mask, streamer), daemon=True)
#     thread.start()

#     # Drain the streamer; yield control to the event loop between tokens
#     full_response = ""
#     streamer_iter = iter(streamer)
#     loop = asyncio.get_event_loop()

#     while True:
#         token: Optional[str] = await loop.run_in_executor(None, next, streamer_iter, None)
#         if token is None:
#             break
#         full_response += token
#         await ws.send_text(json.dumps({"type": "token", "content": token}))

#     await ws.send_text(json.dumps({"type": "done"}))
#     return full_response

# # ---------------------------------------------------------------------------
# # FastAPI app
# # ---------------------------------------------------------------------------

# app = FastAPI(title="TV Character Chatbot")

# # Serve static files (index.html etc.) from ./static
# static_dir = Path(__file__).parent / "static"
# static_dir.mkdir(exist_ok=True)
# app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# @app.get("/", response_class=HTMLResponse)
# async def index():
#     html_path = static_dir / "index.html"
#     if not html_path.exists():
#         return HTMLResponse("<h1>index.html not found in ./static/</h1>", status_code=404)
#     return HTMLResponse(html_path.read_text())


# @app.get("/characters")
# async def list_characters():
#     grouped = {}
#     for char, show in SHOW_MAP.items():
#         grouped.setdefault(show, []).append(char)
#     return grouped


# @app.websocket("/ws")
# async def websocket_endpoint(ws: WebSocket):
#     await ws.accept()
#     history: List[Dict] = []
#     character = "Sheldon"

#     try:
#         while True:
#             raw = await ws.receive_text()
#             payload = json.loads(raw)

#             # --- Character selection ---
#             if payload.get("type") == "set_character":
#                 character = payload.get("character", character)
#                 history = []  # fresh conversation per character
#                 await ws.send_text(json.dumps({"type": "character_set", "character": character}))
#                 continue

#             # --- Chat message ---
#             user_msg = payload.get("message", "").strip()
#             if not user_msg:
#                 continue

#             full_response = await stream_reply(ws, character, history, user_msg)

#             # Maintain rolling history (last 10 turns = 20 messages)
#             history.append({"role": "user", "content": user_msg})
#             history.append({"role": "assistant", "content": full_response})
#             if len(history) > 20:
#                 history = history[-20:]

#     except WebSocketDisconnect:
#         pass
#     except Exception as exc:
#         try:
#             await ws.send_text(json.dumps({"type": "error", "content": str(exc)}))
#         except Exception:
#             pass

# # ---------------------------------------------------------------------------
# # Entry point
# # ---------------------------------------------------------------------------

# def main() -> None:
#     parser = argparse.ArgumentParser(description="TV Character Chatbot Server")
#     parser.add_argument(
#         "--model-id", default="HuggingFaceTB/SmolLM2-1.7B-Instruct",
#         help="HuggingFace model ID (default: HuggingFaceTB/SmolLM2-1.7B-Instruct)"
#     )
#     parser.add_argument(
#         "--adapter-path", default="./finetuned_model",
#         help="Path to LoRA adapters from finetune.ipynb (optional)"
#     )
#     parser.add_argument("--persist-dir", default="./chroma_db")
#     parser.add_argument("--collection", default="tv_scenes")
#     parser.add_argument("--host", default="0.0.0.0")
#     parser.add_argument("--port", type=int, default=8000)
#     parser.add_argument(
#         "--load-in-4bit", action="store_true",
#         help="Load model in 4-bit NF4 quantisation for faster inference (CUDA only)",
#     )
#     args = parser.parse_args()

#     global chroma_col
#     print(f"Connecting to ChromaDB at {args.persist_dir}...")
#     chroma_client = chromadb.PersistentClient(path=args.persist_dir)
#     chroma_col = chroma_client.get_collection(args.collection)
#     print(f"  Collection '{args.collection}': {chroma_col.count()} docs\n")

#     load_model(args.model_id, args.adapter_path, args.load_in_4bit)

#     print(f"Starting server at http://{args.host}:{args.port}")
#     uvicorn.run(app, host=args.host, port=args.port)


# if __name__ == "__main__":
#     main()
