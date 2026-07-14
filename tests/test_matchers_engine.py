"""Golden tests for the engine-domain matcher.

Imports weaver.knowledge.matchers.engine directly (NOT via run_matchers) so
results stay stable while other domain modules evolve.
"""

from __future__ import annotations

import pytest

import weaver.knowledge.matchers.engine as engine
from weaver.knowledge.taxonomy import is_valid_tag
from golden_utils import GOLDEN_DIR, load_golden

GOLDEN = load_golden(GOLDEN_DIR / "engine.yaml")
IDS = [g.card.name for g in GOLDEN]

OWNED_TAGS = {
    "token-producer",
    "treasure-producer",
    "sac-outlet",
    "death-payoff",
    "counters-matter",
    "landfall-payoff",
    "spellslinger-payoff",
    "untapper",
    "copy-effect",
    "blink",
    "cheat-into-play",
    "graveyard-fill",
    "discard-payoff",
    "haste-granting",
    "flash-granting",
}


def test_domain_marker():
    assert engine.DOMAIN == "engine"


@pytest.mark.parametrize("golden", GOLDEN, ids=IDS)
def test_golden_expectations(golden):
    hits = engine.match(golden.card)
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
    for hit in engine.match(golden.card):
        assert is_valid_tag(hit.tag), f"{golden.card.name}: unregistered tag {hit.tag!r}"
        assert hit.tag in OWNED_TAGS, (
            f"{golden.card.name}: engine matcher emitted foreign tag {hit.tag!r}"
        )
        assert 0.0 < hit.quality <= 1.0, (
            f"{golden.card.name}: {hit.tag} quality {hit.quality} outside (0, 1]"
        )
        assert hit.why, f"{golden.card.name}: {hit.tag} emitted without a why"
        assert hit.tag not in seen, f"{golden.card.name}: duplicate hit for {hit.tag}"
        seen.add(hit.tag)


def _quality(name: str, tag: str) -> float:
    golden = next(g for g in GOLDEN if g.card.name == name)
    for hit in engine.match(golden.card):
        if hit.tag == tag:
            return hit.quality
    raise AssertionError(f"{name}: no {tag} hit emitted")


def test_doubling_season_is_premium_counters_payoff():
    assert _quality("Doubling Season", "counters-matter") >= 0.9


def test_free_sac_outlet_beats_restrictive_one():
    assert _quality("Ashnod's Altar", "sac-outlet") > _quality("Birthing Pod", "sac-outlet")
