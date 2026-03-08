# RAG design for character voice (e.g. Michael)

## CSV inspection summary

**TheOffice.csv**

- ~54.6k rows (one per line of dialogue). Columns: `season`, `episode`, `title`, `scene`, `speaker`, `line`.
- **Michael** has the most lines (~10.7k); then Dwight, Jim, Pam, Andy, etc.
- Michael appears in **2,780 scenes**. In those scenes he has on average **58%** of the lines (median 50%); in **65%** of his scenes he has ≥50% of the dialogue.
- Scene size: 1–74 lines per scene, median 4, p90 16.

So many scenes are mixed dialogue; "what Michael wants to say" is better represented when we **prefer scenes where Michael (or the selected character) has a larger share of the lines**.

---

## Design choices we use

| Choice | What we do | Why |
|--------|------------|-----|
| **More few-shot scenes** | Use **8** scenes in the prompt (was 4). | Richer character voice; more examples of how they talk. |
| **Character line fraction** | At **build** time we store per-scene `character_line_fraction` (e.g. `{"Michael": 0.6, "Jim": 0.3}`). At **retrieval** we slightly boost scenes where the selected character has a higher fraction of the lines. | Ensures we prefer "Michael-heavy" scenes over "Michael is there but mostly others talk". |
| **MMR** | Maximal Marginal Relevance over the (optionally boosted) candidates. | Balances relevance and diversity so we don't get 8 nearly identical scenes. |
| **Larger candidate pool** | Fetch 60 candidates from Chroma, then filter/dedup and select 8. | Enough headroom after character filter and dedup. |

---

## What you need to do

- **Rebuild Chroma** so new docs include `character_line_fraction`:
  ```bash
  python3 build_chromadb.py --reset
  ```
- Existing collections without this field still work; we treat missing fraction as 0.5 (no boost).

---

## Optional future tweaks

- **Per-character n_results:** Use more scenes (e.g. 10) for leads like Michael/Dwight who have the most data.
- **Stronger boost:** In `retrieval.py`, increase the `0.25` in `(1.0 - 0.25 * frac)` to prefer character-heavy scenes more aggressively.
- **TBBT:** Same logic applies; BBT CSVs now also get `character_line_fraction` at build time.
