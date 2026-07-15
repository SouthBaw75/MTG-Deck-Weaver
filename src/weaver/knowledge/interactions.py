"""Mechanic Interaction Graph (KNOWLEDGE_MODEL.md, Layer 2).

Loads the hand-authored tag-to-tag interaction graph from
data/curated/interactions.json. Each edge connects two taxonomy tags
(``from`` -> ``to``) with a typed relationship (enables / amplifies /
combos-with / protects-against / nonbo) and a strength in [-1, 1]
(nonbo edges are negative). Edges optionally carry a Comprehensive Rules
citation.

The synergy engine reasons over this graph: given the tags on two cards,
it looks up the edges between those tags to explain and score the
interaction. Pure stdlib -- no DB, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

from weaver.db.connection import repo_root

_DEFAULT_REL_PATH = Path("data") / "curated" / "interactions.json"


def load_interactions(path: Path | None = None) -> dict:
    """Load the raw interactions document.

    When *path* is None, reads data/curated/interactions.json relative to
    repo_root().
    """
    if path is None:
        path = repo_root() / _DEFAULT_REL_PATH
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def interaction_edges(interactions: dict | None = None) -> list[dict]:
    """Return the list of edge dicts (loading the document if needed)."""
    if interactions is None:
        interactions = load_interactions()
    return list(interactions.get("edges", []))


def edges_between(
    tag_a: str, tag_b: str, interactions: dict | None = None
) -> list[dict]:
    """Return every edge connecting *tag_a* and *tag_b* in either direction.

    Matches edges where (from == tag_a and to == tag_b) OR
    (from == tag_b and to == tag_a). Used by the synergy engine, which does
    not care which card supplied which tag.
    """
    result = []
    for edge in interaction_edges(interactions):
        endpoints = {edge.get("from"), edge.get("to")}
        if endpoints == {tag_a, tag_b}:
            result.append(edge)
    return result


def edges_for_tag(tag: str, interactions: dict | None = None) -> list[dict]:
    """Return every edge that touches *tag* as either endpoint."""
    return [
        edge
        for edge in interaction_edges(interactions)
        if edge.get("from") == tag or edge.get("to") == tag
    ]
