"""Golden tests for the defense/offense-domain matcher.

Imports weaver.knowledge.matchers.defense_offense directly (NOT via
run_matchers) so results stay stable while other domain modules evolve.
"""

from __future__ import annotations

import pytest

import weaver.knowledge.matchers.defense_offense as defoff
from weaver.knowledge.taxonomy import is_valid_tag
from golden_utils import GOLDEN_DIR, load_golden

GOLDEN = load_golden(GOLDEN_DIR / "defense_offense.yaml")
IDS = [g.card.name for g in GOLDEN]

OWNED_TAGS = {
    "protection.self",
    "protection.board",
    "fog",
    "pillow-fort",
    "deterrent",
    "lifegain",
    "blocker.value",
    "wincon.combat",
    "wincon.alt",
    "evasion-granting",
    "buff.anthem",
    "extra-combat",
    "extra-turn",
    "burn",
}


def test_domain_marker():
    assert defoff.DOMAIN == "defense_offense"


def test_never_emits_combo_piece():
    # wincon.combo-piece is derived from the combo database, never patterns.
    for golden in GOLDEN:
        tags = {h.tag for h in defoff.match(golden.card)}
        assert "wincon.combo-piece" not in tags, golden.card.name


@pytest.mark.parametrize("golden", GOLDEN, ids=IDS)
def test_golden_expectations(golden):
    hits = defoff.match(golden.card)
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
    for hit in defoff.match(golden.card):
        assert is_valid_tag(hit.tag), f"{golden.card.name}: unregistered tag {hit.tag!r}"
        assert hit.tag in OWNED_TAGS, (
            f"{golden.card.name}: defense_offense matcher emitted foreign tag {hit.tag!r}"
        )
        assert 0.0 < hit.quality <= 1.0, (
            f"{golden.card.name}: {hit.tag} quality {hit.quality} outside (0, 1]"
        )
        assert hit.why, f"{golden.card.name}: {hit.tag} emitted without a why"
        assert hit.tag not in seen, f"{golden.card.name}: duplicate hit for {hit.tag}"
        seen.add(hit.tag)


def _quality(name: str, tag: str) -> float:
    golden = next(g for g in GOLDEN if g.card.name == name)
    for hit in defoff.match(golden.card):
        if hit.tag == tag:
            return hit.quality
    raise AssertionError(f"{name}: no {tag} hit emitted")


def test_teferis_protection_is_gold_standard():
    assert _quality("Teferi's Protection", "protection.board") >= _quality(
        "Heroic Intervention", "protection.board"
    )


def test_craterhoof_is_a_premium_finisher():
    assert _quality("Craterhoof Behemoth", "wincon.combat") >= 0.9
