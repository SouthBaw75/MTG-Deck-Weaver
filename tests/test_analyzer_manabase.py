"""Tests for the mana-base analyzer (offline, hand-built DeckViews)."""

from __future__ import annotations

from weaver.analysis.analyzers import manabase
from deck_fixtures import basic_lands, make_card, make_deck


def _sev(section, severity):
    return [f for f in section.findings if f.severity == severity]


def _dual(name, colors, qty):
    return make_card(
        name,
        qty=qty,
        type_line="Land",
        color_identity=list(colors),
    )


# --------------------------------------------------------------------------
# 1. A well-built ~37-land two-color deck: on target, no warnings/problems.
# --------------------------------------------------------------------------
def test_well_built_deck_is_clean():
    cards = []
    # 1 commander (excluded from avg MV / curve, but its pips count).
    cards.append(
        make_card(
            "GW Commander",
            commander=True,
            type_line="Legendary Creature",
            mana_cost="{2}{G}{W}",
            mana_value=4,
            color_identity=["G", "W"],
        )
    )
    # 37 lands: 30 GW duals + 4 Forest + 3 Plains  -> both colors well over target.
    cards.append(_dual("Temple Garden", ["G", "W"], 30))
    cards += basic_lands({"Forest": 4, "Plains": 3})
    # 62 nonland spells, all MV 2 -> avg_mv == 2.0 -> recommended 37 lands.
    #  - 3 colorless ramp rocks (no colored pips), keeps ramp small (no land reduction)
    for i in range(3):
        cards.append(
            make_card(
                f"Rock {i}",
                type_line="Artifact",
                mana_cost="{2}",
                mana_value=2,
                color_identity=[],
                tags={"ramp.rock": 1.0},
            )
        )
    for i in range(30):
        cards.append(
            make_card(f"G Spell {i}", type_line="Creature", mana_cost="{1}{G}",
                      mana_value=2, color_identity=["G"])
        )
    for i in range(29):
        cards.append(
            make_card(f"W Spell {i}", type_line="Creature", mana_cost="{1}{W}",
                      mana_value=2, color_identity=["W"])
        )

    deck = make_deck(cards)
    assert deck.total_cards == 100
    section = manabase.analyze(deck)

    assert section.data["land_count"] == 37
    assert section.data["avg_mv"] == 2.0
    assert section.data["recommendations"]["recommended_lands"] == 37
    # No warnings or problems on a matched build.
    assert _sev(section, "problem") == []
    assert _sev(section, "warn") == []
    # Land count finding is an "ok".
    assert any("on target" in f.message for f in _sev(section, "ok"))


# --------------------------------------------------------------------------
# 2. A greedy 30-land 5-color deck: warns on land count and on thin colors.
# --------------------------------------------------------------------------
def test_greedy_five_color_deck_warns():
    cards = []
    cards.append(
        make_card(
            "WUBRG Commander",
            commander=True,
            type_line="Legendary Creature",
            mana_cost="{W}{U}{B}{R}{G}",
            mana_value=5,
            color_identity=["W", "U", "B", "R", "G"],
        )
    )
    # 30 lands: 6 basics of each color -> 6 sources per color.
    cards += basic_lands(
        {"Plains": 6, "Island": 6, "Swamp": 6, "Mountain": 6, "Forest": 6}
    )
    # 69 nonland spells, MV 3, cycling colors -> avg 3.0, ~14 pips/color.
    pip_colors = ["W", "U", "B", "R", "G"]
    for i in range(69):
        col = pip_colors[i % 5]
        cards.append(
            make_card(
                f"Spell {i}",
                type_line="Sorcery",
                mana_cost="{2}" + "{" + col + "}",
                mana_value=3,
                color_identity=[col],
            )
        )

    deck = make_deck(cards)
    assert deck.total_cards == 100
    section = manabase.analyze(deck)

    assert section.data["land_count"] == 30
    assert section.data["avg_mv"] == 3.0
    assert section.data["recommendations"]["recommended_lands"] >= 39
    for c in ("W", "U", "B", "R", "G"):
        assert section.data["sources_by_color"][c] == 6

    warns = _sev(section, "warn")
    # land-count warning
    assert any("meaningfully" in f.message and "low" in f.message for f in warns)
    # multiple under-supported colors
    color_warns = [f for f in warns if "under-supported" in f.message]
    assert len(color_warns) >= 3


# --------------------------------------------------------------------------
# 3. Heavy {G}{G}/{G}{G}{G} demand with only 6 green sources -> warn green.
# --------------------------------------------------------------------------
def test_thin_green_sources_warns():
    cards = []
    cards += basic_lands({"Forest": 6})           # 6 green sources
    cards += basic_lands({"Island": 10})          # blue lands, no green
    for i in range(4):
        cards.append(
            make_card(f"GG {i}", type_line="Creature", mana_cost="{G}{G}",
                      mana_value=2, color_identity=["G"])
        )
    for i in range(4):
        cards.append(
            make_card(f"GGG {i}", type_line="Creature", mana_cost="{G}{G}{G}",
                      mana_value=3, color_identity=["G"])
        )

    section = manabase.analyze(make_deck(cards))
    assert section.data["sources_by_color"]["G"] == 6
    # 4*2 + 4*3 = 20 green pips
    assert section.data["pips_by_color"]["G"] == 20.0

    warns = _sev(section, "warn")
    assert any("Green" in f.message and "under-supported" in f.message for f in warns)


# --------------------------------------------------------------------------
# 4. avg MV excludes lands and the commander.
# --------------------------------------------------------------------------
def test_avg_mv_excludes_lands_and_commander():
    cards = [
        make_card("Cmdr", commander=True, type_line="Legendary Creature",
                  mana_cost="{4}{G}{G}", mana_value=6, color_identity=["G"]),
        make_card("Forest big", type_line="Land", mana_value=0, color_identity=["G"]),
        make_card("One", type_line="Creature", mana_cost="{G}", mana_value=1,
                  color_identity=["G"]),
        make_card("Two", type_line="Creature", mana_cost="{1}{G}", mana_value=2,
                  color_identity=["G"]),
        make_card("Three", type_line="Creature", mana_cost="{2}{G}", mana_value=3,
                  color_identity=["G"]),
    ]
    section = manabase.analyze(make_deck(cards))
    # (1 + 2 + 3) / 3 == 2.0 ; commander MV 6 and land MV 0 excluded.
    assert section.data["avg_mv"] == 2.0


# --------------------------------------------------------------------------
# 5. Curve histogram is correct (quantity-weighted, buckets 0..7+).
# --------------------------------------------------------------------------
def test_curve_histogram():
    cards = [
        make_card("Cmdr", commander=True, type_line="Legendary Creature",
                  mana_value=4, color_identity=["G"]),
        make_card("Land", type_line="Land", mana_value=0, color_identity=["G"]),
        make_card("Zero", type_line="Artifact", mana_value=0),
        make_card("One", type_line="Creature", mana_value=1),
        make_card("Two", type_line="Creature", mana_value=2, qty=2),  # weighted
        make_card("Three", type_line="Creature", mana_value=3),
        make_card("Seven", type_line="Creature", mana_value=7),
        make_card("Eight", type_line="Creature", mana_value=8),      # -> 7+ bucket
    ]
    section = manabase.analyze(make_deck(cards))
    curve = section.data["curve"]
    assert curve[0] == 1
    assert curve[1] == 1
    assert curve[2] == 2
    assert curve[3] == 1
    assert curve[4] == 0   # commander excluded
    assert curve[7] == 2   # MV 7 and MV 8 both land in the 7+ bucket
    assert "7+:2" in section.data["curve_str"]


# --------------------------------------------------------------------------
# 6. Ramp package size is surfaced.
# --------------------------------------------------------------------------
def test_ramp_count_surfaced():
    cards = [
        make_card("Sol Ring", type_line="Artifact", mana_value=1,
                  tags={"ramp.rock": 1.0}),
        make_card("Signet", type_line="Artifact", mana_value=2, color_identity=["G"],
                  tags={"ramp.rock": 1.0}),
        make_card("Llanowar Elves", type_line="Creature", mana_value=1,
                  color_identity=["G"], tags={"ramp.dork": 1.0}),
        make_card("Rampant Growth", type_line="Sorcery", mana_value=2,
                  tags={"ramp.land": 1.0}),
        make_card("Dark Ritual", type_line="Instant", mana_value=1,
                  tags={"ramp.ritual": 1.0}),
    ]
    section = manabase.analyze(make_deck(cards))
    assert section.data["ramp_count"] == 5
    assert section.data["ramp_by_tag"]["ramp.rock"] == 2
    assert section.data["ramp_by_tag"]["ramp.dork"] == 1
    assert any("Ramp package" in f.message for f in section.findings)


# --------------------------------------------------------------------------
# 7. Unresolved nonland cards are excluded gracefully and counted.
# --------------------------------------------------------------------------
def test_unresolved_excluded():
    unresolved = make_card("Mystery", type_line="Creature", mana_value=0)
    unresolved.card = None  # simulate an unresolved card
    cards = [
        unresolved,
        make_card("Two", type_line="Creature", mana_cost="{1}{G}", mana_value=2,
                  color_identity=["G"]),
    ]
    section = manabase.analyze(make_deck(cards))
    assert section.data["excluded_unresolved"] == 1
    # avg over the single resolved spell only
    assert section.data["avg_mv"] == 2.0
