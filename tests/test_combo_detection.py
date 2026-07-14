"""Combo detection: matching logic, loader wiring, and the combo analyzer."""

from __future__ import annotations

import json

from weaver.analysis.combos import match_combos, detect_deck_combos
from weaver.analysis.analyzers import combo as combo_analyzer
from weaver.db.connection import connect
from weaver.db.schema import apply_schema
from weaver.analysis.loader import load_deck
from deck_fixtures import make_card, make_deck

COMBOS = [
    {
        "id": "c1",
        "cards": ["Basalt Monolith", "Rings of Brighthearth"],
        "produces": ["Infinite colorless mana"],
        "description": "Tap for 3, untap paying 3+2 copies...",
        "color_identity": [],
        "spellbook_uri": "https://commanderspellbook.com/combo/c1/",
    },
    {
        "id": "c2",
        "cards": ["Thassa's Oracle", "Demonic Consultation"],
        "produces": ["Win the game"],
        "description": "Exile library, then win with Oracle.",
        "color_identity": ["U", "B"],
        "spellbook_uri": "https://commanderspellbook.com/combo/c2/",
    },
    {
        "id": "c3",
        "cards": ["Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"],
        "produces": ["Infinite hasty creatures"],
        "description": "Copy Conscripts, untap Kiki, repeat.",
        "color_identity": ["R"],
        "spellbook_uri": "https://commanderspellbook.com/combo/c3/",
    },
]


def test_present_combo_detected():
    names = {"Basalt Monolith", "Rings of Brighthearth", "Sol Ring"}
    present, near = match_combos(names, COMBOS)
    assert [m.combo_id for m in present] == ["c1"]
    assert present[0].is_present


def test_near_miss_within_identity():
    # Have Thassa's Oracle but not Demonic Consultation; deck is UB.
    names = {"Thassa's Oracle"}
    present, near = match_combos(names, COMBOS, deck_color_identity={"U", "B"})
    assert not present
    ids = [m.combo_id for m in near]
    assert "c2" in ids
    c2 = next(m for m in near if m.combo_id == "c2")
    assert c2.missing == ["Demonic Consultation"]


def test_near_miss_filtered_by_color_identity():
    # Have Kiki-Jiki but deck is mono-blue: the red combo must NOT be suggested.
    names = {"Kiki-Jiki, Mirror Breaker"}
    present, near = match_combos(names, COMBOS, deck_color_identity={"U"})
    assert "c3" not in [m.combo_id for m in near]


def test_case_insensitive_matching():
    names = {"basalt monolith", "RINGS OF BRIGHTHEARTH"}
    present, _ = match_combos(names, COMBOS)
    assert [m.combo_id for m in present] == ["c1"]


def test_two_cards_missing_is_not_near_miss():
    present, near = match_combos({"Sol Ring"}, COMBOS, deck_color_identity={"U", "B", "R"})
    assert not present
    assert not near  # every combo is 2 cards short, not 1


def _seed_db(tmp_path):
    conn = connect(tmp_path / "c.db")
    apply_schema(conn)
    cards = [
        ("o1", "Basalt Monolith", "Artifact", "[]"),
        ("o2", "Rings of Brighthearth", "Artifact", "[]"),
        ("o3", "Thassa's Oracle", "Creature — Merfolk Wizard", '["U"]'),
        ("o4", "Sol Ring", "Artifact", "[]"),
        ("cmd", "Urza, Lord High Artificer", "Legendary Creature", '["U"]'),
    ]
    for oid, name, tl, ci in cards:
        conn.execute(
            "INSERT INTO cards(oracle_id,name,type_line,mana_value,color_identity,"
            "legal_commander,is_game_changer) VALUES(?,?,?,0,?,'legal',0)",
            (oid, name, tl, ci),
        )
    conn.execute(
        "INSERT INTO combos(id,description,produces,color_identity,spellbook_uri)"
        " VALUES('c1','desc',?,'[]','uri')",
        (json.dumps(["Infinite colorless mana"]),),
    )
    for cid, cname in [("c1", "Basalt Monolith"), ("c1", "Rings of Brighthearth")]:
        conn.execute(
            "INSERT INTO combo_cards(combo_id,card_name,quantity,must_be_commander)"
            " VALUES(?,?,1,0)",
            (cid, cname),
        )
    conn.commit()
    return conn


def test_loader_attaches_present_combo(tmp_path):
    conn = _seed_db(tmp_path)
    deck = load_deck(conn, "Commander\n1 Urza, Lord High Artificer\nDeck\n"
                           "1 Basalt Monolith\n1 Rings of Brighthearth\n1 Sol Ring\n")
    assert len(deck.combos_present) == 1
    assert deck.combos_present[0].combo_id == "c1"


def test_combo_analyzer_formats_present(tmp_path):
    conn = _seed_db(tmp_path)
    deck = load_deck(conn, "1 Basalt Monolith\n1 Rings of Brighthearth\n")
    section = combo_analyzer.analyze(deck)
    assert section.data["present_count"] == 1
    assert any("Basalt Monolith" in f.message for f in section.findings)


def test_combo_analyzer_handles_empty():
    deck = make_deck([make_card("Sol Ring", type_line="Artifact")])
    section = combo_analyzer.analyze(deck)
    assert section.data["present_count"] == 0
    assert section.findings  # emits the "no combos / empty db" note
