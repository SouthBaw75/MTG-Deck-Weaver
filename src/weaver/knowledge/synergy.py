"""Synergy engine: score how well cards work together using the mechanic
interaction graph (data/curated/interactions.json).

The graph is tag→tag: edges say how one mechanic plays off another (enables,
amplifies, combos-with, protects-against, nonbo). Because everything is computed
from a card's *tags*, synergy works for any card — including brand-new ones the
day their Oracle text is tagged.

Core operations:
  pairwise_synergy(tags_a, tags_b)  -> (score, contributions)
  tag_profile(cards)                -> aggregated tag weights for a set of cards
  synergy_with_profile(tags, profile) -> (score, contributions)
  deck_synergy(cards)               -> density metrics + per-card contribution
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


def _load_edges() -> list[dict]:
    """Load the interaction graph, tolerating its absence during development."""
    try:
        from weaver.knowledge.interactions import interaction_edges
        return interaction_edges()
    except Exception:
        return []


@dataclass
class Contribution:
    from_tag: str
    to_tag: str
    type: str
    strength: float
    weighted: float
    note: str


def _edge_index(edges: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Index edges by unordered tag pair for O(1) pair lookups."""
    idx: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in edges:
        key = tuple(sorted((e["from"], e["to"])))
        idx[key].append(e)
    return idx


# Cache the index across calls (the graph is static within a process).
_INDEX_CACHE: dict[int, dict] = {}


def _get_index(edges: list[dict] | None) -> dict[tuple[str, str], list[dict]]:
    if edges is None:
        edges = _load_edges()
    key = id(edges)
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = _edge_index(edges)
    return _INDEX_CACHE[key]


def pairwise_synergy(
    tags_a: dict[str, float],
    tags_b: dict[str, float],
    *,
    edges: list[dict] | None = None,
    same_card: bool = False,
) -> tuple[float, list[Contribution]]:
    """Synergy between two tag sets (tag -> quality).

    For every interaction edge whose endpoints are one in A and the other in B,
    contribute strength * quality_a * quality_b (negative for nonbo). Returns the
    summed score and the list of contributing edges, sorted by impact.
    """
    index = _get_index(edges)
    contributions: list[Contribution] = []
    seen: set[int] = set()
    for ta, qa in tags_a.items():
        for tb, qb in tags_b.items():
            if ta == tb:
                continue
            key = tuple(sorted((ta, tb)))
            for e in index.get(key, ()):
                if same_card and id(e) in seen:
                    continue
                seen.add(id(e))
                weighted = e["strength"] * qa * qb
                contributions.append(
                    Contribution(e["from"], e["to"], e["type"], e["strength"], weighted, e.get("note", ""))
                )
    score = sum(c.weighted for c in contributions)
    contributions.sort(key=lambda c: abs(c.weighted), reverse=True)
    return score, contributions


def tag_profile(cards) -> dict[str, float]:
    """Aggregate a set of cards into tag -> summed quality weight.

    `cards` is any iterable of objects exposing a `.tags` dict (DeckCard,
    Candidate) — or (tags_dict, weight) pairs.
    """
    profile: dict[str, float] = defaultdict(float)
    for c in cards:
        tags = c.tags if hasattr(c, "tags") else c
        for tag, q in tags.items():
            profile[tag] += q
    return dict(profile)


def synergy_with_profile(
    tags: dict[str, float],
    profile: dict[str, float],
    *,
    edges: list[dict] | None = None,
) -> tuple[float, list[Contribution]]:
    """Synergy of a single card's tags against an aggregated deck tag profile.

    This is the builder's workhorse: cheap (O(edges touching the card's tags))
    and it captures "does this card interact with what the deck is doing?"."""
    return pairwise_synergy(tags, profile, edges=edges)


def deck_synergy(cards, *, edges: list[dict] | None = None) -> dict:
    """Compute deck-wide synergy metrics.

    Returns:
      total          — sum of all unique pairwise synergies
      density        — total / number of cards (avg synergy pull per card)
      per_card       — {name: net synergy with the rest of the deck}
      top_pairs      — strongest positive interactions (name_a, name_b, score, note)
      nonbos         — anti-synergies present (name_a, name_b, score, note)
    """
    cards = list(cards)
    per_card: dict[str, float] = defaultdict(float)
    pair_scores: list[tuple[str, str, float, str]] = []
    total = 0.0
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = cards[i], cards[j]
            if not a.tags or not b.tags:
                continue
            score, contribs = pairwise_synergy(a.tags, b.tags, edges=edges)
            if score == 0:
                continue
            total += score
            per_card[a.name] += score
            per_card[b.name] += score
            note = contribs[0].note if contribs else ""
            pair_scores.append((a.name, b.name, score, note))
    pair_scores.sort(key=lambda t: t[2], reverse=True)
    n = len(cards) or 1
    return {
        "total": round(total, 3),
        "density": round(total / n, 3),
        "per_card": {k: round(v, 3) for k, v in per_card.items()},
        "top_pairs": [p for p in pair_scores if p[2] > 0][:12],
        "nonbos": [p for p in pair_scores if p[2] < 0][:12],
    }


def find_partners(
    target_tags: dict[str, float],
    candidates,
    *,
    edges: list[dict] | None = None,
    top_n: int = 15,
) -> list[tuple]:
    """Rank candidates by synergy with a target card's tags.

    `candidates` is an iterable of objects with `.name` and `.tags`. Returns
    [(name, score, top_note), ...] highest first, excluding zero-synergy cards.
    """
    scored = []
    for c in candidates:
        if not c.tags:
            continue
        score, contribs = pairwise_synergy(target_tags, c.tags, edges=edges)
        if score != 0:
            note = contribs[0].note if contribs else ""
            scored.append((c.name, round(score, 3), note))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:top_n]
