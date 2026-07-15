"""Offline tests for the curated archetype data + resolver.

Loads the REAL data/curated/archetypes.json (via an explicit path so tests
pass regardless of the working directory pytest runs from) and exercises the
scoring resolver against hand-written commander texts.
"""

from pathlib import Path

from weaver.build import archetypes as arch
from weaver.knowledge import taxonomy

REPO_ARCHETYPES = (
    Path(__file__).resolve().parent.parent / "data" / "curated" / "archetypes.json"
)


def _load():
    return arch.load_archetypes(REPO_ARCHETYPES)


# ---- data integrity -------------------------------------------------------

def test_archetypes_json_parses():
    data = _load()
    assert isinstance(data, list)
    assert 15 <= len(data) <= 20
    keys = [a["key"] for a in data]
    assert len(keys) == len(set(keys)), "archetype keys must be unique"


def test_required_fields_present():
    for a in _load():
        for field in (
            "key",
            "name",
            "description",
            "signal_tags",
            "commander_text",
            "commander_keywords",
            "payoff_tags",
            "core_roles_bias",
        ):
            assert field in a, f"{a.get('key')} missing {field}"
        assert a["name"] and a["description"]
        assert a["commander_text"], f"{a['key']} has no commander_text signals"
        assert a["signal_tags"], f"{a['key']} has no signal_tags"


def test_all_tags_are_valid_taxonomy_tags():
    for a in _load():
        for tag in a["signal_tags"]:
            assert taxonomy.is_valid_tag(tag), f"{a['key']}: bad signal_tag {tag}"
        for tag in a["payoff_tags"]:
            assert taxonomy.is_valid_tag(tag), f"{a['key']}: bad payoff_tag {tag}"
        for tag in a["core_roles_bias"]:
            assert taxonomy.is_valid_tag(tag), f"{a['key']}: bad bias tag {tag}"


def test_payoff_tags_are_signal_tags():
    # Payoffs should be a subset of the archetype's own signals.
    for a in _load():
        signals = set(a["signal_tags"])
        for tag in a["payoff_tags"]:
            assert tag in signals, f"{a['key']}: payoff {tag} not in signal_tags"


# ---- resolver: archetype identification -----------------------------------

def test_aristocrats_ranks_first():
    data = _load()
    text = "whenever a creature you control dies, each opponent loses 1 life."
    ranked = arch.resolve_archetypes(text, {"death-payoff"}, data)
    assert ranked, "expected a non-empty ranking"
    assert ranked[0][0] == "aristocrats"
    assert ranked[0][1] > 0


def test_voltron_ranks_high():
    data = _load()
    text = "~ gets +1/+1 for each aura and equipment attached to it. it has trample."
    ranked = arch.resolve_archetypes(text, {"protection.self", "evasion-granting"}, data)
    top_keys = [k for k, _ in ranked]
    assert "voltron" in top_keys
    assert top_keys[0] == "voltron"


def test_landfall_ranks_first():
    data = _load()
    text = "landfall — whenever a land enters the battlefield under your control, draw a card."
    ranked = arch.resolve_archetypes(text, {"landfall-payoff"}, data)
    assert ranked[0][0] == "landfall"


def test_spellslinger_ranks_first():
    data = _load()
    text = "whenever you cast an instant or sorcery spell, ~ deals 1 damage to any target."
    ranked = arch.resolve_archetypes(text, {"spellslinger-payoff"}, data)
    assert ranked[0][0] == "spellslinger"


def test_reanimator_ranks_first():
    data = _load()
    text = (
        "return target creature card from your graveyard to the battlefield "
        "under your control."
    )
    ranked = arch.resolve_archetypes(text, {"cheat-into-play"}, data)
    assert ranked[0][0] == "reanimator"


def test_lifegain_ranks_first():
    data = _load()
    text = "whenever you gain life, you may draw a card. ~ has lifelink."
    ranked = arch.resolve_archetypes(text, {"lifegain"}, data)
    assert ranked[0][0] == "lifegain"


def test_counters_ranks_first():
    data = _load()
    text = "at the beginning of combat, put a +1/+1 counter on each creature you control."
    ranked = arch.resolve_archetypes(text, {"counters-matter"}, data)
    assert ranked[0][0] == "counters"


# ---- resolver: mechanics --------------------------------------------------

def test_top_n_is_respected():
    data = _load()
    text = "create a 1/1 creature token. whenever a creature you control dies, draw a card."
    ranked = arch.resolve_archetypes(text, {"token-producer"}, data, top_n=2)
    assert len(ranked) <= 2
    # Scores must be sorted descending.
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_empty_inputs_return_empty():
    data = _load()
    assert arch.resolve_archetypes("", set(), data) == []
    assert arch.resolve_archetypes("", None, data) == []
    assert arch.resolve_archetypes("some flavorful text with no signals", set(), data) == []


def test_tags_alone_can_score():
    data = _load()
    ranked = arch.resolve_archetypes("", {"death-payoff", "sac-outlet"}, data)
    assert ranked
    assert ranked[0][0] == "aristocrats"


def test_archetype_by_key():
    data = _load()
    a = arch.archetype_by_key("aristocrats", data)
    assert a is not None
    assert a["name"] == "Aristocrats"
    assert arch.archetype_by_key("does-not-exist", data) is None
