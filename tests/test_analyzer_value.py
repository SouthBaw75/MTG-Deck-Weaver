"""Deck Value analyzer tests."""

from __future__ import annotations

import weaver.analysis.analyzers.value as value
from deck_fixtures import basic_lands, make_card, make_deck


def _section(deck):
    return value.analyze(deck)


def test_sums_prices_quantity_weighted():
    deck = make_deck([
        make_card("Sol Ring", type_line="Artifact", price_usd=1.50),
        make_card("Dockside Extortionist", type_line="Creature", price_usd=40.00),
    ] + basic_lands({"Island": 10}))  # basics: no price, not counted
    s = _section(deck)
    assert s.data["total_usd"] == 41.50
    assert s.data["priced_cards"] == 2


def test_basics_do_not_count_as_unpriced():
    deck = make_deck(basic_lands({"Forest": 20}) + [make_card("Sol Ring", type_line="Artifact", price_usd=2.0)])
    s = _section(deck)
    assert s.data["unpriced_cards"] == 0  # basics excused
    assert s.data["total_usd"] == 2.0


def test_flags_unpriced_and_unresolved():
    deck = make_deck([
        make_card("Priced", type_line="Creature", price_usd=5.0),
        make_card("No Price Card", type_line="Creature", price_usd=None),
    ], unresolved=["Ghost Card"])
    # add an unresolved DeckCard (card=None) so the counter sees it
    from weaver.analysis.deck import DeckCard
    deck.cards.append(DeckCard(quantity=1, name="Ghost Card", is_commander=False, card=None))
    s = _section(deck)
    assert s.data["unpriced_cards"] == 1
    assert s.data["unresolved_cards"] == 1
    assert any(f.severity == "warn" for f in s.findings)


def test_top_cards_sorted_by_line_total():
    deck = make_deck([
        make_card("Cheap", type_line="Creature", price_usd=1.0),
        make_card("Expensive", type_line="Creature", price_usd=30.0),
        make_card("Bulk x4", type_line="Creature", qty=4, price_usd=3.0),  # $12 line
    ])
    s = _section(deck)
    top = s.data["top_cards"]
    assert top[0]["name"] == "Expensive"       # $30
    assert top[1]["name"] == "Bulk x4"          # $12 line total beats the $1 card
    assert top[0]["line"] == 30.0


def test_empty_deck_is_zero():
    s = _section(make_deck([]))
    assert s.data["total_usd"] == 0.0
