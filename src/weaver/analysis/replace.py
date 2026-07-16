"""Find equivalent-power replacements for a card, restricted to legal options.

Given a loaded DeckView and a card the user wants out, suggest cards that:
  * fill the same functional role(s) (share a role/taxonomy tag),
  * sit within the deck's color identity,
  * are legal (never banned; on MTG Arena when `arena_only`),
  * aren't already in the deck (singleton),
ranked by role overlap, then mana-value closeness, then how played/strong the
card is (edhrec_rank, Game-Changer status). Pure given a connection: one DB read.
"""

from __future__ import annotations

import json
import sqlite3

_ROLE_PREFIXES = (
    "ramp", "draw", "removal", "wipe", "counter", "protection", "wincon",
    "tutor", "recursion", "sac", "token", "graveyard", "impulse", "extra-combat",
)


def _deck_identity(deck) -> set[str]:
    """The deck's color identity: the commander's, else the union of its cards'."""
    ci = {letter for c in deck.commanders for letter in (c.color_identity or [])}
    if ci:
        return ci
    return {letter for c in deck.cards for letter in (c.color_identity or [])}


def _row_on_arena(row) -> bool:
    try:
        raw = row["games"]
    except (IndexError, KeyError):
        return False
    if not raw:
        return False
    try:
        return "arena" in json.loads(raw)
    except (ValueError, TypeError):
        return False


def _target(deck, card_name: str):
    key = card_name.lower()
    for c in deck.cards:
        if c.name.lower() == key:
            return c
    return None


def find_replacements(
    conn: sqlite3.Connection,
    deck,
    card_name: str,
    *,
    arena_only: bool = False,
    count: int = 5,
) -> list[dict]:
    """Ranked legal replacements for `card_name`. Empty if the card isn't in the
    deck, carries no role tags, or nothing comparable is legal."""
    target = _target(deck, card_name)
    if target is None or not target.tags:
        return []

    target_tags = set(target.tags)
    deck_ci = _deck_identity(deck)
    in_deck = {c.name.lower() for c in deck.cards}
    target_mv = target.mana_value or 0.0

    # Candidate oracle_ids: cards that share at least one role tag with the target.
    placeholders = ",".join("?" for _ in target_tags)
    oracle_ids = [
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT oracle_id FROM card_tags WHERE tag IN ({placeholders})",
            list(target_tags),
        )
    ]
    if not oracle_ids:
        return []

    scored: list[tuple] = []
    for i in range(0, len(oracle_ids), 500):
        chunk = oracle_ids[i : i + 500]
        ph = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"SELECT * FROM cards WHERE oracle_id IN ({ph})", chunk
        ):
            name = row["name"]
            if name.lower() in in_deck:
                continue
            if row["legal_commander"] == "banned":
                continue
            card_ci = json.loads(row["color_identity"]) if row["color_identity"] else []
            if not set(card_ci).issubset(deck_ci):
                continue
            if arena_only and not _row_on_arena(row):
                continue
            cand_tags = {
                t["tag"]
                for t in conn.execute(
                    "SELECT tag FROM card_tags WHERE oracle_id = ?", (row["oracle_id"],)
                )
            }
            overlap = target_tags & cand_tags
            if not overlap:
                continue
            mv_gap = abs((row["mana_value"] or 0.0) - target_mv)
            rank = row["edhrec_rank"] if row["edhrec_rank"] is not None else 10_000_000
            # Rank: more shared roles, closer curve, then more-played/stronger.
            sort_key = (-len(overlap), mv_gap, rank)
            scored.append((sort_key, row, overlap))

    scored.sort(key=lambda t: t[0])
    out: list[dict] = []
    for _key, row, overlap in scored[:count]:
        role = _pretty_role(sorted(overlap)[0])
        mv = row["mana_value"] or 0.0
        gc = " · top-tier" if row["is_game_changer"] else ""
        out.append(
            {
                "name": row["name"],
                "reason": f"same role ({role}) · MV {_fmt_mv(mv)}{gc}",
                "mv": mv,
                "mv_label": _fmt_mv(mv),
                "type_line": row["type_line"] or "",
            }
        )
    return out


def _pretty_role(tag: str) -> str:
    return tag.split(".")[0].replace("-", " ") if any(
        tag.startswith(p) for p in _ROLE_PREFIXES
    ) else tag


def _fmt_mv(mv: float) -> str:
    return str(int(mv)) if float(mv).is_integer() else f"{mv:g}"
