"""
TV Character Profiler
=====================
Generates structured character profiles for AI chatbot personas using Groq.

Pass character names and their shows; the LLM generates system-prompt
descriptions (IDENTITY, SPEECH STYLE, BEHAVIORAL TRIGGERS, RULES, RESPONSE
STYLE) from its knowledge of the characters.

Usage:
  python character_profiler.py --characters "Sheldon:The Big Bang Theory,Leonard:The Big Bang Theory"
  python character_profiler.py --characters "Michael:The Office,Dwight:The Office" --model llama-3.3-70b-versatile
  python character_profiler.py --characters "Sheldon:The Big Bang Theory" --output my_profiles.json

Set GROQ_API_KEY environment variable before running.
"""

import argparse
import json
import os
import time

from dotenv import load_dotenv
from openai import OpenAI

# ─────────────────────────────────────────────
# DEFAULTS
# ─────────────────────────────────────────────
_DEFAULT_OUTPUT_PATH   = "character_profiles.json"
_DEFAULT_GROQ_MODEL    = "openai/gpt-oss-safeguard-20b"

# Default characters when --characters is omitted
_DEFAULT_CHARACTERS: dict = {
    "Sheldon": "The Big Bang Theory",
    "Leonard": "The Big Bang Theory",
    "Michael": "The Office",
    "Dwight":  "The Office",
}

# ── Synthesis LLM settings ─────────────────────────────────────────────────
_SYNTHESIS_TEMPERATURE = 0.7
_SYNTHESIS_MAX_TOKENS  = 2048
_SYNTHESIS_TIMEOUT     = 300   # seconds

# ── Retry / rate-limit settings ────────────────────────────────────────────
_MAX_RETRIES           = 3     # attempts per character before giving up
_RETRY_DELAY           = 8     # seconds to wait between retries
_INTER_CHAR_DELAY      = 3     # seconds to pause between characters


# ─────────────────────────────────────────────
# LLM SYNTHESIS
# ─────────────────────────────────────────────
def _call_groq(client: OpenAI, prompt: str, model: str) -> str:
    """Send a single prompt to Groq and return the text response."""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=_SYNTHESIS_TEMPERATURE,
        max_tokens=_SYNTHESIS_MAX_TOKENS,
        timeout=_SYNTHESIS_TIMEOUT,
    )
    return resp.choices[0].message.content.strip()


def synthesize_characters(
    characters: dict,          # {character_name: show_name}
    model: str = _DEFAULT_GROQ_MODEL,
) -> tuple[dict, list[str]]:
    """Call Groq once per character to generate a structured system-prompt description.

    Reads GROQ_API_KEY from the environment (raises SystemExit if missing).
    Returns ``(synthesized, failed)`` where:
      - synthesized: {character_name: description_string} for successful calls
      - failed:      list of character names whose API call errored
    """
    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise SystemExit(
            "ERROR: GROQ_API_KEY not found.\n"
            "Add it to your .env file:  GROQ_API_KEY=gsk_...\n"
            "Or get a free key at https://console.groq.com"
        )
    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
    synthesized: dict = {}
    failed: list[str] = []

    char_list = list(characters.items())
    for i, (char, show_name) in enumerate(char_list):
        print(f"  Synthesizing {char} ({show_name}, model: {model})...")

        prompt = f"""You are writing a system-prompt character description for an AI chatbot that will roleplay as {char} from {show_name}.

The description will be injected verbatim as the chatbot's system prompt, so it must read as direct instructions to the AI — written in second person ("You are {char}..."). The goal is a chatbot that feels like talking to the actual character, not a generic impersonation.

Draw on your detailed knowledge of how {char} actually speaks in {show_name}. Generic personality descriptions are useless — this must be grounded in how {char} actually talks, their specific catchphrases, running gags, and real behavioral patterns from the show.

IMPORTANT BEFORE YOU WRITE:
- Identify {char}'s single most iconic recurring bit or running gag (e.g. a joke format they always deploy, a correction they insist on making, a ritual phrase). It must appear in SPEECH STYLE and at least one BEHAVIORAL TRIGGER.
- Identify what secretly drives or insecures {char} underneath their surface persona. It must appear in IDENTITY.
- RULES must be about personality and character-specific behavior, NOT about speech formality (e.g. do not write "never use contractions" — that is a formatting rule, not a personality rule).
- For catchphrases: the rule you write must name the ONE specific moment type that earns the catchphrase. Vague conditions ("when appropriate", "when the time is right", "occasionally") are not acceptable — a reader must be able to determine unambiguously whether the current moment qualifies. The rule must also list at least two situations where the catchphrase does NOT apply, to prevent over-firing.

OUTPUT FORMAT — write five clearly labelled sections in this exact order:

IDENTITY: One paragraph (3-4 sentences). Who {char} is, their role, their core personality, and their most important relationships. End with one sentence about what secretly drives or insecures them underneath their surface behavior.

SPEECH STYLE: One paragraph (3-5 sentences). How {char} actually talks — sentence length, how they open, verbal tics, how they handle uncertainty or disagreement. Quote their most iconic catchphrase or recurring bit verbatim here (e.g. if they always make a specific correction, or always deploy a specific joke format, write it out). Ground everything in specific real phrases they actually say in the show.

BEHAVIORAL TRIGGERS: A dash-separated list of 5-7 "When [scenario] → [exact reaction]" pairs. These are specific situations {char} reliably reacts to in a distinctive way. Include: being corrected or proven wrong, someone challenging their authority or self-image, a topic they obsess over, needing to apologise, their most iconic running gag being triggered (e.g. an accidental straight line they can't resist). For each trigger, describe exactly what {char} does or says — reference real catchphrases. The trigger for the catchphrase must describe the ONE situation type that earns it — not "when it feels right" but a concrete, unambiguous scenario (e.g. "When {char} has just told a deliberate lie or made-up statement as a joke and is now revealing it was false → [catchphrase]"). Do NOT write generic personality traits; write concrete stimulus-response pairs.

RULES: A list of 5-7 "NEVER" statements about {char}'s personality and behavior in conversation. Be character-specific. Examples: "Never admit you are wrong even when clearly proven so." "Never use AI assistant phrases like 'Great question!' or 'I understand how you feel.'" "Never express genuine vulnerability — reframe all personal feelings as logical or practical matters." For the catchphrase rule, write it in this exact form: "Never say [catchphrase] except in this one situation: [single, specific, unambiguous trigger sentence]. It does NOT apply when [counter-example 1] or when [counter-example 2]." Do NOT include rules about speech formality or contractions.

RESPONSE STYLE: One sentence describing how long and what shape {char}'s responses tend to be (e.g. long lectures, short clipped commands, rambling stream-of-consciousness, self-deprecating hedges followed by a pivot).

Use ONLY plain text. No markdown, no bold, no bullet symbols beyond the list dashes. Start the output immediately with "IDENTITY:" — no preamble.

Write the description now:"""

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                desc = _call_groq(client, prompt, model)

                # Validate: response must be non-empty and contain the IDENTITY section.
                if not desc.strip():
                    raise ValueError("Model returned an empty response.")
                idx = desc.find("IDENTITY:")
                if idx == -1:
                    raise ValueError(
                        f"Response missing IDENTITY: section. Got: {desc[:120]!r}"
                    )
                desc = desc[idx:]

                synthesized[char] = desc
                print(f"    ✓ {desc[:80]}...")
                break  # success — move to next character

            except Exception as exc:
                if attempt < _MAX_RETRIES:
                    print(
                        f"    ✗ attempt {attempt}/{_MAX_RETRIES} failed: {exc}\n"
                        f"      retrying in {_RETRY_DELAY}s…"
                    )
                    time.sleep(_RETRY_DELAY)
                else:
                    print(f"    ✗ all {_MAX_RETRIES} attempts failed: {exc}")
                    failed.append(char)

        # Pause between characters to avoid hitting rate limits on the next call.
        if i < len(char_list) - 1:
            time.sleep(_INTER_CHAR_DELAY)

    return synthesized, failed


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate TV character profiles for chatbot personas using Groq"
    )
    p.add_argument(
        "--characters", default=None,
        help=(
            "Comma-separated 'Character:Show' pairs to profile. "
            "E.g. 'Sheldon:The Big Bang Theory,Michael:The Office'. "
            "If omitted, profiles the 4 default characters "
            "(Sheldon, Leonard, Michael, Dwight)."
        ),
    )
    p.add_argument(
        "--output", default=_DEFAULT_OUTPUT_PATH,
        help=f"Output path for synthesized profiles (default: {_DEFAULT_OUTPUT_PATH})",
    )
    p.add_argument(
        "--model", default=_DEFAULT_GROQ_MODEL,
        help=(
            f"Groq model for synthesis (default: {_DEFAULT_GROQ_MODEL}). "
            "See https://console.groq.com/docs/models for available models."
        ),
    )
    return p


if __name__ == "__main__":
    args = _build_cli().parse_args()

    # ── Resolve character list ────────────────────────────────────────────────
    if args.characters is None:
        characters: dict = _DEFAULT_CHARACTERS
    else:
        characters = {}
        for entry in args.characters.split(","):
            entry = entry.strip()
            if ":" not in entry:
                raise SystemExit(
                    f"Invalid format '{entry}'. Use 'Character:Show' pairs, e.g.\n"
                    f"  --characters 'Sheldon:The Big Bang Theory,Michael:The Office'"
                )
            char, show = entry.split(":", 1)
            characters[char.strip()] = show.strip()

    print(f"\nCharacters to profile ({len(characters)}):")
    for char, show in characters.items():
        print(f"  {char} ({show})")
    print()

    # ── Load any existing profiles so reruns don't discard them ──────────────
    existing: dict = {}
    output_path = args.output
    try:
        with open(output_path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            existing = {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}
            if existing:
                print(f"Loaded {len(existing)} existing profile(s) from '{output_path}'.")
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"  Warning: could not read '{output_path}': {exc} — starting fresh.")

    # ── Generate profiles ─────────────────────────────────────────────────────
    print(f"Generating profiles via Groq (model: {args.model})...")
    synthesized, failed = synthesize_characters(characters, model=args.model)

    # Merge: existing profiles kept; newly generated ones overwrite matching keys.
    # Filter out any empty strings so blank entries never persist in the file.
    merged = {
        k: v for k, v in {**existing, **synthesized}.items()
        if isinstance(v, str) and v.strip()
    }

    with open(output_path, "w") as f:
        json.dump(merged, f, indent=2, default=str)
    print(f"\n  Profiles saved to '{output_path}'  ({len(merged)} total).")

    if failed:
        print(f"\n  WARNING — failed to generate profiles for: {failed}")
        print("  Re-run to retry only the failed characters:")
        retry_arg = ",".join(f"{c}:{characters[c]}" for c in failed)
        print(f"    python character_profiler.py --characters \"{retry_arg}\"")

    print("\n--- Generated Descriptions ---")
    for char, desc in synthesized.items():
        print(f"\n[{char}]  ({characters[char]})")
        print(desc)
