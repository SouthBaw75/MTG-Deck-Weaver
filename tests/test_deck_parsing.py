"""Deck parser and DeckView tests (no network, no DB)."""

from __future__ import annotations

import textwrap

from weaver.analysis.deck import parse_decklist
from deck_fixtures import basic_lands, make_card, make_deck


def test_parses_quantities_and_names():
    entries = parse_decklist("1 Sol Ring\n3x Forest\nRhystic Study\n")
    assert (entries[0].quantity, entries[0].name) == (1, "Sol Ring")
    assert (entries[1].quantity, entries[1].name) == (3, "Forest")
    assert (entries[2].quantity, entries[2].name) == (1, "Rhystic Study")


def test_strips_set_annotations():
    entries = parse_decklist("1 Sol Ring (C21) 263\n1 Counterspell [FOIL]\n")
    assert entries[0].name == "Sol Ring"
    assert entries[1].name == "Counterspell"


def test_commander_section_and_marker():
    text = textwrap.dedent("""\
        Commander
        1 Atraxa, Praetors' Voice
        Deck
        1 Sol Ring
        1 Kenrith, the Returned King *CMDR*
    """)
    entries = parse_decklist(text)
    cmdrs = [e.name for e in entries if e.is_commander]
    assert "Atraxa, Praetors' Voice" in cmdrs
    assert "Kenrith, the Returned King" in cmdrs
    assert not next(e for e in entries if e.name == "Sol Ring").is_commander


def test_ignores_sideboard_and_comments():
    text = textwrap.dedent("""\
        # my deck
        1 Sol Ring
        // note
        Sideboard
        1 Pyroblast
        Maybeboard
        1 Mana Crypt
    """)
    names = [e.name for e in parse_decklist(text)]
    assert names == ["Sol Ring"]


def test_split_card_separator_normalized():
    entries = parse_decklist("1 Fire // Ice\n1 Wear/Tear\n")
    assert entries[0].name == "Fire // Ice"
    assert entries[1].name == "Wear // Tear"


def test_deckview_aggregates():
    deck = make_deck(
        basic_lands({"Forest": 20})
        + [
            make_card("Sol Ring", type_line="Artifact", tags={"ramp.rock": 1.0}),
            make_card("Cultivate", type_line="Sorcery", tags={"ramp.land": 0.86, "mana-fixing": 0.6}),
            make_card("Kenrith, the Returned King", commander=True, type_line="Legendary Creature — Human Noble"),
        ]
    )
    assert deck.total_cards == 23
    assert deck.land_count == 20
    assert deck.tag_count("ramp.rock") == 1
    assert len(deck.commanders) == 1
    assert deck.nonland_spells  # excludes lands + commander
