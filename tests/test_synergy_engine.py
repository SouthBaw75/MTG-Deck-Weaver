"""Synergy engine tests using an explicit in-test interaction graph, so they
are deterministic regardless of the curated data file."""

from __future__ import annotations

from weaver.knowledge.synergy import (
    deck_synergy,
    find_partners,
    pairwise_synergy,
    synergy_with_profile,
    tag_profile,
)

# A tiny, explicit graph for deterministic tests.
EDGES = [
    {"from": "sac-outlet", "to": "death-payoff", "type": "enables", "strength": 0.9, "note": "aristocrats engine"},
    {"from": "token-producer", "to": "death-payoff", "type": "amplifies", "strength": 0.6, "note": "more fodder"},
    {"from": "wipe.creature", "to": "token-producer", "type": "nonbo", "strength": -0.6, "note": "kills your tokens"},
]


class _Card:
    def __init__(self, name, tags):
        self.name = name
        self.tags = tags


def test_pairwise_positive():
    score, contribs = pairwise_synergy(
        {"sac-outlet": 1.0}, {"death-payoff": 1.0}, edges=EDGES
    )
    assert score == 0.9
    assert contribs[0].type == "enables"


def test_pairwise_scales_with_quality():
    high, _ = pairwise_synergy({"sac-outlet": 1.0}, {"death-payoff": 1.0}, edges=EDGES)
    low, _ = pairwise_synergy({"sac-outlet": 0.5}, {"death-payoff": 0.5}, edges=EDGES)
    assert high > low
    assert abs(low - 0.9 * 0.25) < 1e-9


def test_nonbo_is_negative():
    score, contribs = pairwise_synergy(
        {"wipe.creature": 1.0}, {"token-producer": 1.0}, edges=EDGES
    )
    assert score < 0
    assert contribs[0].type == "nonbo"


def test_symmetric_direction():
    # edge is token-producer -> death-payoff; lookup should work either way
    a, _ = pairwise_synergy({"token-producer": 1.0}, {"death-payoff": 1.0}, edges=EDGES)
    b, _ = pairwise_synergy({"death-payoff": 1.0}, {"token-producer": 1.0}, edges=EDGES)
    assert a == b == 0.6


def test_no_shared_edge_is_zero():
    score, contribs = pairwise_synergy({"ramp.rock": 1.0}, {"fog": 1.0}, edges=EDGES)
    assert score == 0 and contribs == []


def test_tag_profile_aggregates():
    cards = [_Card("a", {"token-producer": 0.8}), _Card("b", {"token-producer": 0.6, "death-payoff": 0.9})]
    prof = tag_profile(cards)
    assert abs(prof["token-producer"] - 1.4) < 1e-9
    assert prof["death-payoff"] == 0.9


def test_synergy_with_profile():
    profile = {"death-payoff": 2.0}
    score, _ = synergy_with_profile({"sac-outlet": 1.0}, profile, edges=EDGES)
    assert abs(score - 0.9 * 2.0) < 1e-9


def test_deck_synergy_metrics():
    cards = [
        _Card("Viscera Seer", {"sac-outlet": 1.0}),
        _Card("Blood Artist", {"death-payoff": 1.0}),
        _Card("Bitterblossom", {"token-producer": 1.0}),
        _Card("Wrath of God", {"wipe.creature": 1.0}),
    ]
    result = deck_synergy(cards, edges=EDGES)
    assert result["total"] != 0
    # aristocrats trio is net positive; the wrath introduces a nonbo
    assert result["top_pairs"], "expected positive pairs"
    assert result["nonbos"], "expected the wipe/token nonbo"
    assert "Blood Artist" in result["per_card"]


def test_find_partners_ranks_by_synergy():
    pool = [
        _Card("Blood Artist", {"death-payoff": 1.0}),
        _Card("Random Vanilla", {"blocker.value": 1.0}),
        _Card("Grave Pact", {"death-payoff": 0.5}),
    ]
    ranked = find_partners({"sac-outlet": 1.0}, pool, edges=EDGES)
    assert ranked[0][0] == "Blood Artist"
    assert "Random Vanilla" not in [r[0] for r in ranked]
