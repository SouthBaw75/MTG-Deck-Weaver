"""Combo detection: match a deck against the Commander Spellbook mirror.

Given the set of card names in a deck, this finds:
  - combos fully PRESENT (every card of the combo is in the deck)
  - combos ONE CARD AWAY (all but exactly one card present) whose missing card
    is legal in the deck's color identity, so the suggestion is actionable

The matching logic is separated from the DB query so it can be unit-tested with
a plain list of combo dicts (no database needed).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass
class ComboMatch:
    combo_id: str
    cards: list[str]
    produces: list[str]
    description: str
    color_identity: list[str]
    spellbook_uri: str
    missing: list[str] = field(default_factory=list)  # empty => fully present
    # For a near-miss: is the single missing card available on MTG Arena?
    # None = not queried (present combos, or no DB lookup done).
    missing_arena: bool | None = None

    @property
    def is_present(self) -> bool:
        return not self.missing


def _within_identity(combo_ci: list[str], deck_ci: set[str]) -> bool:
    """A missing card is only addable if the whole combo fits the deck's
    color identity (combo color identity ⊆ commander color identity)."""
    return set(combo_ci or []).issubset(deck_ci)


def match_combos(
    deck_card_names: set[str],
    combos: list[dict],
    *,
    deck_color_identity: set[str] | None = None,
) -> tuple[list[ComboMatch], list[ComboMatch]]:
    """Return (present, near_miss).

    Each combo dict: {id, cards: [names], produces: [names], description,
    color_identity: [letters], spellbook_uri}. Names are compared
    case-insensitively.
    """
    names_lower = {n.lower() for n in deck_card_names}
    present: list[ComboMatch] = []
    near: list[ComboMatch] = []

    for c in combos:
        cards = c.get("cards", [])
        if not cards:
            continue
        missing = [n for n in cards if n.lower() not in names_lower]
        match = ComboMatch(
            combo_id=str(c.get("id", "")),
            cards=cards,
            produces=c.get("produces", []),
            description=c.get("description", ""),
            color_identity=c.get("color_identity", []),
            spellbook_uri=c.get("spellbook_uri", ""),
            missing=missing,
        )
        if not missing:
            present.append(match)
        elif len(missing) == 1:
            if deck_color_identity is None or _within_identity(
                match.color_identity, deck_color_identity
            ):
                near.append(match)
    # Most "complete" and popular first: present already complete; near-miss
    # ordered so bigger combos (more owned pieces) surface first.
    near.sort(key=lambda m: len(m.cards), reverse=True)
    return present, near


def load_combo_index(conn: sqlite3.Connection, deck_card_names: set[str]) -> list[dict]:
    """Pull only the combos relevant to this deck: any combo that shares at
    least one card name with the deck. Keeps matching fast on a 30k-combo DB.
    """
    if not deck_card_names:
        return []
    placeholders = ",".join("?" for _ in deck_card_names)
    # Combo ids that reference any deck card.
    rows = conn.execute(
        f"SELECT DISTINCT combo_id FROM combo_cards "
        f"WHERE card_name IN ({placeholders}) COLLATE NOCASE",
        list(deck_card_names),
    ).fetchall()
    combo_ids = [r[0] for r in rows]
    if not combo_ids:
        return []

    out: list[dict] = []
    # Fetch in chunks to stay under SQLite's variable limit.
    for i in range(0, len(combo_ids), 500):
        chunk = combo_ids[i : i + 500]
        ph = ",".join("?" for _ in chunk)
        combo_rows = conn.execute(
            f"SELECT id, description, produces, color_identity, spellbook_uri "
            f"FROM combos WHERE id IN ({ph})",
            chunk,
        ).fetchall()
        for cr in combo_rows:
            card_rows = conn.execute(
                "SELECT card_name FROM combo_cards WHERE combo_id = ?", (cr["id"],)
            ).fetchall()
            out.append(
                {
                    "id": cr["id"],
                    "description": cr["description"] or "",
                    "produces": json.loads(cr["produces"]) if cr["produces"] else [],
                    "color_identity": json.loads(cr["color_identity"]) if cr["color_identity"] else [],
                    "spellbook_uri": cr["spellbook_uri"] or "",
                    "cards": [row["card_name"] for row in card_rows],
                }
            )
    return out


def _card_on_arena(conn: sqlite3.Connection, name: str) -> bool:
    """Whether a card is available on MTG Arena (Scryfall `games` + curated
    overrides). Tolerant of DFC/split half-names, like the loader."""
    from weaver.knowledge.arena import is_on_arena

    row = conn.execute(
        "SELECT name, games FROM cards WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT name, games FROM cards WHERE name LIKE ? COLLATE NOCASE "
            "AND name LIKE '% // %' ORDER BY length(name) LIMIT 1",
            (f"{name} // %",),
        ).fetchone()
    if row is None:
        return is_on_arena(name, None)
    return is_on_arena(row["name"], row["games"])


def detect_deck_combos(conn: sqlite3.Connection, deck) -> tuple[list[ComboMatch], list[ComboMatch]]:
    """Convenience: pull the combo index for a DeckView and match it."""
    names = {c.name for c in deck.cards}
    deck_ci = {
        letter for c in deck.commanders for letter in (c.color_identity or [])
    }
    combos = load_combo_index(conn, names)
    present, near = match_combos(names, combos, deck_color_identity=deck_ci or None)
    # Annotate each near-miss with whether its single missing card is on Arena,
    # so an Arena-legal deck can be warned before adding an off-Arena upgrade.
    for m in near:
        if m.missing:
            m.missing_arena = _card_on_arena(conn, m.missing[0])
    return present, near
