"""
TV Character Profiler — Sheldon, Leonard, Michael, Dwight
=========================================================
Analyzes dialogue data from a merged CSV (TBBT + The Office) to build
character profiles automatically.

Two stages:
  1. Statistical analysis (pure Python) — speech patterns, relationships,
     vocabulary, tone indicators, seasonal evolution, sample dialogues
  2. LLM synthesis (Ollama) — generates concise CHARACTER_DESCRIPTIONS strings
     (2nd-person, 3–5 sentences, no headings/bullets) from the analysis

Requires:  merged_tv_dialogues.csv  (columns: show, season, episode, scene, character, dialogue)

Usage:
  python character_profiler.py                  # Stage 1 only  → character_profiles.json
  python character_profiler.py --synthesize     # Stage 1 + 2   → also writes character_profiles.json
  python character_profiler.py --synthesize --model mistral  # Use a specific Ollama model
"""

import json
import re
from collections import Counter, defaultdict
import pandas as pd
import requests

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
CSV_PATH              = "merged_tv_dialogues.csv"
OUTPUT_PATH           = "character_profiles.json"
STATS_OUTPUT_PATH     = "character_stats.json"

MAIN_CHARACTERS = ["Sheldon", "Leonard", "Michael", "Dwight"]

SHOW_MAP = {
    "Sheldon": "The Big Bang Theory",
    "Leonard": "The Big Bang Theory",
    "Michael": "The Office",
    "Dwight":  "The Office",
}

# Entries to treat as non-character in both shows
SKIP_CHARACTERS = frozenset({
    "Scene", "Stage Direction", "Stage Directions",
    "All", "Both", "Everyone", "Everyone:", "Narrator",
    "Group", "Crowd", "Together", "Various", "Others",
    "Office", "Employees", "Voicemail",
})

OLLAMA_URL          = "http://localhost:11434/api/generate"
DEFAULT_OLLAMA_MODEL = "llama3"


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
def load_data(path: str) -> pd.DataFrame:
    """Load merged_tv_dialogues.csv and compute helper columns.

    Expected schema: show, season, episode, scene, character, dialogue
    A globally-unique scene_key is derived from those four fields so
    the rest of the pipeline can group and compare scenes without
    assuming any column is globally unique on its own.
    (TBBT 'scene' is per-episode 0–21; Office 'scene' is cumulative 1–8157.)
    """
    df = pd.read_csv(path)
    # Validate expected columns
    required = {"show", "season", "episode", "scene", "character", "dialogue"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"{path} is missing columns: {sorted(missing)}\n"
            "Expected merged_tv_dialogues.csv with columns: "
            "show, season, episode, scene, character, dialogue"
        )
    # Drop non-character rows
    df = df[~df["character"].isin(SKIP_CHARACTERS)].copy()
    df["dialogue"] = df["dialogue"].fillna("").astype(str)
    df = df[df["character"].str.strip() != ""]
    df = df[df["dialogue"].str.strip() != ""]
    df["word_count"] = df["dialogue"].str.split().str.len()
    df["char_count"]  = df["dialogue"].str.len()
    # Build a globally-unique scene key: e.g. "the_big_bang_theory_s01e01_sc0001"
    df["scene_key"] = (
        df["show"].str.lower().str.replace(" ", "_", regex=False)
        + "_s" + df["season"].astype(str).str.zfill(2)
        + "e"  + df["episode"].astype(str).str.zfill(2)
        + "_sc"+ df["scene"].astype(str).str.zfill(5)
    )
    df = df.reset_index(drop=True)
    return df


# ─────────────────────────────────────────────
# 1. SPEECH PATTERN ANALYSIS
# ─────────────────────────────────────────────
def analyze_speech_patterns(df: pd.DataFrame, character: str) -> dict:
    """Extract quantitative speech patterns for a character."""
    char_df = df[df["character"] == character]
    all_text = " ".join(char_df["dialogue"].tolist()).lower()
    words = all_text.split()

    stats: dict = {
        "total_lines": len(char_df),
        "avg_words_per_line": round(char_df["word_count"].mean(), 1),
        "median_words_per_line": round(char_df["word_count"].median(), 1),
        "max_words_in_line": int(char_df["word_count"].max()),
        "total_words": len(words),
    }

    unique_words = set(words)
    stats["unique_words"] = len(unique_words)
    stats["vocabulary_richness"] = round(len(unique_words) / max(len(words), 1), 4)
    stats["avg_char_per_line"] = round(char_df["char_count"].mean(), 1)
    stats["question_ratio"] = round(
        char_df["dialogue"].str.contains(r"\?").sum() / max(len(char_df), 1), 3
    )
    stats["exclamation_ratio"] = round(
        char_df["dialogue"].str.contains(r"!").sum() / max(len(char_df), 1), 3
    )
    return stats


# ─────────────────────────────────────────────
# 2. CATCHPHRASES & DISTINCTIVE VOCABULARY
# ─────────────────────────────────────────────
def find_distinctive_phrases(df: pd.DataFrame, character: str, top_n: int = 30) -> dict:
    """
    Find words/phrases distinctively used by this character vs others *from the
    same show*.  Comparing within the same show avoids inflating scores with
    vocabulary differences that are just TBBT-vs-Office genre gaps.
    """
    char_df = df[df["character"] == character]
    char_show = char_df["show"].iloc[0] if len(char_df) > 0 else None

    # Compare against all OTHER characters from the same show
    if char_show:
        other_df = df[(df["show"] == char_show) & (df["character"] != character)]
    else:
        other_df = df[df["character"] != character]

    char_text  = " ".join(char_df["dialogue"].tolist()).lower()
    other_text = " ".join(other_df["dialogue"].tolist()).lower()

    char_words  = Counter(char_text.split())
    other_words = Counter(other_text.split())

    char_total  = sum(char_words.values())
    other_total = sum(other_words.values())

    # TF-IDF-like distinctiveness score
    distinctive: dict = {}
    for word, count in char_words.items():
        if count < 5 or len(word) < 3:
            continue
        char_freq  = count / char_total
        other_freq = (other_words.get(word, 0) + 1) / other_total
        distinctive[word] = round(char_freq / other_freq, 2)

    top_distinctive = sorted(distinctive.items(), key=lambda x: -x[1])[:top_n]

    # Repeated n-grams (2–4 words)
    ngram_counts: dict = defaultdict(int)
    for line in char_df["dialogue"].tolist():
        line_lower = line.lower().strip()
        wds = line_lower.split()
        for n in range(2, 5):
            for i in range(len(wds) - n + 1):
                ngram_counts[" ".join(wds[i : i + n])] += 1

    repeated_phrases = {k: v for k, v in ngram_counts.items() if v >= 5}
    phrase_scores    = {k: v * len(k.split()) for k, v in repeated_phrases.items()}
    top_phrases      = sorted(phrase_scores.items(), key=lambda x: -x[1])[:20]

    # Verbatim catchphrases (short lines repeated ≥ 3 times)
    short_lines = char_df[char_df["word_count"] <= 6]["dialogue"].str.lower().str.strip()
    catchphrase_counts = short_lines.value_counts()
    catchphrases = catchphrase_counts[catchphrase_counts >= 3].head(15).to_dict()

    return {
        "distinctive_words": dict(top_distinctive),
        "repeated_phrases":  dict(top_phrases[:15]),
        "catchphrases":      catchphrases,
    }


# ─────────────────────────────────────────────
# 3. RELATIONSHIP ANALYSIS
# ─────────────────────────────────────────────
def analyze_relationships(df: pd.DataFrame, character: str) -> dict:
    """
    Analyse co-occurrence and conversational adjacency.
    Uses scene_key (globally unique per scene in the merged CSV) for grouping.
    """
    char_scenes = df[df["character"] == character]["scene_key"].drop_duplicates()

    co_occurrences: Counter = Counter()
    for scene_key in char_scenes:
        scene_chars = df[
            (df["scene_key"] == scene_key)
            & (~df["character"].isin(SKIP_CHARACTERS))
            & (df["character"] != character)
        ]["character"].unique()
        for other in scene_chars:
            co_occurrences[other] += 1

    # Conversational turn adjacency — only count within the same scene_key
    char_indices    = df[df["character"] == character].index
    responds_to_me: Counter = Counter()
    i_respond_to:   Counter = Counter()

    for idx in char_indices:
        curr_scene = df.loc[idx, "scene_key"]
        if idx + 1 in df.index and df.loc[idx + 1, "scene_key"] == curr_scene:
            next_char = df.loc[idx + 1, "character"]
            if next_char not in SKIP_CHARACTERS and next_char != character:
                responds_to_me[next_char] += 1
        if idx - 1 in df.index and df.loc[idx - 1, "scene_key"] == curr_scene:
            prev_char = df.loc[idx - 1, "character"]
            if prev_char not in SKIP_CHARACTERS and prev_char != character:
                i_respond_to[prev_char] += 1

    return {
        "scenes_together":     dict(co_occurrences.most_common(10)),
        "most_responds_to_me": dict(responds_to_me.most_common(7)),
        "i_most_respond_to":   dict(i_respond_to.most_common(7)),
    }


# ─────────────────────────────────────────────
# 4. EMOTIONAL TONE INDICATORS
# ─────────────────────────────────────────────
def analyze_tone(df: pd.DataFrame, character: str) -> dict:
    """
    Heuristic tone analysis with patterns relevant to both TBBT and The Office
    characters.
    """
    char_df  = df[df["character"] == character]
    dialogues = char_df["dialogue"].tolist()
    total     = max(len(dialogues), 1)

    patterns = {
        # TBBT-skewed
        "scientific_technical": (
            r"\b(theorem|hypothesis|equation|quantum|physics|experiment|molecule"
            r"|algorithm|data|variable|coefficient|proton|electron|neutron"
            r"|paradigm|photon|theoretical|empirical|string theory)\b"
        ),
        # Office-skewed (Michael)
        "management_speak": (
            r"\b(synergy|leverage|team player|proactive|mission statement"
            r"|best practices|paradigm shift|incentivize|strategize|morale"
            r"|that's what she said|world's best boss|regional manager"
            r"|motivate|teamwork|fun workplace)\b"
        ),
        # Office-skewed (Dwight)
        "authority_rank": (
            r"\b(assistant|regional manager|superior|rank|authority|protocol"
            r"|rule|regulation|order|command|i outrank|pursuant to|duty"
            r"|second in command|assistant to the|enforce)\b"
        ),
        # Office-skewed (Dwight)
        "survival_outdoors": (
            r"\b(beet|farm|survival|weapons|bear|hunt|train|mose|schrute"
            r"|acreage|harvest|defence|strength|combat|militia|nunchucks"
            r"|throwing stars|crossbow|karate|self.reliance)\b"
        ),
        # Office-skewed
        "sales_business": (
            r"\b(paper|sales|quota|client|commission|customer|discount"
            r"|delivery|dunder mifflin|shipment|account|invoice|supply)\b"
        ),
        # General
        "sarcasm_markers": (
            r"\b(oh really|wow|gee|sure|right|yeah right|obviously"
            r"|clearly|apparently)\b"
        ),
        "affection": (
            r"\b(love|sweetie|honey|dear|baby|sweetheart|babe|darling|bestie)\b"
        ),
        "insults_put_downs": (
            r"\b(idiot|stupid|dumb|moron|loser|pathetic|fool|ridiculous|incompetent)\b"
        ),
        "uncertainty": (
            r"\b(maybe|perhaps|i guess|i think|i don't know|not sure|might)\b"
        ),
        "formal_language": (
            r"\b(therefore|furthermore|moreover|consequently|nevertheless"
            r"|indeed|thus|hereby|whereas)\b"
        ),
        "pop_culture": (
            r"\b(star trek|star wars|comic|batman|superman|marvel|dc|hobbit"
            r"|lord of the rings|harry potter|dungeons|xbox|playstation"
            r"|video game|klingon|jedi)\b"
        ),
        "self_reference": (
            r"\b(i am|i'm|my|me|myself|i have|i've|i was|i will|i'll)\b"
        ),
    }

    results = {}
    for name, pattern in patterns.items():
        count = sum(1 for d in dialogues if re.search(pattern, d, re.IGNORECASE))
        results[name] = round(count / total, 3)

    return results


# ─────────────────────────────────────────────
# 5. TEMPORAL EVOLUTION
# ─────────────────────────────────────────────
def analyze_evolution(df: pd.DataFrame, character: str) -> dict:
    """Track how the character's dialogue changes across seasons."""
    char_df = df[df["character"] == character]

    by_season = {}
    for season in sorted(char_df["season"].unique()):
        season_df = char_df[char_df["season"] == season]
        by_season[int(season)] = {
            "lines": len(season_df),
            "avg_words": round(season_df["word_count"].mean(), 1),
            "question_ratio": round(
                season_df["dialogue"].str.contains(r"\?").sum()
                / max(len(season_df), 1),
                3,
            ),
        }

    return by_season


# ─────────────────────────────────────────────
# 6. SAMPLE DIALOGUE EXTRACTION
# ─────────────────────────────────────────────
def extract_sample_dialogues(df: pd.DataFrame, character: str, n_samples: int = 10) -> dict:
    """Extract representative dialogue samples — longest and random lines."""
    char_df = df[df["character"] == character]

    long_lines    = char_df.nlargest(n_samples, "word_count")["dialogue"].tolist()
    sample_size   = min(n_samples, len(char_df))
    random_lines  = char_df.sample(sample_size, random_state=42)["dialogue"].tolist()

    return {
        "longest_monologues": long_lines[:5],
        "random_sample":      random_lines[:10],
    }


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────
def build_all_profiles(df: pd.DataFrame, characters: list) -> dict:
    """Run full Stage-1 analysis pipeline for all characters."""
    profiles = {}

    for char in characters:
        print(f"  Analyzing {char} ({SHOW_MAP.get(char, '?')})...")
        profiles[char] = {
            "show":              SHOW_MAP.get(char, ""),
            "speech_patterns":   analyze_speech_patterns(df, char),
            "distinctive_language": find_distinctive_phrases(df, char),
            "relationships":     analyze_relationships(df, char),
            "tone_indicators":   analyze_tone(df, char),
            "evolution_by_season": analyze_evolution(df, char),
            "sample_dialogues":  extract_sample_dialogues(df, char),
        }

    return profiles


# ─────────────────────────────────────────────
# STAGE 2 — OLLAMA SYNTHESIS
# ─────────────────────────────────────────────
def _call_ollama(prompt: str, model: str) -> str:
    """
    Send a single prompt to the local Ollama server and return the response.
    Uses the /api/generate endpoint (non-streaming).
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 1536,  # 4-section format needs more room than the old 3-5 sentences
        },
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach Ollama at {OLLAMA_URL}. "
            "Make sure Ollama is running:  ollama serve"
        )
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error: {exc}")


def synthesize_with_llm(profiles: dict, model: str = DEFAULT_OLLAMA_MODEL) -> dict:
    """
    Call a local Ollama model once per character to turn raw stats into a
    concise CHARACTER_DESCRIPTIONS-style string.

    Returns {character_name: description_string}.
    """
    synthesized = {}

    for char, data in profiles.items():
        show_name = data.get("show") or SHOW_MAP.get(char, "a TV show")
        print(f"  Synthesising {char} ({show_name}, model: {model})...")

        # Trim the payload to the most signal-rich keys.
        # Keep real sample lines so the model can see the character's actual voice.
        slim_data = {
            "speech_patterns": data.get("speech_patterns", {}),
            "catchphrases": data.get("distinctive_language", {}).get("catchphrases", {}),
            "repeated_phrases": dict(list(
                data.get("distinctive_language", {})
                    .get("repeated_phrases", {})
                    .items()
            )[:10]),
            "top_distinctive_words": list(
                data.get("distinctive_language", {})
                    .get("distinctive_words", {})
                    .keys()
            )[:20],
            "top_co_stars": list(
                data.get("relationships", {})
                    .get("scenes_together", {})
                    .keys()
            )[:6],
            "tone_indicators": data.get("tone_indicators", {}),
            "sample_dialogues": {
                "longest_monologues": data.get("sample_dialogues", {}).get(
                    "longest_monologues", []
                )[:3],
                "random_sample": data.get("sample_dialogues", {}).get(
                    "random_sample", []
                )[:8],
            },
        }

        prompt = f"""You are writing a system-prompt character description for an AI chatbot that will roleplay as {char} from {show_name}.

The description will be injected verbatim as the chatbot's system prompt, so it must read as direct instructions to the AI — written in second person ("You are {char}...").

Study the statistical data below. It contains real catchphrases, repeated phrases, distinctive vocabulary, and actual sample lines from {char}'s dialogue. Use these to write something accurate and specific, not generic.

OUTPUT FORMAT — write four clearly labelled sections in this exact order:

IDENTITY: One paragraph (3-4 sentences). Who {char} is, their role, their core personality, and their most important relationships. Be specific — use names from top_co_stars, reference their job or situation.

SPEECH STYLE: One paragraph (3-5 sentences). How {char} actually talks. Sentence length and structure, how they open sentences, verbal tics, how they handle uncertainty or disagreement. Ground this in the real catchphrases and repeated_phrases from the data — quote them directly if they are distinctive.

RULES: A short list of 4-6 "NEVER" statements. Things {char} would never say or do in conversation. Be character-specific, not generic. Examples of what a RULES line looks like: "Never admit you are wrong even when you clearly are." "Never use the phrase 'Great question!' or any other AI assistant phrasing." "Never express genuine empathy — offer clinical observations instead."

RESPONSE STYLE: One sentence describing how long and what shape {char}'s responses tend to be (e.g. long lectures, short clipped commands, rambling stream-of-consciousness, self-deprecating hedges).

Use ONLY plain text. No markdown, no bold, no bullet symbols beyond the RULES list dashes. Start the output immediately with "IDENTITY:" — no preamble.

DATA:
{json.dumps(slim_data, indent=2, default=str)}

Write the description now:"""

        desc = _call_ollama(prompt, model)

        # Strip any preamble Ollama adds before the first expected section header.
        # The new 4-section format opens with "IDENTITY:"; fall back to the old
        # "You are {char}" marker if the model ignores the format instruction.
        for marker in ("IDENTITY:", f"You are {char}"):
            idx = desc.find(marker)
            if idx != -1:
                desc = desc[idx:]
                break

        synthesized[char] = desc
        print(f"    → {desc[:90]}...")

    return synthesized


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Profile TV characters from merged_tv_dialogues.csv"
    )
    parser.add_argument(
        "--synthesize", action="store_true",
        help="Run Stage 2: call Ollama to generate CHARACTER_DESCRIPTIONS strings",
    )
    parser.add_argument(
        "--model", default=DEFAULT_OLLAMA_MODEL,
        help=f"Ollama model to use for synthesis (default: {DEFAULT_OLLAMA_MODEL})",
    )
    parser.add_argument(
        "--csv", default=CSV_PATH,
        help=f"Path to the merged CSV (default: {CSV_PATH})",
    )
    args = parser.parse_args()

    print(f"Loading {args.csv}...")
    df = load_data(args.csv)
    print(f"  Loaded {len(df):,} lines of dialogue")
    print(f"  Show breakdown: TBBT={len(df[df['show']=='The Big Bang Theory']):,}  "
          f"The Office={len(df[df['show']=='The Office']):,}")
    print(f"\nCharacters to profile: {MAIN_CHARACTERS}")
    print()

    # Stage 1 — statistical analysis
    print("Stage 1: Statistical analysis...")
    profiles = build_all_profiles(df, MAIN_CHARACTERS)

    with open(STATS_OUTPUT_PATH, "w") as f:
        json.dump(profiles, f, indent=2, default=str)
    print(f"\n  Raw stats saved to {STATS_OUTPUT_PATH}")

    # Stage 2 — Ollama synthesis (optional)
    if args.synthesize:
        print(f"\nStage 2: LLM synthesis via Ollama (model: {args.model})...")
        synthesized = synthesize_with_llm(profiles, model=args.model)

        with open(OUTPUT_PATH, "w") as f:
            json.dump(synthesized, f, indent=2, default=str)
        print(f"\n  Synthesised profiles saved to {OUTPUT_PATH}")

        print("\n─── Generated CHARACTER_DESCRIPTIONS ───")
        for char, desc in synthesized.items():
            show = SHOW_MAP.get(char, "")
            print(f"\n[{char}]  ({show})")
            print(desc)
    else:
        with open(OUTPUT_PATH, "w") as f:
            json.dump(profiles, f, indent=2, default=str)
        print(f"  Profiles (Stage 1 only) saved to {OUTPUT_PATH}")
        print()
        print("Run with --synthesize to generate LLM character descriptions.")
        print(f"Use --model <name> to pick an Ollama model (default: {DEFAULT_OLLAMA_MODEL}).")
