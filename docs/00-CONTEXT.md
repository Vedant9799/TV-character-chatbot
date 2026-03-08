# TV Character Chatbot — Project Context

**All project context and design docs live in this `docs/` folder. This file is the main overview.**

## What the project is

A **TV character chatbot** that lets users chat with characters from **The Office** and **The Big Bang Theory** (e.g. Michael Scott, Sheldon Cooper). The app uses **RAG over scene-level dialogue**: relevant scenes are retrieved from a vector store and injected as few-shot examples into the system prompt, and a local LLM (Qwen2.5-7B-Instruct) or the Hugging Face Inference API generates in-character replies. The UI is served by a FastAPI + WebSocket server and streams tokens to the frontend.

## Data

- **Sources:** CSV files in `data/` (gitignored):
  - `TheOffice.csv` — The Office dialogue (columns: season, episode, title, scene, speaker, line).
  - `TBBTcleaned.csv` — The Big Bang Theory dialogue (columns: season, episode, character, dialogue, scene_id).
- **Ingestion:** [build_chromadb.py](../build_chromadb.py) parses these CSVs into scene-level documents and upserts them into a ChromaDB collection in `chroma_db/` (gitignored).
- **Embeddings:** BAAI/bge-large-en-v1.5 via ChromaDB’s `SentenceTransformerEmbeddingFunction`. The collection uses cosine distance.

## RAG pipeline

1. **Query:** `build_retrieval_query()` combines the current user message with the last 6 messages of conversation (history) into a single retrieval query for context-aware search.
2. **ChromaDB:** Query is run against the collection with a show-level filter (the_office / big_bang_theory). Top 60 results (`CANDIDATE_POOL`) are fetched with embeddings. When the query contains a topic keyword (downsizing, bazinga, dundie, dundies, scranton, couch, spot, etc.), `where_document` restricts results to docs containing that term.
3. **Post-Chroma filtering:** Results are filtered in Python to keep only scenes where the selected character appears (`characters_present`), and deduplicated by (season, episode, scene).
4. **Scoring adjustments (calculations):**
   - **Character line fraction:** 25% distance reduction for scenes where the target character has more lines (better voice examples): `adjusted_dist = dist * (1.0 - 0.25 * frac)`.
   - **Keyword boost:** 35% relevance boost when query terms (length ≥ 4, non-stop) appear in the doc: `adjusted_dist *= 0.65`.
5. **Selection:** Results are sorted by adjusted distance, then either **top-k** or **MMR** picks 8 scenes. The live server uses MMR. Optional **hybrid** strategy combines BM25 + Chroma + RRF.
6. **Prompt:** Retrieved scenes are formatted as few-shot examples and appended to the system prompt. The show is set in 2005–2013; the model is instructed to avoid references outside that era unless the examples include them.
7. **Generation:** Qwen2.5-7B-Instruct (local or HF Inference API) generates a reply; tokens are streamed to the client over WebSocket.

## Loggers and debug

- **Retrieval debug logger:** Enable with `--retrieval-debug` (chatbot) or `RETRIEVAL_DEBUG=1` or `--debug` (run_eval). Writes JSONL to `retrieval_debug.log` (in project root) with input, funnel counts, scoring metrics (raw_dist, line_frac, keyword_boost, adjusted_dist), candidates, and selected doc_ids. See [01-RETRIEVAL_DESIGN.md](01-RETRIEVAL_DESIGN.md).

## Docs in this folder

| File | Description |
|------|-------------|
| [00-CONTEXT.md](00-CONTEXT.md) | This file — main project overview and RAG summary. |
| [01-RETRIEVAL_DESIGN.md](01-RETRIEVAL_DESIGN.md) | Retrieval pipeline, scoring, topic keywords, strategies, debug logger. |
| [02-HF_INFERENCE_API.md](02-HF_INFERENCE_API.md) | Hugging Face Inference API integration (no local model). |
| [03-RAG_CHARACTER_DESIGN.md](03-RAG_CHARACTER_DESIGN.md) | RAG design for character voice; character line fraction rationale. |
| [04-CHROMA_VALIDATION_AND_REBUILD.md](04-CHROMA_VALIDATION_AND_REBUILD.md) | How to validate data, rebuild Chroma, and verify both shows. |

## How to run

1. **Build ChromaDB** (one-time; requires CSVs in `data/`):
   ```bash
   python build_chromadb.py --reset
   ```
2. **Start the chatbot server:**
   ```bash
   python chatbot_server.py
   ```
   Or with HF Inference API (no local model): `python chatbot_server.py --use-inference-api`  
   With retrieval debug: `python chatbot_server.py --retrieval-debug`
3. **Run retrieval evaluation:**
   ```bash
   python run_eval.py --n-results 8
   ```
   Optional: `--eval-set ./eval_set.json`, `--persist-dir ./chroma_db`, `--collection tv_scenes`, `--debug` for retrieval logs.

The app is served at http://localhost:8000/; the WebSocket endpoint is `/ws`.
