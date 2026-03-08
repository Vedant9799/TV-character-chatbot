#!/usr/bin/env python3
"""Retrieval debug logger — logs input, output, scoring metrics, and candidates for agentic feedback.

Enable via RETRIEVAL_DEBUG=1 or --retrieval-debug. Writes JSONL to retrieval_debug.log (and optionally stdout).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Enable when RETRIEVAL_DEBUG=1 or set programmatically
_DEBUG_ENABLED = os.environ.get("RETRIEVAL_DEBUG", "").lower() in ("1", "true", "yes")
# Log next to this file so it's always in the project dir regardless of CWD
_LOG_PATH = Path(__file__).resolve().parent / "retrieval_debug.log"
_LOG_TO_STDOUT = os.environ.get("RETRIEVAL_DEBUG_STDOUT", "").lower() in ("1", "true", "yes")
_FIRST_LOG_DONE = False


def set_debug(enabled: bool = True, log_path: Optional[Path] = None, to_stdout: bool = False) -> None:
    """Enable or disable retrieval debug logging."""
    global _DEBUG_ENABLED, _LOG_PATH, _LOG_TO_STDOUT
    _DEBUG_ENABLED = enabled
    if log_path is not None:
        _LOG_PATH = log_path
    _LOG_TO_STDOUT = to_stdout


def is_debug_enabled() -> bool:
    return _DEBUG_ENABLED


def get_log_path() -> Path:
    """Return the path where logs are written (for startup message)."""
    return _LOG_PATH


def log_retrieval(entry: Dict[str, Any], force: bool = False) -> None:
    """Emit one retrieval trace as JSONL. Called by retrieval.retrieve() when debug enabled."""
    global _FIRST_LOG_DONE
    if not _DEBUG_ENABLED and not force:
        return
    entry["_timestamp"] = datetime.utcnow().isoformat() + "Z"
    line = json.dumps(entry, default=str) + "\n"
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
        if not _FIRST_LOG_DONE:
            _FIRST_LOG_DONE = True
            print(f"[retrieval_logger] Logging to {_LOG_PATH.resolve()}")
    except OSError as e:
        print(f"[retrieval_logger] Failed to write to {_LOG_PATH}: {e}")
    if _LOG_TO_STDOUT:
        print(f"[RETRIEVAL_DEBUG] {line.strip()}")
