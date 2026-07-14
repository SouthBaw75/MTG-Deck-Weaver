"""Tests for the consistency analyzer (offline, hand-built DeckViews).

Covers the hypergeometric helpers with hand-computed exact values, plus the
behavioral metrics (opening-hand land distribution, land-drop curve, ramp /
interaction access) and the section.data contract.
"""

from __future__ import annotations

from math import comb, isclose

from weaver.analysis.analyzers import consistency
from deck_fixtures import basic_lands, make_card, make_deck


def _sev(section, severity):
    return [f for f in section.findings if f.severity == severity]


def _pad_to(cards, target=100):
    """Pad a card list with colorless filler up to `target` total cards."""
    have = sum(c.quantity for c in cards)
    if have < target:
        cards.append(
            make_card("Filler", qty=target - have, type_line="Artifact", mana_value=2)
        )
    return cards


# ==========================================================================
# 1. Hypergeometric helpers — exact, hand-computed values.
# ==========================================================================
def test_hypergeom_single_success_is_ratio():
    # One copy in a 100-card deck, drawing 7: P(>=1) = 7/100 exactly.
    assert isclose(consistency.hypergeom_at_least(1, 100, 1, 7), 7 / 100)
    assert isclose(consistency.hypergeom_at_least_one(100, 1, 7), 0.07)
    assert isclose(consistency.hypergeom_exactly(1, 100, 1, 7), 7 / 100)
    # The single copy is either in the 7 seen or the 93 unseen.
    assert isclose(consistency.hypergeom_exactly(0, 100, 1, 7), 93 / 100)


def test_hypergeom_exactly_small_case():
    # N=10, K=2, n=3. P(exactly 2) = C(2,2)*C(8,1)/C(10,3) = 1*8/120 = 1/15.
    got = consistency.hypergeom_exactly(2, 10, 2, 3)
    assert isclose(got, 8 / 120)
    assert isclose(got, 1 / 15)
    # P(exactly 1) = C(2,1)*C(8,2)/C(10,3) = 2*28/120 = 56/120.
    assert isclose(consistency.hypergeom_exactly(1, 10, 2, 3), 56 / 120)
    # P(exactly 0) = C(8,3)/C(10,3) = 56/120.
    assert isclose(consistency.hypergeom_exactly(0, 10, 2, 3), comb(8, 3) / comb(10, 3))
    # The three exact cases form a full distribution.
    total = sum(consistency.hypergeom_exactly(k, 10, 2, 3) for k in range(3))
    assert isclose(total, 1.0)


def test_hypergeom_at_least_matches_complement():
    # N=40, K=17, n=10. P(>=1) == 1 - P(exactly 0).
    p_ge1 = consistency.hypergeom_at_least(1, 40, 17, 10)
    p_eq0 = consistency.hypergeom_exactly(0, 40, 17, 10)
    assert isclose(p_ge1, 1 - p_eq0)
    # P(>=0) is certain.
    assert consistency.hypergeom_at_least(0, 40, 17, 10) == 1.0


def test_hypergeom_edge_cases():
    # No successes in the deck -> can never draw one.
    assert consistency.hypergeom_at_least_one(100, 0, 7) == 0.0
    assert consistency.hypergeom_exactly(1, 100, 0, 7) == 0.0
    assert consistency.hypergeom_exactly(0, 100, 0, 7) == 1.0
    # Degenerate deck size.
    assert consistency.hypergeom_at_least(1, 0, 5, 7) == 0.0
    # Drawing more than the deck holds is clamped to drawing the whole deck.
    assert isclose(consistency.hypergeom_at_least_one(5, 3, 99), 1.0)
    # Asking for more successes than exist is impossible.
    assert consistency.hypergeom_at_least(4, 100, 3, 7) == 0.0


# ==========================================================================
# 2. Opening-hand land distribution.
# ==========================================================================
def test_opening_hand_distribution_sane():
    cards = basic_lands({"Forest": 38})
    _pad_to(cards, 100)
    deck = make_deck(cards)
    assert deck.total_cards == 100
    assert deck.land_count == 38

    section = consistency.analyze(deck)
    oh = section.data["opening_hand"]

    # Distribution over 0..7 lands sums to 1.
    assert isclose(sum(oh["distribution"].values()), 1.0)
    # A textbook 38-land Commander deck keeps most hands by land count.
    assert 0.75 < oh["p_keepable_2_5"] < 0.95
    # Screw + flood is the remainder.
    assert isclose(
        oh["p_keepable_2_5"] + oh["p_screw_0_1"] + oh["p_flood_6_7"], 1.0
    )


def test_opening_hand_matches_direct_hypergeom():
    cards = basic_lands({"Forest": 38})
    _pad_to(cards, 100)
    section = consistency.analyze(make_deck(cards))
    dist = section.data["opening_hand"]["distribution"]
    # Cross-check one bucket against a direct call.
    assert isclose(dist[3], consistency.hypergeom_exactly(3, 100, 38, 7))


def test_extreme_land_counts_flag_mulligan_risk():
    # A 20-land/100 deck floods with screw risk; a 60-land deck floods hard.
    lean = _pad_to(basic_lands({"Forest": 20}), 100)
    section = consistency.analyze(make_deck(lean))
    oh = section.data["opening_hand"]
    assert oh["p_screw_0_1"] > oh["p_flood_6_7"]  # too few lands -> screw
    assert oh["p_mulligan_risk"] > consistency._MULLIGAN_RISK
    assert any("mulligan risk" in f.message.lower() for f in _sev(section, "warn"))


# ==========================================================================
# 3. Land drops: more lands -> better curve.
# ==========================================================================
def test_land_drops_improve_with_more_lands():
    rich = consistency.analyze(make_deck(_pad_to(basic_lands({"Forest": 38}), 100)))
    poor = consistency.analyze(make_deck(_pad_to(basic_lands({"Forest": 20}), 100)))

    for t in (2, 3, 4, 5):
        assert rich.data["land_drops"][t] > poor.data["land_drops"][t]

    # The land-poor deck should warn about its turn-4 land drop.
    assert poor.data["land_drops"][4] < consistency._LAND_DROP_T4_FLOOR
    assert any("4th land by turn 4" in f.message for f in _sev(poor, "warn"))
    # The land-rich deck clears the floor.
    assert rich.data["land_drops"][4] >= consistency._LAND_DROP_T4_FLOOR


def test_land_drop_uses_on_the_play_card_count():
    cards = _pad_to(basic_lands({"Forest": 38}), 100)
    section = consistency.analyze(make_deck(cards))
    # By turn 4 on the play you've seen 7 + 3 = 10 cards; need >=4 lands.
    expected = consistency.hypergeom_at_least(4, 100, 38, 10)
    assert isclose(section.data["land_drops"][4], expected)


# ==========================================================================
# 4. Ramp access is monotonic in ramp count.
# ==========================================================================
def _deck_with_ramp(n_ramp):
    cards = basic_lands({"Forest": 38})
    for i in range(n_ramp):
        cards.append(
            make_card(
                f"Rock {i}", type_line="Artifact", mana_value=2,
                tags={"ramp.rock": 1.0},
            )
        )
    return make_deck(_pad_to(cards, 100))


def test_more_ramp_raises_access_monotonically():
    probs = []
    for n in (0, 5, 10, 20):
        section = consistency.analyze(_deck_with_ramp(n))
        assert section.data["ramp"]["count"] == n
        probs.append(section.data["ramp"]["p_by_turn3"])
    assert probs[0] == 0.0
    assert probs == sorted(probs)
    assert probs[1] < probs[2] < probs[3]
    # By turn 3 you've seen more cards than in the opener, so odds are higher.
    section = consistency.analyze(_deck_with_ramp(10))
    assert section.data["ramp"]["p_by_turn3"] > section.data["ramp"]["p_opening"]


def test_ramp_dedupes_multi_tag_cards():
    cards = basic_lands({"Forest": 38})
    # One card carrying two ramp tags counts once.
    cards.append(
        make_card(
            "Dork-Rock", type_line="Artifact Creature", mana_value=2,
            tags={"ramp.rock": 1.0, "ramp.dork": 1.0},
        )
    )
    section = consistency.analyze(make_deck(_pad_to(cards, 100)))
    assert section.data["ramp"]["count"] == 1


# ==========================================================================
# 5. Interaction access: a deck with none warns.
# ==========================================================================
def test_no_interaction_warns():
    cards = _pad_to(basic_lands({"Forest": 38}), 100)
    section = consistency.analyze(make_deck(cards))
    assert section.data["interaction"]["count"] == 0
    assert any(
        "interaction" in f.message.lower() for f in _sev(section, "warn")
    )


def test_low_interaction_warns_but_present():
    cards = basic_lands({"Forest": 38})
    # A single removal spell in 100 cards -> ~7% to open with it -> low warn.
    cards.append(
        make_card("Swords", type_line="Instant", mana_value=1,
                  tags={"removal.spot.creature": 1.0})
    )
    section = consistency.analyze(make_deck(_pad_to(cards, 100)))
    assert section.data["interaction"]["count"] == 1
    assert section.data["interaction"]["p_opening"] < consistency._INTERACTION_FLOOR
    assert any("Interaction access" in f.message for f in _sev(section, "warn"))


def test_ample_interaction_is_info_not_warn():
    cards = basic_lands({"Forest": 30})
    for i in range(15):
        cards.append(
            make_card(f"Removal {i}", type_line="Instant", mana_value=2,
                      tags={"removal.spot.any": 1.0})
        )
    section = consistency.analyze(make_deck(_pad_to(cards, 100)))
    assert section.data["interaction"]["count"] == 15
    assert section.data["interaction"]["p_opening"] >= consistency._INTERACTION_FLOOR
    assert not any(
        "Interaction access" in f.message for f in _sev(section, "warn")
    )


# ==========================================================================
# 6. Card advantage and tutor access appear in data.
# ==========================================================================
def test_card_advantage_and_tutors_reported():
    cards = basic_lands({"Forest": 34})
    for i in range(8):
        cards.append(
            make_card(f"Draw {i}", type_line="Enchantment", mana_value=3,
                      tags={"draw.engine": 1.0})
        )
    for i in range(4):
        cards.append(
            make_card(f"Tutor {i}", type_line="Sorcery", mana_value=2,
                      tags={"tutor.broad": 1.0})
        )
    section = consistency.analyze(make_deck(_pad_to(cards, 100)))
    assert section.data["card_advantage"]["count"] == 8
    assert 0.0 < section.data["card_advantage"]["p_by_turn3"] < 1.0
    assert section.data["tutors"]["count"] == 4
    assert 0.0 < section.data["tutors"]["p_by_turn"] < 1.0
    assert any("Tutor access" in f.message for f in section.findings)


# ==========================================================================
# 7. Contract: section shape and data keys exist.
# ==========================================================================
def test_section_contract():
    assert consistency.ORDER == 40
    section = consistency.analyze(make_deck(_pad_to(basic_lands({"Forest": 38}), 100)))
    assert section.title == "Consistency"
    assert section.findings  # at least one finding
    for key in (
        "deck_size", "land_count", "opening_hand", "land_drops",
        "ramp", "interaction", "card_advantage", "tutors", "assumptions",
    ):
        assert key in section.data
    assert set(section.data["land_drops"]) == {2, 3, 4, 5}
    for sub, keys in (
        ("opening_hand", {"distribution", "p_keepable_2_5", "p_screw_0_1",
                          "p_flood_6_7", "p_mulligan_risk"}),
        ("ramp", {"count", "p_opening", "p_by_turn3"}),
        ("interaction", {"count", "p_opening"}),
        ("card_advantage", {"count", "p_by_turn3"}),
        ("tutors", {"count", "turn", "p_by_turn"}),
    ):
        assert keys <= set(section.data[sub])


def test_empty_deck_falls_back_to_100():
    # total_cards == 0 -> N falls back to 100, no crash.
    section = consistency.analyze(make_deck([]))
    assert section.data["deck_size"] == 100
    assert section.data["land_count"] == 0
