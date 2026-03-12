#!/usr/bin/env python3
"""SQLite-backed evaluation logger for chat interactions."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional
from uuid import uuid4


class EvalLogger:
    """Persist chat turns for later evaluation without affecting serving."""

    def __init__(self, db_path: Path, enabled: bool = True) -> None:
        self._db_path = db_path
        self._enabled = enabled
        if self._enabled:
            self._initialise()

    def _initialise(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._db_path, timeout=30) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS eval_logs (
                        log_id TEXT PRIMARY KEY,
                        character TEXT NOT NULL,
                        user_message TEXT NOT NULL,
                        bot_response TEXT NOT NULL,
                        rag_query TEXT,
                        model_name TEXT,
                        rag_backend TEXT,
                        rag_time_ms REAL,
                        llm_time_ms REAL,
                        total_time_ms REAL,
                        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_eval_logs_created_at
                    ON eval_logs(created_at DESC)
                    """
                )
                conn.commit()
        except OSError as exc:
            self._enabled = False
            print(f"[eval_logger] Failed to prepare {self._db_path}: {exc}")
        except sqlite3.Error as exc:
            self._enabled = False
            print(f"[eval_logger] Failed to initialise {self._db_path}: {exc}")

    def is_enabled(self) -> bool:
        return self._enabled

    def get_db_path(self) -> Path:
        return self._db_path

    def log_interaction(
        self,
        *,
        character: str,
        user_message: str,
        bot_response: str,
        rag_query: Optional[str],
        model_name: str,
        rag_backend: str,
        rag_time_ms: float,
        llm_time_ms: float,
        total_time_ms: float,
    ) -> Optional[str]:
        if not self._enabled:
            return None

        log_id = uuid4().hex
        try:
            with sqlite3.connect(self._db_path, timeout=30) as conn:
                conn.execute(
                    """
                    INSERT INTO eval_logs (
                        log_id,
                        character,
                        user_message,
                        bot_response,
                        rag_query,
                        model_name,
                        rag_backend,
                        rag_time_ms,
                        llm_time_ms,
                        total_time_ms
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        log_id,
                        character,
                        user_message,
                        bot_response,
                        rag_query,
                        model_name,
                        rag_backend,
                        rag_time_ms,
                        llm_time_ms,
                        total_time_ms,
                    ),
                )
                conn.commit()
        except sqlite3.Error as exc:
            print(f"[eval_logger] Failed to write to {self._db_path}: {exc}")
            return None

        return log_id


def build_eval_logger(enabled: bool = True, db_path: Optional[str] = None) -> EvalLogger:
    env_enabled = os.environ.get("EVAL_LOGGING")
    if env_enabled is not None:
        enabled = env_enabled.lower() not in {"0", "false", "no"}

    resolved_path = db_path or os.environ.get("EVAL_LOG_DB") or "./eval_logs.db"
    return EvalLogger(Path(resolved_path), enabled=enabled)