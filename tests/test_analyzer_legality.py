"""Offline tests for the legality + bracket analyzer."""

from __future__ import annotations

from deck_fixtures import basic_lands, make_card, make_deck

from weaver.analysis.analyzers import legality


# ---- helpers -------------------------------------------------------------

def _problems(section):
    return [f.message for f in section.findings if f.severity == "problem"]


def _warns(section):
    return [f.message for f in section.findings if f.severity == "warn"]


def _pad_to_100(cards, filler="Forest"):
    """Append enough basic lands so the deck totals exactly 100 cards."""
    total = sum(c.quantity for c in cards)
    need = 100 - total
    assert need >= 0, f"deck already has {total} cards"
    if need:
        cards = cards + basic_lands({filler: need})
    return cards


def _commander(name="Yeva, Nature's Herald", ci=("G",)):
    return make_card(
        name,
        commander=True,
        type_line="Legendary Creature — Elf Shaman",
        mana_value=3.0,
        color_identity=list(ci),
        oracle_text="Flash. You may cast green creature spells as though they had flash.",
    )


# ---- tests ---------------------------------------------------------------

def test_clean_legal_mono_green_deck():
    cards = [
        _commander(),
        make_card("Llanowar Elves", type_line="Creature — Elf Druid", color_identity=["G"]),
        make_card("Cultivate", type_line="Sorcery", color_identity=["G"], mana_value=3.0),
        make_card("Sol Ring", type_line="Artifact", color_identity=[], mana_value=1.0),
    ]
    deck = make_deck(_pad_to_100(cards))
    section = legality.analyze(deck)

    assert section.title == "Legality & Bracket"
    assert _problems(section) == []
    assert section.data["deck_size"] == 100
    assert section.data["color_identity"] == ["G"]
    # 0 Game Changers -> the floor is bracket 1.
    assert section.data["game_changer_count"] == 0
    assert section.data["min_bracket"] == 1


def test_color_identity_violation():
    cards = [
        _commander("Chulane, Teller of Tales", ci=("G", "W", "U")),
        make_card("Lightning Bolt", type_line="Instant", color_identity=["R"], mana_value=1.0),
        make_card("Llanowar Elves", type_line="Creature — Elf Druid", color_identity=["G"]),
    ]
    deck = make_deck(_pad_to_100(cards))
    section = legality.analyze(deck)

    probs = _problems(section)
    assert any("Lightning Bolt" in m for m in probs)
    viols = section.data["violations"]["color_identity"]
    assert viols[0]["name"] == "Lightning Bolt"
    assert viols[0]["outside"] == ["R"]


def test_banned_card_flagged():
    cards = [
        _commander(),
        make_card(
            "Channel",
            type_line="Sorcery",
            color_identity=["G"],
            legal_commander="banned",
        ),
    ]
    deck = make_deck(_pad_to_100(cards))
    section = legality.analyze(deck)

    assert any("Channel" in m and "banned" in m for m in _problems(section))
    assert section.data["violations"]["banned"] == ["Channel"]


def test_four_game_changers_min_bracket_four():
    gc_names = ["Rhystic Study", "Cyclonic Rift", "Mana Vault", "Demonic Tutor"]
    cards = [_commander("Kenrith, the Returned King", ci=("W", "U", "B", "R", "G"))]
    for n in gc_names:
        cards.append(
            make_card(n, type_line="Artifact", color_identity=[], game_changer=True)
        )
    deck = make_deck(_pad_to_100(cards))
    section = legality.analyze(deck)

    assert section.data["game_changer_count"] == 4
    assert sorted(section.data["game_changers"]) == sorted(gc_names)
    assert section.data["min_bracket"] == 4


def test_duplicate_nonbasic_singleton_problem():
    cards = [
        _commander(),
        make_card("Sol Ring", qty=2, type_line="Artifact", color_identity=[], mana_value=1.0),
    ]
    deck = make_deck(_pad_to_100(cards))
    section = legality.analyze(deck)

    assert any("Sol Ring" in m for m in _problems(section))
    assert section.data["violations"]["singleton"][0]["name"] == "Sol Ring"


def test_relentless_rats_no_singleton_problem():
    cards = [
        _commander("K'rrik, Son of Yawgmoth", ci=("B",)),
        make_card(
            "Relentless Rats",
            qty=10,
            type_line="Creature — Rat",
            color_identity=["B"],
            oracle_text=(
                "Relentless Rats gets +1/+1 for each other creature named "
                "Relentless Rats you control.\n"
                "A deck can have any number of cards named Relentless Rats."
            ),
        ),
    ]
    deck = make_deck(_pad_to_100(cards, filler="Swamp"))
    section = legality.analyze(deck)

    assert "singleton" not in section.data["violations"]
    assert not any("Relentless Rats" in m for m in _problems(section))


def test_missing_commander_warns():
    cards = [
        make_card("Llanowar Elves", type_line="Creature — Elf Druid", color_identity=["G"]),
    ]
    deck = make_deck(_pad_to_100(cards))
    section = legality.analyze(deck)

    assert any("no commander" in m.lower() for m in _warns(section))
    assert section.data["color_identity"] == []
