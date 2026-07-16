"""Near-miss combos carry the Arena legality of their missing card, so an
Arena-legal deck can be warned before adding an off-Arena upgrade piece.
"""

from __future__ import annotations

import json

import pytest

from weaver.analysis.combos import detect_deck_combos
from weaver.analysis.loader import load_deck
from weaver.db.connection import connect
from weaver.db.schema import apply_schema


def _card(conn, name, games, ci="[]"):
    conn.execute(
        "INSERT INTO cards(oracle_id,name,type_line,oracle_text,color_identity,"
        "games,legal_commander,is_game_changer,edhrec_rank,mana_value) VALUES"
        "(?,?,'Creature','x',?,?,'legal',0,10,2)",
        (name, name, ci, json.dumps(games)),
    )


def _combo(conn, cid, cards):
    conn.execute(
        "INSERT INTO combos(id,description,produces,color_identity,card_count,spellbook_uri)"
        " VALUES(?,?,?,'[]',?,?)",
        (cid, f"{cid} desc", json.dumps(["Win the game"]), len(cards), f"uri/{cid}"),
    )
    for n in cards:
        conn.execute(
            "INSERT INTO combo_cards(combo_id,card_name,quantity,must_be_commander)"
            " VALUES(?,?,1,0)", (cid, n),
        )


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "a.db")
    apply_schema(c)
    _card(c, "Have Piece", ["arena", "paper"])
    _card(c, "Arena Missing", ["arena", "paper"])
    _card(c, "Paper Missing", ["paper", "mtgo"])
    _combo(c, "combo-arena", ["Have Piece", "Arena Missing"])
    _combo(c, "combo-paper", ["Have Piece", "Paper Missing"])
    c.commit()
    return c


def test_near_miss_flags_arena_legality(conn):
    deck = load_deck(conn, "Deck\n1 Have Piece\n")
    _present, near = detect_deck_combos(conn, deck)
    by_missing = {m.missing[0]: m.missing_arena for m in near}
    assert by_missing == {"Arena Missing": True, "Paper Missing": False}


def test_missing_card_absent_from_db_is_not_arena(conn):
    # A combo whose missing piece isn't in the cards table at all -> not on Arena.
    _combo(conn, "combo-ghost", ["Have Piece", "Nonexistent Card"])
    conn.commit()
    deck = load_deck(conn, "Deck\n1 Have Piece\n")
    _present, near = detect_deck_combos(conn, deck)
    ghost = next(m for m in near if m.combo_id == "combo-ghost")
    assert ghost.missing_arena is False


def test_analyzer_exposes_arena_legal_in_section_data(conn):
    from weaver.analysis.analyzers import combo as combo_analyzer

    deck = load_deck(conn, "Deck\n1 Have Piece\n")
    deck.combos_present, deck.combos_near_miss = detect_deck_combos(conn, deck)
    section = combo_analyzer.analyze(deck)
    flags = {nm["missing"][0]: nm["arena_legal"] for nm in section.data["near_miss"]}
    assert flags == {"Arena Missing": True, "Paper Missing": False}
