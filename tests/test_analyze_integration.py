"""End-to-end Phase 2 test: build a small DB, tag it, load a decklist, and run
the full analyzer stack, asserting every section reports sensibly."""

from __future__ import annotations

import json

import pytest

from weaver.analysis.engine import analyze_deck
from weaver.analysis.loader import load_deck
from weaver.db.connection import connect
from weaver.db.schema import apply_schema
from weaver.knowledge.tagger import run_tagging

# (name, mana_cost, mv, type_line, oracle_text, color_identity, is_land)
CARDS = [
    ("Tovolar, Dire Overlord", "{1}{R}{G}", 3, "Legendary Creature — Human Werewolf",
     "Whenever a Wolf or Werewolf you control deals combat damage to a player, draw a card.", ["R", "G"], False),
    ("Sol Ring", "{1}", 1, "Artifact", "{T}: Add {C}{C}.", [], False),
    ("Cultivate", "{2}{G}", 3, "Sorcery",
     "Search your library for up to two basic land cards, reveal those cards, and put one onto the battlefield tapped and the other into your hand. Then shuffle.", ["G"], False),
    ("Llanowar Elves", "{G}", 1, "Creature — Elf Druid", "{T}: Add {G}.", ["G"], False),
    ("Lightning Bolt", "{R}", 1, "Instant", "Lightning Bolt deals 3 damage to any target.", ["R"], False),
    ("Beast Within", "{2}{G}", 3, "Instant",
     "Destroy target permanent. Its controller creates a 3/3 green Beast creature token.", ["G"], False),
    ("Blasphemous Act", "{8}{R}", 9, "Sorcery",
     "This spell costs {1} less to cast for each creature on the battlefield.\nBlasphemous Act deals 13 damage to each creature.", ["R"], False),
    ("Harmonize", "{2}{G}{G}", 4, "Sorcery", "Draw three cards.", ["G"], False),
    ("Craterhoof Behemoth", "{5}{G}{G}{G}", 8, "Creature — Beast",
     "Haste\nWhen Craterhoof Behemoth enters the battlefield, creatures you control gain trample and get +X/+X until end of turn, where X is the number of creatures you control.", ["G"], False),
    ("Forest", "", 0, "Basic Land — Forest", "({T}: Add {G}.)", ["G"], True),
    ("Mountain", "", 0, "Basic Land — Mountain", "({T}: Add {R}.)", ["R"], True),
]


@pytest.fixture()
def deck_db(tmp_path):
    conn = connect(tmp_path / "deck.db")
    apply_schema(conn)
    for i, (name, mc, mv, tl, txt, ci, _land) in enumerate(CARDS):
        conn.execute(
            "INSERT INTO cards(oracle_id, name, mana_cost, mana_value, type_line,"
            " oracle_text, color_identity, legal_commander, is_game_changer)"
            " VALUES(?,?,?,?,?,?,?,'legal',0)",
            (f"o{i}", name, mc, mv, tl, txt, json.dumps(ci)),
        )
    conn.commit()
    run_tagging(conn)
    conn.commit()
    return conn


def _decklist() -> str:
    lines = ["Commander", "1 Tovolar, Dire Overlord", "Deck"]
    for name, *_rest, is_land in CARDS:
        if name == "Tovolar, Dire Overlord":
            continue
        if is_land:
            continue
        lines.append(f"1 {name}")
    # pad to 100 with basics (8 nonland spells + 1 commander + 91 basics)
    lines.append("46 Forest")
    lines.append("45 Mountain")
    return "\n".join(lines)


def test_full_analysis_runs_all_sections(deck_db):
    deck = load_deck(deck_db, _decklist())
    assert deck.total_cards == 100
    assert not deck.unresolved

    sections = {s.title: s for s in analyze_deck(deck)}
    assert set(sections) == {"Overview", "Legality & Bracket", "Role Coverage", "Mana Base"}

    # Legality: legal size, legal commander, no banned, GC floor computed.
    legality = sections["Legality & Bracket"]
    assert legality.data["deck_size"] == 100
    assert legality.data["color_identity"] == ["G", "R"]
    assert not legality.data["violations"].get("banned")

    # Role coverage: our tagged staples land in the right buckets.
    roles = sections["Role Coverage"].data["roles"]
    assert roles["ramp"]["count"] >= 2       # Sol Ring, Llanowar Elves, Cultivate
    assert roles["spot_removal"]["count"] >= 2  # Beast Within, Lightning Bolt
    assert roles["board_wipe"]["count"] >= 1    # Blasphemous Act

    # Mana base: avg MV computed, curve present, both colors have sources.
    mana = sections["Mana Base"].data
    assert mana["land_count"] == 91
    assert mana["avg_mv"] > 0
    assert mana["sources_by_color"]["G"] > 0 and mana["sources_by_color"]["R"] > 0
    # 91 lands is absurd — the analyzer must flag it.
    assert any(f.severity == "warn" for f in sections["Mana Base"].findings)


def test_color_identity_violation_detected(deck_db):
    # Add an off-color card (blue) to a Gruul deck.
    deck_db.execute(
        "INSERT INTO cards(oracle_id, name, mana_cost, mana_value, type_line,"
        " oracle_text, color_identity, legal_commander, is_game_changer)"
        " VALUES('ox','Counterspell','{U}{U}',2,'Instant','Counter target spell.','[\"U\"]','legal',0)"
    )
    deck_db.commit()
    deck = load_deck(deck_db, "Commander\n1 Tovolar, Dire Overlord\nDeck\n1 Counterspell\n")
    legality = {s.title: s for s in analyze_deck(deck)}["Legality & Bracket"]
    offenders = [v["name"] for v in legality.data["violations"].get("color_identity", [])]
    assert "Counterspell" in offenders
