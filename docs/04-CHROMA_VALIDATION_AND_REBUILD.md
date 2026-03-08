# Handoff: Chroma DB Validation and Rebuild

**Purpose:** Validate the TV Character Chatbot's ChromaDB state and perform a full rebuild so both **The Office** and **The Big Bang Theory** are ingested and RAG works for all characters (e.g. Sheldon, Michael).

---

## Task list (summary)

| # | Task | Command / action |
|---|------|------------------|
| 1 | Validate data files exist and are usable | Check `data/TheOffice.csv`, `data/TBBTcleaned.csv` |
| 2 | (Optional) Inspect current Chroma collection | Run `inspect_chromadb.py` |
| 3 | Rebuild Chroma with both shows | Run `build_chromadb.py --reset` from project root |
| 4 | Verify rebuild | Re-run `inspect_chromadb.py`; confirm both shows and character coverage |
| 5 | (Optional) Run retrieval funnel + eval | Run `run_eval.py` |

---

## 1. Validate data files

**Location:** `TV-character-chatbot/data/` (gitignored).

**Required files:** `TheOffice.csv` (columns: season, episode, title, scene, speaker, line); `TBBTcleaned.csv` (season, episode, character, dialogue, scene_id or episode_title).

---

## 2. (Optional) Inspect current Chroma collection

```bash
python3 inspect_chromadb.py
```

Defaults: `--persist-dir ./chroma_db`, `--collection tv_scenes`. Check total docs and per-show counts; if `big_bang_theory: 0 scenes`, rebuild (step 3).

---

## 3. Rebuild Chroma with both shows

```bash
cd /path/to/TV-character-chatbot
python3 build_chromadb.py --reset
```

Use `--reset` for a clean rebuild. Both `the_office` and `big_bang_theory` should have non-zero scenes in the summary.

---

## 4. Verify rebuild

Re-run `inspect_chromadb.py`, then start the server and test in the UI. You should not see "[RAG] No scenes found" for Sheldon or Office characters.

---

## 5. (Optional) Retrieval eval

```bash
python3 run_eval.py --n-results 8
```

---

## Reference: key paths and defaults

| Item | Path / value |
|------|----------------|
| Project root | `TV-character-chatbot/` |
| Data CSVs | `data/TheOffice.csv`, `data/TBBTcleaned.csv` |
| Chroma persist dir | `./chroma_db` |
| Collection name | `tv_scenes` |
