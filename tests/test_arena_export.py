"""Arena-safe decklist export: multi-face cards must use the name MTG Arena's
importer accepts (front face for DFC/transform/adventure; full "A // B" for
split/aftermath). Regression for the "unknown card title: Front // Back" import
error.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import json

from weaver.analysis.loader import load_deck
from weaver.build.types import BuildRequest, BuildResult, Candidate, SlotAssignment
from weaver.db.connection import connect
from weaver.db.schema import apply_schema
from weaver.knowledge.cardview import export_card_name


@pytest.mark.parametrize(
    "name, layout, expected",
    [
        # DFC / transform families -> front face only (what Arena wants).
        ("Jerren, Corrupted Bishop // Ormendahl, the Corrupter", "transform", "Jerren, Corrupted Bishop"),
        ("Malakir Rebirth // Malakir Mire", "modal_dfc", "Malakir Rebirth"),
        ("Brazen Borrower // Petty Theft", "adventure", "Brazen Borrower"),
        ("Akki Lavarunner // Tok-Tok, Volcano Born", "flip", "Akki Lavarunner"),
        ("Hanweir Battlements // Hanweir, the Writhing Township", "meld", "Hanweir Battlements"),
        # Split / aftermath -> keep the whole name (one castable object).
        ("Fire // Ice", "split", "Fire // Ice"),
        ("Commit // Memory", "aftermath", "Commit // Memory"),
        # Single-face cards are untouched.
        ("Sol Ring", "normal", "Sol Ring"),
        ("Lightning Bolt", "", "Lightning Bolt"),
        # Missing/unknown layout but a combined name -> front face (Arena-safe default).
        ("Jerren, Corrupted Bishop // Ormendahl, the Corrupter", None, "Jerren, Corrupted Bishop"),
        ("Some Card // Other Side", "", "Some Card"),
    ],
)
def test_export_card_name(name, layout, expected):
    assert export_card_name(name, layout) == expected


def _cand(name, layout="", type_line="Creature"):
    return Candidate(
        name=name, oracle_id=name, card=None, tags={}, color_identity=[],
        mana_value=2.0, type_line=type_line, price_usd=None, edhrec_rank=1,
        is_game_changer=False, legal_commander="legal", layout=layout,
    )


def test_to_decklist_uses_arena_safe_names():
    result = BuildResult(
        request=BuildRequest(commander="Jerren, Corrupted Bishop // Ormendahl, the Corrupter"),
        commander=_cand("Jerren, Corrupted Bishop // Ormendahl, the Corrupter", "transform",
                        "Legendary Creature — Human Cleric"),
        partner=None,
        assignments=[
            SlotAssignment(_cand("Brazen Borrower // Petty Theft", "adventure"), "wincon", 1.0, "flyer"),
            SlotAssignment(_cand("Fire // Ice", "split", "Instant // Instant"), "spot_removal", 1.0, "flex"),
            SlotAssignment(_cand("Sol Ring", "normal", "Artifact"), "ramp", 1.0, "fast mana"),
        ],
        lands=[SlotAssignment(_cand("Swamp", "normal", "Basic Land — Swamp"), "land", 1.0, "", quantity=10)],
        unfilled={},
    )
    dl = result.to_decklist()
    # DFC commander + adventure -> front face; split stays whole; normal untouched.
    assert "1 Jerren, Corrupted Bishop" in dl
    assert "Ormendahl, the Corrupter" not in dl
    assert "1 Brazen Borrower" in dl and "Petty Theft" not in dl
    assert "1 Fire // Ice" in dl
    assert "10 Swamp" in dl


def test_front_face_export_round_trips_through_importer(tmp_path):
    """An Arena-safe front-face name must still resolve to the full DFC card when
    the exported list is re-imported into the weaver (Analyze)."""
    conn = connect(tmp_path / "rt.db")
    apply_schema(conn)
    conn.execute(
        "INSERT INTO cards(oracle_id,name,layout,type_line,oracle_text,color_identity,"
        "legal_commander,is_game_changer,edhrec_rank,mana_value) VALUES"
        "('o1','Jerren, Corrupted Bishop // Ormendahl, the Corrupter','transform',"
        "'Legendary Creature — Human Cleric','x',?,'legal',0,100,3)",
        (json.dumps(["B"]),),
    )
    conn.commit()
    deck = load_deck(conn, "Commander\n1 Jerren, Corrupted Bishop\n")
    jerren = deck.cards[0]
    assert jerren.resolved
    assert jerren.name == "Jerren, Corrupted Bishop // Ormendahl, the Corrupter"
