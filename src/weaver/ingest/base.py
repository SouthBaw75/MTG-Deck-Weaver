"""Shared contracts and helpers for all data ingesters.

Every ingester is a module in weaver.ingest exposing:

    NAME: str
    def ingest(conn, cache_dir: Path, force: bool = False,
               progress: Callable[[str], None] = print) -> IngestResult

Rules of the road:
- Download into `cache_dir` via download_file() (streaming, atomic rename),
  never into the repo tree.
- Be idempotent: safe to re-run; replace your own tables' contents.
- Record freshness in meta: set_meta(conn, f"{NAME}.updated_at", utcnow_iso()).
- Never let one source's failure corrupt the DB: do all inserts in one
  transaction (the runner wraps ingest() calls and rolls back on error).
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from weaver import USER_AGENT

Progress = Callable[[str], None]

# Scryfall asks API clients to identify themselves and send Accept.
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}

REQUEST_TIMEOUT = 60  # seconds


@dataclass
class IngestResult:
    name: str
    rows: int = 0
    skipped: bool = False
    detail: str = ""
    warnings: list[str] = field(default_factory=list)


def utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def http_get_json(url: str, *, params: dict | None = None) -> dict:
    """GET a JSON document with standard headers and timeout."""
    resp = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def download_file(
    url: str,
    dest: Path,
    *,
    force: bool = False,
    progress: Progress = print,
) -> Path:
    """Stream `url` to `dest` atomically (tmp file + rename).

    If `dest` already exists and force is False, the cached copy is reused —
    callers decide staleness policy via the meta table before calling.
    """
    if dest.exists() and not force:
        progress(f"  using cached {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    progress(f"  downloading {url}")
    with requests.get(url, headers=DEFAULT_HEADERS, stream=True, timeout=REQUEST_TIMEOUT) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(dest)
    return dest
