"""Offline tests for the curated mechanic interaction graph + loader.

Loads the REAL data/curated/interactions.json (via an explicit path so the
tests pass regardless of the working directory pytest runs from) and validates
every edge against the taxonomy and the strength/type invariants.
"""

from pathlib import Path

from weaver.knowledge import interactions as inter
from weaver.knowledge import taxonomy

REPO_INTERACTIONS = (
    Path(__file__).resolve().parent.parent / "data" / "curated" / "interactions.json"
)

DECLARED_TYPES = {"enables", "amplifies", "combos-with", "protects-against", "nonbo"}


def _doc():
    return inter.load_interactions(REPO_INTERACTIONS)


def _edges():
    return inter.interaction_edges(_doc())


# ---- data integrity -------------------------------------------------------


def test_json_parses_and_has_edges():
    doc = _doc()
    assert isinstance(doc, dict)
    assert "edges" in doc and isinstance(doc["edges"], list)


def test_edge_count_in_range():
    assert 100 <= len(_edges()) <= 200


def test_all_endpoints_are_valid_tags():
    for edge in _edges():
        assert taxonomy.is_valid_tag(edge["from"]), edge["from"]
        assert taxonomy.is_valid_tag(edge["to"]), edge["to"]


def test_no_self_loops():
    for edge in _edges():
        assert edge["from"] != edge["to"], edge


def test_edge_types_are_declared():
    for edge in _edges():
        assert edge["type"] in DECLARED_TYPES, edge["type"]
    # edge_types map in the document matches the declared set.
    assert set(_doc()["edge_types"].keys()) == DECLARED_TYPES


def test_strengths_in_range():
    for edge in _edges():
        assert isinstance(edge["strength"], (int, float))
        assert -1.0 <= edge["strength"] <= 1.0, edge


def test_nonbo_negative_others_positive():
    for edge in _edges():
        if edge["type"] == "nonbo":
            assert edge["strength"] < 0, edge
        else:
            assert edge["strength"] > 0, edge


def test_every_declared_type_present():
    present = {edge["type"] for edge in _edges()}
    assert present == DECLARED_TYPES


def test_rule_citations_are_strings_or_null():
    for edge in _edges():
        assert "rule" in edge
        if edge["rule"] is not None:
            assert isinstance(edge["rule"], str) and edge["rule"].strip()


def test_notes_present():
    for edge in _edges():
        assert isinstance(edge.get("note"), str) and edge["note"].strip()


# ---- known interaction spot-check -----------------------------------------


def test_aristocrats_edge_exists():
    hits = inter.edges_between("sac-outlet", "death-payoff", _doc())
    assert hits, "expected a curated edge connecting sac-outlet and death-payoff"
    assert any(e["type"] == "enables" for e in hits)


def test_infinite_mana_edge_exists():
    hits = inter.edges_between("untapper", "ramp.rock", _doc())
    assert any(e["type"] == "combos-with" for e in hits)


# ---- loader behaviour -----------------------------------------------------


def test_edges_between_is_symmetric():
    doc = _doc()
    for a, b in [("sac-outlet", "death-payoff"), ("wipe.creature", "token-producer")]:
        assert inter.edges_between(a, b, doc) == inter.edges_between(b, a, doc)


def test_edges_for_tag_superset_of_between():
    doc = _doc()
    between = inter.edges_between("sac-outlet", "death-payoff", doc)
    touching = inter.edges_for_tag("sac-outlet", doc)
    for edge in between:
        assert edge in touching


def test_loaders_robust_to_empty():
    empty: dict = {}
    assert inter.interaction_edges(empty) == []
    assert inter.edges_between("a", "b", empty) == []
    assert inter.edges_for_tag("a", empty) == []
