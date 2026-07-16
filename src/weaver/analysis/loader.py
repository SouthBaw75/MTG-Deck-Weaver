"""Build a resolved DeckView from decklist text against the knowledge base."""

from __future__ import annotations

import json
import sqlite3

from weaver.analysis.deck import DeckCard, DeckView, parse_decklist
from weaver.knowledge.cardview import CardView


def _row_on_arena(row) -> bool:
    """Whether a resolved card is on MTG Arena (Scryfall `games` + overrides)."""
    from weaver.knowledge.arena import is_on_arena

    try:
        raw = row["games"]
    except (IndexError, KeyError):
        raw = None
    return is_on_arena(row["name"], raw)


def _resolve_row(conn: sqlite3.Connection, name: str):
    """Find a cards row by name, tolerant of DFC/split names in either direction:
    a half-name ("Fire" -> "Fire // Ice"), or a full combined name whose card the
    DB stores under a single face ("Bilbo, Luckwearer // Burglar's Plot" ->
    "Bilbo, Luckwearer")."""
    row = conn.execute(
        "SELECT * FROM cards WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        return row

    def _by_half(half: str):
        r = conn.execute(
            "SELECT * FROM cards WHERE name = ? COLLATE NOCASE", (half,)
        ).fetchone()
        if r:
            return r
        r = conn.execute(
            "SELECT * FROM cards WHERE name LIKE ? COLLATE NOCASE "
            "AND name LIKE '% // %' ORDER BY length(name) LIMIT 1",
            (f"{half} // %",),
        ).fetchone()
        if r:
            return r
        return conn.execute(
            "SELECT * FROM cards WHERE name LIKE ? COLLATE NOCASE "
            "AND name LIKE '% // %' ORDER BY length(name) LIMIT 1",
            (f"% // {half}",),
        ).fetchone()

    # A combined "A // B" name: try each face. Also covers a bare half-name.
    for face in (name.split(" // ") if " // " in name else [name]):
        row = _by_half(face.strip())
        if row:
            return row
    return None


def _diagnose_unresolved(conn: sqlite3.Connection, name: str) -> dict:
    """Explain why a card didn't match and point at the closest thing we have,
    so the user (or a maintainer) can tell a typo from a data gap from a bug."""
    # Fuzzy suggestion: match on the significant leading token (pre-comma,
    # front face), then fall back to just the first word so a small typo like
    # "Sol Rng" still points at "Sol Ring".
    def _closest(fragment: str):
        fragment = fragment.strip()
        if len(fragment) < 3:
            return None
        row = conn.execute(
            "SELECT name FROM cards WHERE name LIKE ? COLLATE NOCASE "
            "ORDER BY (edhrec_rank IS NULL), edhrec_rank LIMIT 1",
            (f"%{fragment}%",),
        ).fetchone()
        if row and row["name"].lower() != name.lower():
            return row["name"]
        return None

    token = name.split("//")[0].split(",")[0].strip()
    suggestion = _closest(token) or _closest(token.split()[0] if token.split() else "")
    if suggestion:
        reason = "closest match in your database (possible typo or naming variant)"
    elif " // " in name or "/" in name:
        reason = "multi-face name not found under either face — may be a data gap"
    else:
        reason = "not in the card database — try `weaver update`, or check the spelling"
    return {"name": name, "reason": reason, "suggestion": suggestion}


def load_deck(conn: sqlite3.Connection, text: str) -> DeckView:
    entries = parse_decklist(text)
    cards: list[DeckCard] = []
    unresolved: list[str] = []
    unresolved_detail: list[dict] = []
    for entry in entries:
        row = _resolve_row(conn, entry.name)
        if row is None:
            unresolved.append(entry.name)
            unresolved_detail.append(_diagnose_unresolved(conn, entry.name))
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
                price_usd=row["price_usd"],
                on_arena=_row_on_arena(row),
            )
        )
    deck = DeckView(cards=cards, unresolved=unresolved, unresolved_detail=unresolved_detail)

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
