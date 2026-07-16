"""Alchemy rebalanced cards ("A-Spell Satchel") are the same card as their
original in MTG Arena. A deck must not run both, or Arena merges them on import
and the deck lands a card short (the "98 cards" bug). The builder dedups them
and the legality analyzer flags them.
"""

from __future__ import annotations

import pytest

from weaver.analysis.analyzers import legality
from weaver.analysis.loader import load_deck
from weaver.build.assembler import assemble
from weaver.build.pool import build_pool
from weaver.build.scoring import score_pool
from weaver.build.templates import template_for_bracket
from weaver.build.types import BuildRequest
from weaver.db.connection import connect
from weaver.db.schema import apply_schema
from weaver.knowledge.cardview import canonical_card_name


@pytest.mark.parametrize("name, expected", [
    ("A-Spell Satchel", "Spell Satchel"),
    ("a-mischievous catgeist", "mischievous catgeist"),
    ("Spell Satchel", "Spell Satchel"),
    ("Ajani's Pridemate", "Ajani's Pridemate"),   # not an "A-" prefix
    ("A-", "A-"),                                   # too short to strip
])
def test_canonical_name(name, expected):
    assert canonical_card_name(name) == expected


def _add(conn, oid, name, ci=("U",), tl="Artifact", txt="draw a card"):
    conn.execute(
        "INSERT INTO cards(oracle_id,name,type_line,oracle_text,color_identity,games,"
        "legal_commander,is_game_changer,edhrec_rank,mana_value) VALUES(?,?,?,?,?,'[\"arena\"]','legal',0,10,2)",
        (oid, name, tl, txt, __import__("json").dumps(list(ci))),
    )


def test_legality_flags_alchemy_duplicate():
    conn = connect(":memory:")
    apply_schema(conn)
    _add(conn, "ss", "Spell Satchel")
    _add(conn, "ass", "A-Spell Satchel")
    _add(conn, "sr", "Sol Ring")
    conn.commit()
    deck = load_deck(conn, "Deck\n1 Spell Satchel\n1 A-Spell Satchel\n1 Sol Ring\n")
    section = legality.analyze(deck)
    assert any("Alchemy" in f.message and f.severity == "problem" for f in section.findings)
    assert section.data["violations"].get("alchemy_duplicates")


def test_builder_never_includes_both_versions():
    conn = connect(":memory:")
    apply_schema(conn)
    _add(conn, "cmd", "Cmdr", tl="Legendary Creature")
    _add(conn, "ss", "Spell Satchel")
    _add(conn, "ass", "A-Spell Satchel")
    for i in range(60):
        _add(conn, f"f{i}", f"Filler {i}")
    conn.commit()
    c, p, pool = build_pool(conn, BuildRequest(commander="Cmdr", arena_only=True))
    score_pool(pool, BuildRequest(commander="Cmdr"), {}, {})
    result = assemble(c, p, pool, BuildRequest(commander="Cmdr", bracket=3), template_for_bracket(3))
    names = [a.candidate.name for a in result.assignments]
    assert not ("Spell Satchel" in names and "A-Spell Satchel" in names)
