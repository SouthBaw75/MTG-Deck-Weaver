"""Unit tests for cut suggestions (weaver.analysis.cuts.suggest_cuts).

Pure: builds DeckView/DeckCard dataclasses directly, no DB. Verifies the
protection rules (commanders, lands, combo pieces, role-critical cards) and the
weakest-first ordering with human-readable reasons.
"""

from __future__ import annotations

from dataclasses import dataclass

from weaver.analysis.cuts import suggest_cuts
from weaver.analysis.deck import DeckCard, DeckView


@dataclass
class FakeMatch:
    cards: list


@dataclass
class FakeCardView:
    is_land: bool = False


def _card(name, *, tags=None, is_commander=False, resolved=True, land=False, mv=2.0):
    type_line = "Land" if land else "Creature"
    return DeckCard(
        quantity=1,
        name=name,
        is_commander=is_commander,
        card=FakeCardView(is_land=land) if resolved else None,
        tags=tags or {},
        mana_value=mv,
        type_line=type_line,
    )


def _deck(cards, *, near=None, present=None):
    d = DeckView(cards=list(cards))
    d.combos_near_miss = list(near or [])
    d.combos_present = list(present or [])
    return d


def test_protects_commander_lands_and_added_card():
    deck = _deck([
        _card("Meren of Clan Nel Toth", is_commander=True),
        _card("Forest", land=True, resolved=False, mv=0),
        _card("Filler A", tags={"draw.engine": 1.0}),
        _card("Filler B", tags={"draw.engine": 1.0}),
    ])
    names = [s["name"] for s in suggest_cuts(deck, adding="Walking Ballista", count=10)]
    assert "Meren of Clan Nel Toth" not in names  # commander protected
    assert "Forest" not in names                   # lands protected
    assert "Walking Ballista" not in names          # the card being added


def test_protects_combo_pieces():
    deck = _deck(
        [
            _card("Mikaeus, the Unhallowed", tags={"buff.anthem": 1.0}),
            _card("Filler A", tags={"draw.engine": 1.0}),
            _card("Filler B", tags={"draw.engine": 1.0}),
        ],
        near=[FakeMatch(cards=["Mikaeus, the Unhallowed", "Walking Ballista"])],
    )
    names = [s["name"] for s in suggest_cuts(deck, adding="Walking Ballista", count=10)]
    assert "Mikaeus, the Unhallowed" not in names   # near-miss combo piece
    assert "Walking Ballista" not in names


def test_unresolved_card_ranks_first_with_reason():
    deck = _deck([
        _card("Typpo Bolt", resolved=False),
        _card("Filler A", tags={"draw.engine": 1.0}),
        _card("Filler B", tags={"draw.engine": 1.0}),
    ])
    out = suggest_cuts(deck, count=5)
    assert out[0]["name"] == "Typpo Bolt"
    assert "not found" in out[0]["reason"].lower()


def test_low_synergy_reason_and_shape():
    # Two unrelated tag clusters -> low pairwise synergy; still cuttable, ranked
    # by weakness. Each suggestion carries name/reason/mv/mv_label/type_line.
    deck = _deck([
        _card("Lonely One", tags={"burn": 1.0}, mv=4),
        _card("Cluster A", tags={"draw.engine": 1.0}),
        _card("Cluster B", tags={"draw.engine": 1.0}),
    ])
    out = suggest_cuts(deck, count=5)
    assert out, "expected at least one cut candidate"
    for s in out:
        assert set(s) >= {"name", "reason", "mv", "mv_label", "type_line"}
        assert "_score" not in s


def test_respects_count_limit():
    # "token-producer" is not part of any functional role group, so these are
    # never protected as role-critical — all remain cuttable.
    cards = [_card(f"Card {i}", tags={"token-producer": 1.0}) for i in range(8)]
    deck = _deck(cards)
    assert len(suggest_cuts(deck, count=3)) == 3


def test_protects_sole_holder_of_under_filled_role():
    # All cards fill card_advantage and the group sits at its minimum; cutting
    # any would drop it below min, so none are suggested (role-critical).
    cards = [_card(f"Draw {i}", tags={"draw.engine": 1.0}) for i in range(3)]
    deck = _deck(cards)
    assert suggest_cuts(deck, count=5) == []
