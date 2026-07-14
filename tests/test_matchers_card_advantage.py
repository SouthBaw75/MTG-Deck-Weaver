"""Golden tests for the card_advantage matcher domain.

Imports the matcher module directly (NOT via run_matchers) so concurrent
work on other domain modules cannot affect these tests.
"""

from golden_utils import GOLDEN_DIR, load_golden

from weaver.knowledge.matchers import card_advantage
from weaver.knowledge.taxonomy import TAGS, category_of, is_valid_tag

GOLDEN = load_golden(GOLDEN_DIR / "card_advantage.yaml")
DOMAIN_TAGS = {t for t, (cat, _) in TAGS.items() if cat == "card_advantage"}


def _hits_by_name(name: str):
    for gc in GOLDEN:
        if gc.card.name == name:
            return card_advantage.match(gc.card)
    raise AssertionError(f"golden card {name!r} not found")


def test_golden_set_is_substantial():
    assert len(GOLDEN) >= 55
    covered = set().union(*(gc.expect for gc in GOLDEN))
    assert covered == DOMAIN_TAGS, f"tags without positive coverage: {DOMAIN_TAGS - covered}"


def test_golden_expectations():
    for gc in GOLDEN:
        produced = {h.tag for h in card_advantage.match(gc.card)}
        missing = gc.expect - produced
        assert not missing, (
            f"{gc.card.name}: missing expected tags {sorted(missing)} (got {sorted(produced)})"
        )
        forbidden = produced & gc.forbid
        assert not forbidden, (
            f"{gc.card.name}: emitted forbidden tags {sorted(forbidden)} (got {sorted(produced)})"
        )


def test_only_domain_tags_and_taxonomy_valid():
    for gc in GOLDEN:
        for hit in card_advantage.match(gc.card):
            assert is_valid_tag(hit.tag), f"{gc.card.name}: unregistered tag {hit.tag!r}"
            assert category_of(hit.tag) == "card_advantage", (
                f"{gc.card.name}: {hit.tag!r} is outside the card_advantage domain"
            )
            assert hit.tag in DOMAIN_TAGS


def test_quality_bounds_and_why():
    for gc in GOLDEN:
        for hit in card_advantage.match(gc.card):
            assert 0.0 < hit.quality <= 1.0, (
                f"{gc.card.name}: {hit.tag} quality {hit.quality} outside (0, 1]"
            )
            assert hit.why, f"{gc.card.name}: {hit.tag} has an empty why string"


def test_cheap_unrestricted_tutor_outranks_expensive_one():
    demonic = {h.tag: h for h in _hits_by_name("Demonic Tutor")}
    diabolic = {h.tag: h for h in _hits_by_name("Diabolic Tutor")}
    assert "tutor.broad" in demonic and "tutor.broad" in diabolic
    assert demonic["tutor.broad"].quality >= 0.95, "Demonic Tutor should be near-perfect"
    assert demonic["tutor.broad"].quality > diabolic["tutor.broad"].quality, (
        "2-mana Demonic Tutor must outrank the 4-mana Diabolic Tutor"
    )


def test_vampiric_is_broad_and_mystical_is_narrow():
    assert {h.tag for h in _hits_by_name("Vampiric Tutor")} == {"tutor.broad"}
    assert {h.tag for h in _hits_by_name("Mystical Tutor")} == {"tutor.narrow"}
