"""SQLite-backed store for the user's saved decks.

Separate from the knowledge base (weaver.db): user data lives in its own file so
`weaver update` — which rebuilds card/combo/rules tables — can never disturb it.
Default location: <repo>/data/decks.db, overridable via WEAVER_DECKS_DB.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from weaver.db.connection import repo_root
from weaver.ingest.base import utcnow_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    commander  TEXT,
    bracket    INTEGER,
    decklist   TEXT NOT NULL,
    notes      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def default_decks_path() -> Path:
    env = os.environ.get("WEAVER_DECKS_DB")
    return Path(env) if env else repo_root() / "data" / "decks.db"


def connect_decks(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else default_decks_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def save_deck(
    conn: sqlite3.Connection,
    *,
    name: str,
    decklist: str,
    commander: str | None = None,
    bracket: int | None = None,
    notes: str | None = None,
    deck_id: int | None = None,
) -> int:
    """Insert a new deck, or update an existing one when deck_id is given.
    Returns the deck id."""
    name = (name or "").strip() or "Untitled deck"
    now = utcnow_iso()
    if deck_id is not None:
        cur = conn.execute(
            "UPDATE decks SET name=?, commander=?, bracket=?, decklist=?, notes=?, updated_at=? "
            "WHERE id=?",
            (name, commander, bracket, decklist, notes, now, deck_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"no deck with id {deck_id}")
        conn.commit()
        return deck_id
    cur = conn.execute(
        "INSERT INTO decks(name, commander, bracket, decklist, notes, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (name, commander, bracket, decklist, notes, now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_decks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, commander, bracket, created_at, updated_at, decklist "
        "FROM decks ORDER BY updated_at DESC"
    ).fetchall()


def get_deck(conn: sqlite3.Connection, deck_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()


def rename_deck(conn: sqlite3.Connection, deck_id: int, name: str) -> None:
    cur = conn.execute(
        "UPDATE decks SET name = ?, updated_at = ? WHERE id = ?",
        ((name or "").strip() or "Untitled deck", utcnow_iso(), deck_id),
    )
    if cur.rowcount == 0:
        raise KeyError(f"no deck with id {deck_id}")
    conn.commit()


def delete_deck(conn: sqlite3.Connection, deck_id: int) -> bool:
    cur = conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
    conn.commit()
    return cur.rowcount > 0
