"""Offline tests for the Defense & Weaknesses analyzer.

All decks are hand-built from tag fixtures; tag counts drive the analyzer, so a
full 100-card list is unnecessary.
"""

from __future__ import annotations

from deck_fixtures import make_card, make_deck

from weaver.analysis.analyzers import weakness


def _severities(section):
    return [f.severity for f in section.findings]


def _messages(section):
    return " || ".join(f.message for f in section.findings)


def test_module_contract():
    assert weakness.ORDER == 50
    section = weakness.analyze(make_deck([]))
    assert section.title == "Defense & Weaknesses"


def test_control_deck_classifies_control_with_few_blind_spots():
    cards = [
        make_card("Commander", commander=True, tags={"wincon.combat": 1.0}),
        *[make_card(f"Counter {i}", tags={"counterspell": 1.0}) for i in range(6)],
        *[make_card(f"Spot {i}", tags={"removal.spot.any": 1.0}) for i in range(6)],
        make_card("Wipe A", tags={"wipe.creature": 1.0}),
        make_card("Wipe B", tags={"wipe.any": 1.0}),
        make_card("Wipe C", tags={"wipe.creature": 1.0}),
        make_card("Prot", tags={"protection.self": 1.0}),
        make_card("Gy Hate", tags={"graveyard-hate": 1.0}),
    ]
    section = weakness.analyze(make_deck(cards))

    assert section.data["defense_style"] == "control"
    assert section.data["style_scores"]["control"] >= max(
        v for k, v in section.data["style_scores"].items() if k != "control"
    )
    # Well-answered deck: no board-wipe / stack / spot-removal warns.
    joined = _messages(section)
    assert "No board wipes" not in joined
    assert "Thin on spot removal" not in joined
    assert "stack interaction" not in joined
    # data contract
    assert "defense_style" in section.data
    assert "style_scores" in section.data
    assert "blind_spots" in section.data


def test_go_wide_vulnerable_flags_missing_wipes():
    # Plenty of everything EXCEPT board wipes.
    cards = [
        *[make_card(f"Counter {i}", tags={"counterspell": 1.0}) for i in range(4)],
        *[make_card(f"Spot {i}", tags={"removal.spot.any": 1.0}) for i in range(6)],
        make_card("Prot", tags={"protection.board": 1.0}),
    ]
    section = weakness.analyze(make_deck(cards))

    assert section.data["buckets"]["board_wipes"] == 0
    assert any("No board wipes" in bs for bs in section.data["blind_spots"])
    # Should be the headline since it's the highest-priority warn present.
    assert any(
        f.severity == "warn" and "Biggest blind spot" in f.message and "No board wipes" in f.message
        for f in section.findings
    )


def test_zero_counters_and_zero_graveyard_hate_are_flagged():
    cards = [
        # Board presence but no counters, no graveyard hate.
        make_card("Wipe A", tags={"wipe.creature": 1.0}),
        make_card("Wipe B", tags={"wipe.any": 1.0}),
        *[make_card(f"Spot {i}", tags={"removal.spot.creature": 1.0}) for i in range(6)],
        make_card("Prot", tags={"protection.self": 1.0}),
    ]
    section = weakness.analyze(make_deck(cards))

    assert section.data["buckets"]["counters"] == 0
    assert section.data["buckets"]["graveyard_hate"] == 0
    joined = _messages(section)
    # counters==0 with low instant-speed interaction -> stack-interaction warn.
    # Here instant interaction is high (removal), so the stack warn may be
    # suppressed; the graveyard-hate info must still fire.
    assert any("graveyard hate" in bs.lower() for bs in section.data["blind_spots"])
    assert "graveyard hate" in joined.lower()


def test_zero_counters_low_instant_flags_stack_interaction():
    # Almost no removal either -> instant interaction below the floor.
    cards = [
        make_card("Pillow", tags={"pillow-fort": 1.0}),
        make_card("Life", tags={"lifegain": 1.0}),
        make_card("Life2", tags={"lifegain": 1.0}),
    ]
    section = weakness.analyze(make_deck(cards))

    assert section.data["buckets"]["counters"] == 0
    assert section.data["instant_interaction"] < 3
    assert any("stack interaction" in bs for bs in section.data["blind_spots"])


def test_fragile_deck_classifies_fragile_with_multiple_warns():
    # Threats but essentially no defense.
    cards = [
        make_card("Commander", commander=True, tags={"wincon.combat": 1.0}),
        make_card("Threat 1", tags={"wincon.combat": 1.0}),
        make_card("Threat 2", tags={"extra-combat": 1.0}),
        make_card("Buff", tags={"buff.anthem": 1.0}),
    ]
    section = weakness.analyze(make_deck(cards))

    assert section.data["defense_style"] == "fragile"
    warns = [f for f in section.findings if f.severity == "warn"]
    assert len(warns) >= 2
    # Multiple structural holes should be surfaced.
    assert len(section.data["blind_spots"]) >= 3


def test_speed_deck_classifies_speed():
    # High threat density, minimal defense but not zero -> race, not fragile.
    cards = [
        *[make_card(f"Threat {i}", tags={"wincon.combat": 1.0}) for i in range(8)],
        make_card("Extra Combat", tags={"extra-combat": 1.0}),
        make_card("Extra Turn", tags={"extra-turn": 1.0}),
        make_card("Spot", tags={"removal.spot.any": 1.0}),
    ]
    section = weakness.analyze(make_deck(cards))

    assert section.data["threat_density"] >= 8
    assert section.data["defense_style"] == "speed"


def test_well_rounded_deck_gets_ok_note():
    cards = [
        make_card("Spot", tags={"removal.spot.any": 1.0}, qty=5),
        make_card("Wipe", tags={"wipe.creature": 1.0}),
        make_card("Counter", tags={"counterspell": 1.0}),
        make_card("Prot", tags={"protection.self": 1.0}),
        make_card("Fog", tags={"fog": 1.0}),
        make_card("Pillow", tags={"pillow-fort": 1.0}),
        make_card("Life", tags={"lifegain": 1.0}),
        make_card("GyHate", tags={"graveyard-hate": 1.0}),
        make_card("Recur", tags={"recursion": 1.0}),
    ]
    section = weakness.analyze(make_deck(cards))

    assert any(
        f.severity == "ok" and "Well-rounded" in f.message for f in section.findings
    )
    # All buckets non-zero.
    assert all(v > 0 for v in section.data["buckets"].values())


def test_empty_deck_is_robust_and_flags_insufficient_data():
    section = weakness.analyze(make_deck([]))
    assert any("Insufficient tagged data" in f.message for f in section.findings)
    # No crash, data keys present.
    assert "defense_style" in section.data
    assert "style_scores" in section.data
    assert isinstance(section.data["blind_spots"], list)
