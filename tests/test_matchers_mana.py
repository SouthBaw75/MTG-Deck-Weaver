"""Golden tests for the mana-domain matcher.

Imports weaver.knowledge.matchers.mana directly (NOT via run_matchers) so
results stay stable while other domain modules are developed concurrently.
"""

from __future__ import annotations

import pytest

import weaver.knowledge.matchers.mana as mana
from weaver.knowledge.taxonomy import category_of, is_valid_tag
from golden_utils import GOLDEN_DIR, load_golden

GOLDEN = load_golden(GOLDEN_DIR / "mana.yaml")
IDS = [g.card.name for g in GOLDEN]

OWNED_TAGS = {
    "ramp.land",
    "ramp.rock",
    "ramp.dork",
    "ramp.ritual",
    "cost-reduction",
    "mana-fixing",
    "land.utility",
}


def test_domain_marker():
    assert mana.DOMAIN == "mana"


@pytest.mark.parametrize("golden", GOLDEN, ids=IDS)
def test_golden_expectations(golden):
    hits = mana.match(golden.card)
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
    for hit in mana.match(golden.card):
        assert is_valid_tag(hit.tag), f"{golden.card.name}: unregistered tag {hit.tag!r}"
        assert hit.tag in OWNED_TAGS, (
            f"{golden.card.name}: mana matcher emitted foreign tag {hit.tag!r}"
        )
        assert category_of(hit.tag) == "mana", (
            f"{golden.card.name}: {hit.tag!r} is not a mana-category tag"
        )
        assert 0.0 < hit.quality <= 1.0, (
            f"{golden.card.name}: {hit.tag} quality {hit.quality} outside (0, 1]"
        )
        assert hit.why, f"{golden.card.name}: {hit.tag} emitted without a why"
        assert hit.tag not in seen, f"{golden.card.name}: duplicate hit for {hit.tag}"
        seen.add(hit.tag)


def _quality(name: str, tag: str) -> float:
    golden = next(g for g in GOLDEN if g.card.name == name)
    for hit in mana.match(golden.card):
        if hit.tag == tag:
            return hit.quality
    raise AssertionError(f"{name}: no {tag} hit emitted")


def test_rock_quality_favors_cheap_rocks():
    sol_ring = _quality("Sol Ring", "ramp.rock")
    sphere = _quality("Commander's Sphere", "ramp.rock")  # 3-mana rock
    dynamo = _quality("Thran Dynamo", "ramp.rock")  # 4-mana rock
    assert sol_ring > sphere > dynamo
    assert sol_ring == 1.0


def test_dork_quality_favors_cheap_dorks():
    assert _quality("Llanowar Elves", "ramp.dork") > _quality("Faeburrow Elder", "ramp.dork")


def test_signet_beats_nothing_fancy_but_is_solid():
    # 2-mana rocks sit clearly between Sol Ring and 4-drops.
    two_drop = _quality("Arcane Signet", "ramp.rock")
    assert _quality("Sol Ring", "ramp.rock") > two_drop > _quality("Thran Dynamo", "ramp.rock")


def test_taplands_barely_qualify_as_utility():
    # Lifegain-ETB taplands are tagged, but at clearly lower quality than
    # genuinely active utility lands.
    assert _quality("Radiant Fountain", "land.utility") < _quality("Rogue's Passage", "land.utility")
    assert _quality("Radiant Fountain", "land.utility") <= 0.3


def test_dark_ritual_is_a_premium_ritual():
    assert _quality("Dark Ritual", "ramp.ritual") >= 0.85
