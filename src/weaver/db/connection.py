"""Database location and connection helpers."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def repo_root() -> Path:
    """Best-effort project root: WEAVER_HOME env var, else cwd."""
    env = os.environ.get("WEAVER_HOME")
    return Path(env) if env else Path.cwd()


def default_cache_dir() -> Path:
    return repo_root() / "data" / "cache"


def default_db_path() -> Path:
    return default_cache_dir() / "weaver.db"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the knowledge base with sane pragmas."""
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
