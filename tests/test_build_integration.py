"""End-to-end deck builder test: seed a pool, build a deck, validate it.

Uses a procedurally-generated candidate pool so the assembler has enough tagged
cards to fill a bracket-3 template, then checks the result is a legal 100-card
singleton deck within the commander's colors, and that it survives the Phase 2
analyzer.
"""

from __future__ import annotations

import pytest

from weaver.analysis.engine import analyze_deck
from weaver.analysis.loader import load_deck
from weaver.build.builder import build_deck
from weaver.build.types import BuildRequest
from weaver.db.connection import connect
from weaver.db.schema import apply_schema

# role group -> a representative taxonomy tag the assembler will look for
GROUP_TAG = {
    "ramp": "ramp.rock",
    "card_advantage": "draw.engine",
    "spot_removal": "removal.spot.creature",
    "board_wipe": "wipe.creature",
    "targeted_disruption": "counterspell",
    "protection": "protection.self",
    "wincon": "wincon.combat",
}
# BG identities to spread across the pool
_IDS = [["B"], ["G"], ["B", "G"], []]


@pytest.fixture()
def built_db(tmp_path):
    conn = connect(tmp_path / "build.db")
    apply_schema(conn)

    def add(oid, name, tl, ci, tag=None, rank=None, price=None, gc=0, banned=False, mc=""):
        conn.execute(
            "INSERT INTO cards(oracle_id,name,mana_cost,mana_value,type_line,oracle_text,"
            "color_identity,legal_commander,is_game_changer,edhrec_rank,price_usd)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (oid, name, mc, 3, tl, "", __import__("json").dumps(ci),
             "banned" if banned else "legal", gc, rank, price),
        )
        if tag:
            conn.execute(
                "INSERT INTO card_tags(oracle_id,tag,quality,source) VALUES(?,?,?,'pattern')",
                (oid, tag, 0.8),
            )

    # commander: BG legendary creature
    add("cmd", "Test Commander", "Legendary Creature — Elf Shaman", ["B", "G"])
    # 14 cards per role group, spread across BG identities
    i = 0
    for group, tag in GROUP_TAG.items():
        for k in range(14):
            ci = _IDS[k % len(_IDS)]
            add(f"o{i}", f"{group.title()} {k:02d}", "Creature — Elf", ci, tag=tag,
                rank=100 + i, mc="{1}{G}{B}")
            i += 1
    # a few generic synergy cards (no role tag) to feed the flex slots
    for k in range(20):
        add(f"syn{k}", f"Synergy {k:02d}", "Creature — Elf", _IDS[k % len(_IDS)],
            rank=500 + k, mc="{2}{G}")
    # off-color card that MUST be filtered out
    add("offc", "Blue Intruder", "Creature — Merfolk", ["U"], tag="ramp.rock")
    # banned card that MUST be excluded
    add("ban", "Banned Thing", "Artifact", [], tag="ramp.rock", banned=True)
    # a couple of on-color utility lands
    add("land1", "Golgari Utility Land", "Land", ["B", "G"], tag="land.utility", rank=800)
    conn.commit()
    return conn


def test_builds_legal_100_card_deck(built_db):
    result = build_deck(built_db, BuildRequest(commander="Test Commander", bracket=3))
    assert result.total_cards == 100, result.notes

    # singleton: no nonland name repeats
    nonland_names = [a.candidate.name for a in result.assignments]
    assert len(nonland_names) == len(set(nonland_names))

    # commander is not in the deck body
    assert "Test Commander" not in nonland_names

    # every nonland pick is within the commander's BG identity
    for a in result.assignments:
        assert set(a.candidate.color_identity).issubset({"B", "G"}), a.candidate.name

    # the off-color and banned cards never made it in
    assert "Blue Intruder" not in nonland_names
    assert "Banned Thing" not in nonland_names


def test_built_deck_passes_analysis(built_db):
    result = build_deck(built_db, BuildRequest(commander="Test Commander", bracket=3))
    deck = load_deck(built_db, result.to_decklist())
    sections = {s.title: s for s in analyze_deck(deck)}
    # Legal size and identity per the legality analyzer.
    legality = sections["Legality & Bracket"].data
    assert legality["deck_size"] == 100
    assert not legality["violations"].get("color_identity")
    assert not legality["violations"].get("banned")
    assert not legality["violations"].get("singleton")


def test_budget_is_respected(built_db):
    # Give every role card a price; cap the budget and confirm we stay under it.
    built_db.execute("UPDATE cards SET price_usd = 5 WHERE price_usd IS NULL")
    built_db.commit()
    result = build_deck(built_db, BuildRequest(commander="Test Commander", bracket=3, budget=150.0))
    spent = sum(a.candidate.price_usd or 0 for a in result.all_cards)
    assert spent <= 150.0


def test_bracket_gc_cap(built_db):
    # Flag several cards as Game Changers; bracket 2 allows zero.
    built_db.execute("UPDATE cards SET is_game_changer = 1 WHERE oracle_id IN ('o0','o1','o2','o3')")
    built_db.commit()
    result = build_deck(built_db, BuildRequest(commander="Test Commander", bracket=2))
    gc = [a.candidate.name for a in result.assignments if a.candidate.is_game_changer]
    assert gc == [], f"bracket 2 admits no Game Changers, got {gc}"
