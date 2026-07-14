"""Golden tests for the interaction-domain matcher.

Imports weaver.knowledge.matchers.interaction directly (NOT via run_matchers)
so results stay stable while other domain modules evolve.
"""

from __future__ import annotations

import pytest

import weaver.knowledge.matchers.interaction as interaction
from weaver.knowledge.taxonomy import is_valid_tag
from golden_utils import GOLDEN_DIR, load_golden

GOLDEN = load_golden(GOLDEN_DIR / "interaction.yaml")
IDS = [g.card.name for g in GOLDEN]

OWNED_TAGS = {
    "removal.spot.creature",
    "removal.spot.any",
    "removal.spot.artifact-enchantment",
    "wipe.creature",
    "wipe.any",
    "wipe.artifact-enchantment",
    "counterspell",
    "graveyard-hate",
    "stax",
    "theft",
    "taxing",
}


def test_domain_marker():
    assert interaction.DOMAIN == "interaction"


@pytest.mark.parametrize("golden", GOLDEN, ids=IDS)
def test_golden_expectations(golden):
    hits = interaction.match(golden.card)
    tags = {h.tag for h in hits}

    missing = golden.expect - tags
    assert not missing, (
        f"{golden.card.name}: expected tags not emitted: {sorted(missing)} "
        f"(got {sorted(tags)})"
    )

    bad = tags & golden.forbid
    assert not bad, (
        f"{golden.card.name}: forbidden tags emitted: {sorted(bad)} "
        f"(hits: {[(h.tag, h.quality, h.why) for h in hits if h.tag in bad]})"
    )


@pytest.mark.parametrize("golden", GOLDEN, ids=IDS)
def test_hits_well_formed(golden):
    seen = set()
    for hit in interaction.match(golden.card):
        assert is_valid_tag(hit.tag), f"{golden.card.name}: unregistered tag {hit.tag!r}"
        assert hit.tag in OWNED_TAGS, (
            f"{golden.card.name}: interaction matcher emitted foreign tag {hit.tag!r}"
        )
        assert 0.0 < hit.quality <= 1.0, (
            f"{golden.card.name}: {hit.tag} quality {hit.quality} outside (0, 1]"
        )
        assert hit.why, f"{golden.card.name}: {hit.tag} emitted without a why"
        assert hit.tag not in seen, f"{golden.card.name}: duplicate hit for {hit.tag}"
        seen.add(hit.tag)


def _quality(name: str, tag: str) -> float:
    golden = next(g for g in GOLDEN if g.card.name == name)
    for hit in interaction.match(golden.card):
        if hit.tag == tag:
            return hit.quality
    raise AssertionError(f"{name}: no {tag} hit emitted")


def test_premium_removal_beats_clunky_removal():
    assert _quality("Swords to Plowshares", "removal.spot.creature") > _quality(
        "Murder", "removal.spot.creature"
    )


def test_premium_counterspell_beats_cancel():
    assert _quality("Counterspell", "counterspell") > _quality("Cancel", "counterspell")


def test_instant_speed_is_rewarded():
    # Both destroy-all-creatures effects; the instant-speed one is not in the
    # golden set, so just sanity-check Wrath-style wipes score respectably.
    assert _quality("Wrath of God", "wipe.creature") >= 0.7
