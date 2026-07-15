"""Commander strategy archetypes (KNOWLEDGE_MODEL.md, Layer 3).

Loads the curated archetype definitions from data/curated/archetypes.json and
scores how well a given commander fits each archetype based on its Oracle text
and role tags. Pure stdlib — no DB, no network.

Scoring for a single archetype against a commander:

    score = 2.0 * (# archetype.commander_text substrings found in the
                   commander's lowercased oracle text)
          + 1.0 * (# of the commander's own tags that appear in
                   archetype.signal_tags)
          + 1.0 * (# archetype.commander_keywords that match either one of
                   the commander's tags or a substring of its oracle text)

`resolve_archetypes` returns the top_n (key, score) pairs sorted by score
descending (ties broken by archetype order in the data file), dropping any
archetype that scored 0.
"""

from __future__ import annotations

import json
from pathlib import Path

from weaver.db.connection import repo_root

# Scoring weights.
TEXT_WEIGHT = 2.0
TAG_WEIGHT = 1.0
KEYWORD_WEIGHT = 1.0

_DEFAULT_REL_PATH = Path("data") / "curated" / "archetypes.json"


def load_archetypes(path: Path | None = None) -> list[dict]:
    """Load the archetype definitions.

    When *path* is None, reads data/curated/archetypes.json relative to
    repo_root().
    """
    if path is None:
        path = repo_root() / _DEFAULT_REL_PATH
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc["archetypes"]


def _score_archetype(
    archetype: dict,
    commander_text_lower: str,
    commander_tags: set[str],
) -> float:
    text = commander_text_lower or ""
    tags = commander_tags or set()

    score = 0.0

    for phrase in archetype.get("commander_text", []):
        if phrase and phrase.lower() in text:
            score += TEXT_WEIGHT

    signal_tags = set(archetype.get("signal_tags", []))
    score += TAG_WEIGHT * len(tags & signal_tags)

    for kw in archetype.get("commander_keywords", []):
        if not kw:
            continue
        kw_lower = kw.lower()
        if kw_lower in tags or kw_lower in text:
            score += KEYWORD_WEIGHT

    return score


def resolve_archetypes(
    commander_text_lower: str,
    commander_tags: set[str],
    archetypes: list[dict] | None = None,
    top_n: int = 3,
) -> list[tuple[str, float]]:
    """Rank archetypes for a commander, returning up to *top_n* (key, score).

    Only archetypes scoring above 0 are returned; results are sorted by score
    descending, with ties broken by the archetype's position in the data file.
    Returns [] when nothing scores.
    """
    if archetypes is None:
        archetypes = load_archetypes()

    scored: list[tuple[str, float]] = []
    for i, archetype in enumerate(archetypes):
        score = _score_archetype(archetype, commander_text_lower, commander_tags)
        if score > 0:
            # Negative index keeps earlier archetypes ahead on ties after the
            # score sort (which is descending on the first key).
            scored.append((archetype["key"], score, i))  # type: ignore[arg-type]

    scored.sort(key=lambda t: (-t[1], t[2]))
    return [(key, score) for key, score, _ in scored[: max(0, top_n)]]


def archetype_by_key(key: str, archetypes: list[dict] | None = None) -> dict | None:
    """Return the archetype dict for *key*, or None if not found."""
    if archetypes is None:
        archetypes = load_archetypes()
    for archetype in archetypes:
        if archetype.get("key") == key:
            return archetype
    return None
