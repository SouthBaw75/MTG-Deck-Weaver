"""Curated data ingester: Commander brackets and the Game Changers list.

Unlike the other ingesters, this one reads REPO-LOCAL files (no network):

- data/curated/brackets.json       -> `brackets` table
- data/curated/game_changers.json  -> `game_changers` table

After loading, the cards table is reconciled: every card named on the
curated Game Changers list gets is_game_changer = 1. The curated list is
authoritative ON TOP of Scryfall's own game_changer flag — existing flags
are never zeroed out.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from weaver.db.connection import repo_root
from weaver.ingest.base import IngestResult, Progress, set_meta, utcnow_iso

NAME = "curated"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ingest(
    conn: sqlite3.Connection,
    cache_dir: Path,
    force: bool = False,
    progress: Progress = print,
    *,
    curated_dir: Path | None = None,
) -> IngestResult:
    result = IngestResult(name=NAME)

    if curated_dir is None:
        curated_dir = repo_root() / "data" / "curated"

    brackets_doc = _load_json(curated_dir / "brackets.json")
    gc_doc = _load_json(curated_dir / "game_changers.json")

    # ---- validate game_changers.json ----------------------------------
    gc_cards: list[str] = gc_doc["cards"]
    gc_count = gc_doc["count"]
    if gc_count != len(gc_cards):
        raise ValueError(
            f"game_changers.json is inconsistent: count={gc_count} "
            f"but cards has {len(gc_cards)} entries"
        )

    # ---- brackets: full refresh (table wholly owned by this ingester) --
    brackets = brackets_doc["brackets"]
    conn.execute("DELETE FROM brackets")
    conn.executemany(
        "INSERT INTO brackets(number, name, game_changer_limit, description) "
        "VALUES(?, ?, ?, ?)",
        (
            (b["number"], b["name"], b["game_changer_limit"], b["description"])
            for b in brackets
        ),
    )
    progress(f"  brackets: {len(brackets)} loaded")

    # ---- game changers: full refresh -----------------------------------
    source_tag = f"wotc-{gc_doc['updated']}"  # e.g. 'wotc-2026-02-09'
    conn.execute("DELETE FROM game_changers")
    conn.executemany(
        "INSERT INTO game_changers(name, source) VALUES(?, ?)",
        ((name, source_tag) for name in gc_cards),
    )
    progress(f"  game changers: {len(gc_cards)} loaded ({source_tag})")

    # ---- reconcile cards.is_game_changer -------------------------------
    # Curated list is additive-authoritative: set the flag for every named
    # card, but never clear flags Scryfall already set.
    placeholders = ", ".join("?" for _ in gc_cards)
    conn.execute(
        f"UPDATE cards SET is_game_changer = 1 WHERE name IN ({placeholders})",
        gc_cards,
    )
    cards_total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    if cards_total:
        matched = conn.execute(
            "SELECT COUNT(DISTINCT name) FROM cards "
            f"WHERE name IN ({placeholders})",
            gc_cards,
        ).fetchone()[0]
        unmatched = len(gc_cards) - matched
        if unmatched > 0:
            result.warnings.append(
                f"{unmatched} Game Changer name(s) matched no row in cards"
            )
            progress(f"  warning: {unmatched} name(s) not found in cards table")

    # ---- meta -----------------------------------------------------------
    set_meta(conn, f"{NAME}.updated_at", utcnow_iso())

    result.rows = len(brackets) + len(gc_cards)
    result.detail = f"{len(brackets)} brackets + {len(gc_cards)} game changers"
    return result
