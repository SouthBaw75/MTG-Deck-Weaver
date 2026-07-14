"""Build a resolved DeckView from decklist text against the knowledge base."""

from __future__ import annotations

import json
import sqlite3

from weaver.analysis.deck import DeckCard, DeckView, parse_decklist
from weaver.knowledge.cardview import CardView


def _resolve_row(conn: sqlite3.Connection, name: str):
    """Find a cards row by name, tolerant of DFC/split half-names."""
    row = conn.execute(
        "SELECT * FROM cards WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        return row
    # A half-name of a multi-face card ("Fire" -> "Fire // Ice").
    row = conn.execute(
        "SELECT * FROM cards WHERE name LIKE ? COLLATE NOCASE "
        "AND name LIKE '% // %' ORDER BY length(name) LIMIT 1",
        (f"{name} // %",),
    ).fetchone()
    if row:
        return row
    row = conn.execute(
        "SELECT * FROM cards WHERE name LIKE ? COLLATE NOCASE "
        "AND name LIKE '% // %' ORDER BY length(name) LIMIT 1",
        (f"% // {name}",),
    ).fetchone()
    return row


def load_deck(conn: sqlite3.Connection, text: str) -> DeckView:
    entries = parse_decklist(text)
    cards: list[DeckCard] = []
    unresolved: list[str] = []
    for entry in entries:
        row = _resolve_row(conn, entry.name)
        if row is None:
            unresolved.append(entry.name)
            cards.append(DeckCard(entry.quantity, entry.name, entry.is_commander, None))
            continue

        tags = {
            t["tag"]: t["quality"]
            for t in conn.execute(
                "SELECT tag, quality FROM card_tags WHERE oracle_id = ?",
                (row["oracle_id"],),
            )
        }
        cards.append(
            DeckCard(
                quantity=entry.quantity,
                name=row["name"],
                is_commander=entry.is_commander,
                card=CardView.from_row(row),
                tags=tags,
                mana_value=row["mana_value"] or 0.0,
                type_line=row["type_line"] or "",
                color_identity=json.loads(row["color_identity"]) if row["color_identity"] else [],
                legal_commander=row["legal_commander"],
                is_game_changer=bool(row["is_game_changer"]),
            )
        )
    deck = DeckView(cards=cards, unresolved=unresolved)

    # Attach combo detection when the mirror is populated. Non-fatal: a deck
    # still analyzes fine if the combos tables are empty.
    try:
        from weaver.analysis.combos import detect_deck_combos

        if conn.execute("SELECT 1 FROM combos LIMIT 1").fetchone():
            present, near = detect_deck_combos(conn, deck)
            deck.combos_present = present
            deck.combos_near_miss = near
    except sqlite3.Error:
        pass
    return deck
