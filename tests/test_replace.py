"""Replacement finder: legal, same-role, in-color, similar-power swaps."""

from __future__ import annotations

import json

import pytest

from weaver.analysis.loader import load_deck
from weaver.analysis.replace import find_replacements
from weaver.db.connection import connect
from weaver.db.schema import apply_schema
from weaver.knowledge.tagger import run_tagging


def _add(conn, name, mana_cost, mv, type_line, text, ci, games, edhrec=100, banned=False):
    conn.execute(
        "INSERT INTO cards(oracle_id,name,mana_cost,mana_value,type_line,oracle_text,"
        "color_identity,games,legal_commander,is_game_changer,edhrec_rank) "
        "VALUES(?,?,?,?,?,?,?,?,?,0,?)",
        (name, name, mana_cost, mv, type_line, text, json.dumps(ci), json.dumps(games),
         "banned" if banned else "legal", edhrec),
    )


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "r.db")
    apply_schema(c)
    # Target: a black creature-removal spell, on Arena.
    _add(c, "Go for the Throat", "{1}{B}", 2, "Instant",
         "Destroy target nonartifact creature.", ["B"], ["arena", "paper"], edhrec=50)
    # Good replacement: black removal, on Arena, in identity.
    _add(c, "Infernal Grasp", "{1}{B}", 2, "Instant",
         "Destroy target creature. You lose 2 life.", ["B"], ["arena", "paper"], edhrec=40)
    # Same role but NOT on Arena -> excluded when arena_only.
    _add(c, "Snuff Out", "{3}{B}", 4, "Instant",
         "Destroy target nonblack creature.", ["B"], ["paper", "mtgo"], edhrec=60)
    # Same role but OFF-COLOR (white) -> excluded (deck is mono-black).
    _add(c, "Swords to Plowshares", "{W}", 1, "Instant",
         "Exile target creature.", ["W"], ["arena", "paper"], edhrec=10)
    # Same role but BANNED -> excluded.
    _add(c, "Banned Removal", "{B}", 1, "Instant",
         "Destroy target creature.", ["B"], ["arena"], edhrec=5, banned=True)
    # Different role (ramp) -> excluded (no shared tag).
    _add(c, "Arcane Signet", "{2}", 2, "Artifact", "{T}: Add one mana of any color.",
         [], ["arena"], edhrec=1)
    c.commit()
    run_tagging(c)
    c.commit()
    return c


def _deck(conn):
    return load_deck(conn, "Commander\n1 Go for the Throat\nDeck\n1 Infernal Grasp\n")


def test_arena_only_excludes_off_arena_offcolor_and_banned(conn):
    # Replace an in-deck removal spell; ask for Arena-legal options.
    deck = load_deck(conn, "Deck\n1 Go for the Throat\n")
    reps = find_replacements(conn, deck, "Go for the Throat", arena_only=True, count=10)
    names = {r["name"] for r in reps}
    assert "Infernal Grasp" in names            # black removal, on Arena
    assert "Snuff Out" not in names             # not on Arena
    assert "Swords to Plowshares" not in names  # off-color for a mono-B deck
    assert "Banned Removal" not in names        # banned
    assert "Arcane Signet" not in names         # different role


def test_excludes_cards_already_in_deck(conn):
    deck = load_deck(conn, "Deck\n1 Go for the Throat\n1 Infernal Grasp\n")
    reps = find_replacements(conn, deck, "Go for the Throat", arena_only=True, count=10)
    assert "Infernal Grasp" not in {r["name"] for r in reps}  # already in the deck


def test_non_arena_mode_allows_more(conn):
    deck = load_deck(conn, "Deck\n1 Go for the Throat\n")
    reps = find_replacements(conn, deck, "Go for the Throat", arena_only=False, count=10)
    names = {r["name"] for r in reps}
    assert "Snuff Out" in names  # off-Arena is fine when not restricting to Arena


def test_unknown_card_returns_empty(conn):
    deck = load_deck(conn, "Deck\n1 Go for the Throat\n")
    assert find_replacements(conn, deck, "Not In Deck", arena_only=False) == []


def test_shape_has_reason_and_mv(conn):
    deck = load_deck(conn, "Deck\n1 Go for the Throat\n")
    reps = find_replacements(conn, deck, "Go for the Throat", arena_only=True, count=3)
    assert reps and all(set(r) >= {"name", "reason", "mv", "mv_label", "type_line"} for r in reps)
