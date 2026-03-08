#!/usr/bin/env bash
# =============================================================================
# start.sh — Full pipeline launcher for the TV Character Chatbot
#
# Steps (in order):
#   1. build_chromadb.py  --reset     — embed merged_tv_dialogues.csv → chroma_db/
#   2. character_profiler.py          — analyse dialogue, call Ollama → character_profiles.json
#   3. chatbot_server_ollama.py       — FastAPI + WebSocket backend   (background, port 8001)
#   4. npm run dev  (./ui/)           — React / Vite frontend         (foreground,  port 5173)
#
# Usage:
#   ./start.sh                               # full run (resets ChromaDB)
#   ./start.sh --skip-build                  # skip step 1
#   ./start.sh --skip-profile                # skip step 2
#   ./start.sh --skip-build --skip-profile   # jump straight to server + UI
#   ./start.sh --model mistral:7b            # Ollama model for both profiler & server
#   ./start.sh --workers 8                   # ChromaDB build parallelism
#   ./start.sh --no-reset                    # incremental ChromaDB update (no wipe)
#
# Flags:
#   --skip-build      Skip build_chromadb.py
#   --skip-profile    Skip character_profiler.py --synthesize
#   --model <tag>     Ollama model tag (default: llama3:latest)
#   --workers <n>     ChromaDB build workers (default: 4)
#   --no-reset        Don't wipe ChromaDB before building
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

step()  { echo -e "\n${CYAN}${BOLD}▶ $*${RESET}"; }
ok()    { echo -e "${GREEN}✔  $*${RESET}"; }
warn()  { echo -e "${YELLOW}⚠  $*${RESET}"; }
die()   { echo -e "${RED}✘  $*${RESET}" >&2; exit 1; }

# ── Defaults ──────────────────────────────────────────────────────────────────
SKIP_BUILD=true
SKIP_PROFILE=true
OLLAMA_MODEL="llama3:latest"
CHROMA_WORKERS=4
CHROMA_RESET="--reset"

# ── Parse flags ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build)    SKIP_BUILD=true ;;
        --skip-profile)  SKIP_PROFILE=true ;;
        --model)         OLLAMA_MODEL="$2"; shift ;;
        --workers)       CHROMA_WORKERS="$2"; shift ;;
        --no-reset)      CHROMA_RESET="" ;;
        --help|-h)
            sed -n '2,26p' "$0"   # print the header comment
            exit 0 ;;
        *)               die "Unknown flag: $1\nRun:  ./start.sh --help" ;;
    esac
    shift
done

# ── Resolve script directory so the script works from anywhere ────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Python: always use the project venv ───────────────────────────────────────
PYTHON="$SCRIPT_DIR/.venv/bin/python"

# ── Log directory ─────────────────────────────────────────────────────────────
LOG_DIR="$SCRIPT_DIR/.logs"
mkdir -p "$LOG_DIR"

SERVER_LOG="$LOG_DIR/server.log"
UI_LOG="$LOG_DIR/ui.log"

# ── PID tracking for cleanup ──────────────────────────────────────────────────
SERVER_PID=""
UI_PID=""

cleanup() {
    echo ""
    step "Shutting down background processes…"
    [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null \
        && ok "Server (PID $SERVER_PID) stopped"
    [[ -n "$UI_PID" ]]     && kill "$UI_PID"     2>/dev/null \
        && ok "UI     (PID $UI_PID) stopped"
    ok "Done. Logs saved to $LOG_DIR/"
}
trap cleanup EXIT INT TERM

# ─────────────────────────────────────────────────────────────────────────────
# PRE-FLIGHT CHECKS
# ─────────────────────────────────────────────────────────────────────────────
step "Pre-flight checks"

# Python venv
[[ -x "$PYTHON" ]] || die \
    ".venv not found at $SCRIPT_DIR/.venv\n" \
    "Create it:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"

# External tools
command -v ollama >/dev/null 2>&1 || die "ollama not found — install from https://ollama.ai"
command -v npm    >/dev/null 2>&1 || die "npm not found — install Node.js from https://nodejs.org"

# Required files
[[ -f "merged_tv_dialogues.csv" ]] || die \
    "merged_tv_dialogues.csv not found in $SCRIPT_DIR\n" \
    "Expected combined TBBT + The Office dialogue CSV."
[[ -d "ui"              ]] || die "ui/ directory not found"
[[ -f "ui/package.json" ]] || die "ui/package.json not found"

# Ollama reachability (soft warning — server itself will re-check)
if ! ollama list >/dev/null 2>&1; then
    warn "Ollama does not appear to be running."
    warn "Start it with:  ollama serve"
    warn "Continuing — chatbot server will warn again at startup."
fi

ok "Pre-flight checks passed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Build ChromaDB
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$SKIP_BUILD" == true ]]; then
    warn "Skipping ChromaDB build (--skip-build)"
else
    step "Building ChromaDB  (workers=$CHROMA_WORKERS, reset=$([[ -n "$CHROMA_RESET" ]] && echo yes || echo no))"
    "$PYTHON" build_chromadb.py \
        $CHROMA_RESET \
        --workers "$CHROMA_WORKERS" \
        || die "build_chromadb.py failed — check output above"
    ok "ChromaDB build complete"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Character profiler
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$SKIP_PROFILE" == true ]]; then
    warn "Skipping character profiler (--skip-profile)"
else
    step "Running character profiler (model=$OLLAMA_MODEL)"
    "$PYTHON" character_profiler.py \
        --synthesize \
        --model "$OLLAMA_MODEL" \
        || die "character_profiler.py failed — check output above"
    ok "character_profiles.json generated"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Start chatbot server in background
# ─────────────────────────────────────────────────────────────────────────────
step "Starting chatbot server  (model=$OLLAMA_MODEL)"

"$PYTHON" chatbot_server_ollama.py \
    --model "$OLLAMA_MODEL" \
    > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

# Poll /health until the server is accepting connections (max 30 s)
echo -n "  Waiting for server on :8001 "
WAIT=0
until curl -sf http://localhost:8001/health >/dev/null 2>&1; do
    # Check the server process is still alive
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo ""
        die "Server process exited early.\nCheck logs: $SERVER_LOG"
    fi
    sleep 1
    WAIT=$((WAIT + 1))
    echo -n "."
    if [[ $WAIT -ge 30 ]]; then
        echo ""
        die "Server did not start within 30 s.\nCheck logs: $SERVER_LOG"
    fi
done
echo ""
ok "Server is up  →  http://localhost:8001   (log: .logs/server.log)"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Start React UI (foreground output via tee)
# ─────────────────────────────────────────────────────────────────────────────
step "Starting React UI  (npm run dev)"

cd "$SCRIPT_DIR/ui"
npm run dev 2>&1 | tee "$UI_LOG" &
UI_PID=$!
cd "$SCRIPT_DIR"

ok "UI starting  →  http://localhost:5173   (log: .logs/ui.log)"

echo ""
echo -e "${BOLD}════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  All services running${RESET}"
echo -e "${BOLD}  Backend : ${CYAN}http://localhost:8001${RESET}"
echo -e "${BOLD}  Frontend: ${CYAN}http://localhost:5173${RESET}"
echo -e "${BOLD}  Model   : ${CYAN}$OLLAMA_MODEL${RESET}"
echo -e "${BOLD}  Logs    : ${CYAN}$LOG_DIR/${RESET}"
echo -e "${BOLD}  Stop    : Ctrl+C${RESET}"
echo -e "${BOLD}════════════════════════════════════════════${RESET}"

# Keep alive so the EXIT trap fires on Ctrl+C and kills both background PIDs.
wait
