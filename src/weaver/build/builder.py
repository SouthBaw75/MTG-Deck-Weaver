"""Top-level build orchestration: pool → archetype → score → assemble.

This ties the builder components together and is what the CLI calls. Archetype
resolution is optional — if the archetype data/module is unavailable the build
still runs with a neutral (goodstuff) bias.
"""

from __future__ import annotations

import sqlite3

from weaver.build.assembler import assemble
from weaver.build.pool import build_pool
from weaver.build.scoring import score_pool
from weaver.build.templates import template_for_bracket
from weaver.build.types import BuildRequest, BuildResult


def _archetype_bias(commander, request: BuildRequest) -> tuple[list[str], dict[str, float]]:
    """Return (archetype_keys, tag->multiplier bias). Degrades to ([], {}) if
    the archetype layer isn't present yet."""
    try:
        from weaver.build.archetypes import archetype_by_key, resolve_archetypes
    except Exception:
        return [], {}

    text = commander.card.text_lower
    tags = set(commander.tags)
    # Respect an explicit theme override.
    if request.theme:
        entry = archetype_by_key(request.theme)
        ranked = [(request.theme, 1.0)] if entry else []
    else:
        ranked = resolve_archetypes(text, tags)
    if not ranked:
        return [], {}

    bias: dict[str, float] = {}
    keys: list[str] = []
    for key, _score in ranked:
        entry = archetype_by_key(key)
        if not entry:
            continue
        keys.append(key)
        for tag, mult in (entry.get("core_roles_bias") or {}).items():
            bias[tag] = max(bias.get(tag, 1.0), float(mult))
    return keys, bias


def _synergy_profile(commander, partner, bias: dict[str, float]) -> dict[str, float]:
    """Aggregate tag profile the pool is scored for synergy against: the
    commander's tags (weighted heavily, they define the deck) plus the
    archetype's payoff tags."""
    profile: dict[str, float] = {}
    for card in (commander, partner):
        if card:
            for tag, q in card.tags.items():
                profile[tag] = profile.get(tag, 0.0) + q * 2.0  # commander is central
    for tag, mult in bias.items():
        if mult > 1.0:
            profile[tag] = profile.get(tag, 0.0) + (mult - 1.0)
    return profile


def build_deck(conn: sqlite3.Connection, request: BuildRequest) -> BuildResult:
    commander, partner, pool = build_pool(conn, request)
    archetype_keys, bias = _archetype_bias(commander, request)
    profile = _synergy_profile(commander, partner, bias)
    score_pool(pool, request, bias, profile)
    template = template_for_bracket(request.bracket)
    result = assemble(commander, partner, pool, request, template)
    if archetype_keys:
        result.notes.insert(0, "archetype(s): " + ", ".join(archetype_keys))
    else:
        result.notes.insert(0, "archetype: goodstuff (no strong archetype signal / theme)")
    result.notes.append(f"pool size after color/legality/budget filter: {len(pool)}")
    return result
