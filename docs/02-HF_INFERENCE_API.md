# Context: Hugging Face Inference API Integration

This document describes the changes made to the TV Character Chatbot so it can use the **Hugging Face Inference API** instead of loading the 7B model locally. Use it to onboard another agent, hand off the project, or understand what was implemented.

---

## Why This Was Done

- The default setup loads **Qwen/Qwen2.5-7B-Instruct** (~15.2 GB) on the host machine.
- The user's machine couldn't handle that download/size, so we added a path that runs inference on Hugging Face's servers (no local model).

---

## What Changed (Summary)

| Area | Change |
|------|--------|
| **Secrets** | `.env` with `HF_TOKEN`; `.env.example` documents it; `.env` already in `.gitignore`. |
| **Dependencies** | `python-dotenv`, `huggingface_hub` added to `requirements.txt` (Chatbot server section). |
| **Server** | New `--use-inference-api` flag; when set, no local model load; streaming goes through HF Inference API. |

---

## Files Touched

- **`.env`** — Created; contains `HF_TOKEN=...` (do not commit; already gitignored).
- **`.env.example`** — Updated with `HF_TOKEN=` and a short note + link to create a token.
- **`requirements.txt`** — Under "Chatbot server": `python-dotenv>=1.0.0`, `huggingface_hub>=0.20.0`.
- **`chatbot_server.py`** — All logic changes (see below).

---

## Changes in `chatbot_server.py`

### 1. Docstring and usage

- Docstring now documents: `python chatbot_server.py --use-inference-api` for API mode.

### 2. Globals (around line 134)

- **`use_inference_api`** (bool) — True when running with `--use-inference-api`.
- **`hf_inference_model_id`** (str) — Model ID used for the API (default `Qwen/Qwen2.5-7B-Instruct`; can be overridden with `--model-id`).

### 3. New helper: `_stream_reply_via_inference_api(ws, messages)`

- **Role:** Stream the reply using the Hugging Face Inference API only (no local model).
- **Inputs:** WebSocket `ws` and the full `messages` list (system + history + user) already built by `stream_reply`.
- **Flow:** Reads `HF_TOKEN` from the environment; creates `AsyncInferenceClient`; streams via `client.chat.completions.create(..., stream=True)`; sends `{"type": "token", "content": ...}` and `{"type": "done"}`. Same WebSocket contract as local path.

### 4. `stream_reply()`

- If `use_inference_api`: call `_stream_reply_via_inference_api(ws, messages)` and return. Else: existing local path.

### 5. `main()`

- `load_dotenv()` at start; `--use-inference-api` flag; when set, skip `load_model()`, require `HF_TOKEN`.

---

## How to Run

**Local model (original):**
```bash
python chatbot_server.py
```

**Hugging Face Inference API (no local 7B download):**
```bash
python chatbot_server.py --use-inference-api
```

Chromadb and RAG are unchanged; only the LLM call is either local or via the API.
