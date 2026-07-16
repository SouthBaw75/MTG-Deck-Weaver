"""Builder upgrades: dynamic land count (matches the Mana Base analyzer),
auto-completion of combos at high brackets (pool-legal pieces only), and the
deck-level off-Arena flag surfaced to the API.
"""

from __future__ import annotations

import json

import pytest

from weaver.analysis.analyzers.manabase import recommend_land_count
from weaver.build.builder import _combo_completions
from weaver.build.types import BuildRequest, BuildResult, Candidate, SlotAssignment
from weaver.db.connection import connect
from weaver.db.schema import apply_schema
from weaver.knowledge.cardview import CardView


# ---- dynamic land count ----------------------------------------------------
def test_recommend_land_count_scales_with_curve_and_ramp():
    # Low curve, no ramp -> floor-ish; high curve -> more lands; ramp shaves.
    assert recommend_land_count(1.0, 0) == 34         # round(31+3)=34
    assert recommend_land_count(3.0, 0) == 40         # round(31+9)=40
    assert recommend_land_count(3.0, 14) == 36        # 40 - min(4,(14-2)//3)=40-4
    assert recommend_land_count(9.0, 0) == 42         # clamped to ceiling
    assert recommend_land_count(0.0, 0) == 33         # clamped to floor


# ---- combo auto-completion selection --------------------------------------
def _cand(name, games=("arena",)):
    return Candidate(
        name=name, oracle_id=name,
        card=CardView.from_dict({"name": name, "type_line": "Creature"}),
        tags={}, color_identity=["B"], mana_value=2.0, type_line="Creature",
        price_usd=None, edhrec_rank=1, is_game_changer=False, legal_commander="legal",
    )


def _seed_combo(conn, cid, cards):
    conn.execute(
        "INSERT INTO combos(id,description,produces,color_identity,card_count,spellbook_uri)"
        " VALUES(?,?,?,?,?,?)",
        (cid, "d", json.dumps(["Win"]), json.dumps(["B"]), len(cards), f"u/{cid}"),
    )
    for n in cards:
        conn.execute(
            "INSERT INTO combo_cards(combo_id,card_name,quantity,must_be_commander)"
            " VALUES(?,?,1,0)", (cid, n),
        )


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "b.db")
    apply_schema(c)
    _seed_combo(c, "combo-1", ["Have Piece", "Missing Finisher"])
    c.commit()
    return c


def _result_with(commander, assignment_names):
    cmd = _cand(commander)
    return BuildResult(
        request=BuildRequest(commander=commander, bracket=4),
        commander=cmd, partner=None,
        assignments=[SlotAssignment(_cand(n), "synergy", 1.0, "x") for n in assignment_names],
        lands=[], unfilled={},
    )


def test_combo_completion_adds_missing_pool_piece(conn):
    result = _result_with("Cmdr", ["Have Piece"])
    pool = [_cand("Missing Finisher"), _cand("Have Piece"), _cand("Filler")]
    picks = _combo_completions(conn, result, pool, result.request, max_add=3)
    assert picks == ["Missing Finisher"]


def test_combo_completion_skips_piece_not_in_pool(conn):
    # If the finisher isn't a pool candidate (off-color / off-Arena / over budget
    # filtered it out), it must not be added — this is the Arena safety.
    result = _result_with("Cmdr", ["Have Piece"])
    pool = [_cand("Have Piece"), _cand("Filler")]  # no "Missing Finisher"
    picks = _combo_completions(conn, result, pool, result.request, max_add=3)
    assert picks == []


def test_combo_completion_respects_max_add(conn):
    _seed_combo(conn, "combo-2", ["Have Piece", "Finisher Two"])
    _seed_combo(conn, "combo-3", ["Have Piece", "Finisher Three"])
    conn.commit()
    result = _result_with("Cmdr", ["Have Piece"])
    pool = [_cand("Missing Finisher"), _cand("Finisher Two"), _cand("Finisher Three")]
    picks = _combo_completions(conn, result, pool, result.request, max_add=2)
    assert len(picks) == 2


# ---- deck-level off-Arena flag --------------------------------------------
def test_analysis_payload_flags_off_arena_cards(tmp_path):
    from weaver.analysis.engine import analyze_deck
    from weaver.analysis.loader import load_deck
    from weaver.web.serialize import analysis_to_dict

    c = connect(tmp_path / "arena.db")
    apply_schema(c)
    for name, games in [("On Arena Card", ["arena", "paper"]),
                        ("Paper Only Card", ["paper", "mtgo"])]:
        c.execute(
            "INSERT INTO cards(oracle_id,name,type_line,oracle_text,color_identity,"
            "games,legal_commander,is_game_changer,edhrec_rank,mana_value) VALUES"
            "(?,?,'Creature','x','[\"B\"]',?,'legal',0,10,2)",
            (name, name, json.dumps(games)),
        )
    c.commit()
    deck = load_deck(c, "Deck\n1 On Arena Card\n1 Paper Only Card\n")
    payload = analysis_to_dict(deck, analyze_deck(deck))
    assert payload["off_arena"] == ["Paper Only Card"]
