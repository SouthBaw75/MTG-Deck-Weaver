"""Top-level build orchestration: pool → archetype → score → assemble.

This ties the builder components together and is what the CLI calls. Archetype
resolution is optional — if the archetype data/module is unavailable the build
still runs with a neutral (goodstuff) bias.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from weaver.build.assembler import assemble
from weaver.build.pool import build_pool, commander_color_identity
from weaver.build.scoring import score_pool
from weaver.build.templates import template_for_bracket
from weaver.build.types import BuildRequest, BuildResult

# At/above this bracket the builder proactively completes the best combos it can
# (the deck is meant to be high-power), instead of only flagging them later.
_COMBO_BRACKET = 4
_COMBO_ADDS = {4: 3, 5: 6}  # how many combos to auto-complete per bracket


def _combo_completions(conn, result, pool, request, max_add):
    """Names of missing combo pieces the assembled deck is one card away from,
    limited to cards that are actual pool candidates (already color/Arena/budget
    legal). Best (most-owned, most-popular) combos first."""
    from weaver.analysis.combos import load_combo_index, match_combos

    by_name = {c.name.lower(): c for c in pool}
    deck_names = {result.commander.name}
    if result.partner:
        deck_names.add(result.partner.name)
    deck_names.update(a.candidate.name for a in result.assignments)
    deck_names.update(a.candidate.name for a in result.lands)

    ci = commander_color_identity(result.commander, result.partner)
    combos = load_combo_index(conn, deck_names)
    _present, near = match_combos(deck_names, combos, deck_color_identity=ci or None)

    picks: list[str] = []
    seen: set[str] = set()
    for m in near:
        if len(picks) >= max_add:
            break
        missing = m.missing[0] if m.missing else None
        if not missing:
            continue
        key = missing.lower()
        cand = by_name.get(key)
        # Only add a piece we could legally run: it must be a pool candidate
        # (so it's on-color, within budget, and Arena-legal when arena_only).
        if cand is None or key in seen or cand.name in deck_names:
            continue
        picks.append(cand.name)
        seen.add(key)
    return picks


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


def _enforce_arena(conn, result, pool) -> list[tuple[str, str]]:
    """Belt-and-suspenders for Arena builds: re-verify every nonland pick and
    swap any that aren't on Arena for a legal spare from the pool (same role if
    possible). Normally a no-op (the pool is already Arena-filtered), but it
    guarantees the exported deck imports, and catches stale-data edge cases.
    Returns the (old, new) swaps made. The commander can't be swapped."""
    from weaver.knowledge.arena import is_on_arena

    def on_arena(name: str) -> bool:
        row = conn.execute(
            "SELECT name, games FROM cards WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        return is_on_arena(name, row["games"] if row else None)

    used = {result.commander.name}
    if result.partner:
        used.add(result.partner.name)
    used.update(a.candidate.name for a in result.all_cards)
    spares = [
        c for c in sorted(pool, key=lambda c: c.score, reverse=True)
        if c.name not in used and not c.is_land and on_arena(c.name)
    ]

    swaps: list[tuple[str, str]] = []
    for a in result.assignments:
        if on_arena(a.candidate.name):
            continue
        repl = next((c for c in spares if set(c.tags) & set(a.candidate.tags)), None)
        if repl is None:
            repl = spares[0] if spares else None
        if repl is None:
            continue
        spares.remove(repl)
        swaps.append((a.candidate.name, repl.name))
        a.candidate = repl
        a.score = repl.score
        a.reason = f"Arena-legal swap (was {swaps[-1][0]})"
    return swaps


def build_deck(conn: sqlite3.Connection, request: BuildRequest) -> BuildResult:
    commander, partner, pool = build_pool(conn, request)
    archetype_keys, bias = _archetype_bias(commander, request)
    profile = _synergy_profile(commander, partner, bias)
    score_pool(pool, request, bias, profile)
    template = template_for_bracket(request.bracket)
    result = assemble(commander, partner, pool, request, template)

    # High-power brackets: proactively complete the best combos the deck is one
    # card away from, by re-assembling with those pieces forced in as includes.
    combo_added: list[str] = []
    if request.bracket >= _COMBO_BRACKET:
        max_add = _COMBO_ADDS.get(request.bracket, 3)
        combo_added = _combo_completions(conn, result, pool, request, max_add)
        if combo_added:
            req2 = replace(request, seed_cards=[*request.seed_cards, *combo_added])
            result = assemble(commander, partner, pool, req2, template)

    if archetype_keys:
        result.notes.insert(0, "archetype(s): " + ", ".join(archetype_keys))
    else:
        result.notes.insert(0, "archetype: goodstuff (no strong archetype signal / theme)")
    if request.arena_only:
        result.notes.insert(0, "Arena-only: pool restricted to cards available on MTG Arena (for Brawl).")
        arena_swaps = _enforce_arena(conn, result, pool)
        if arena_swaps:
            result.notes.insert(
                0,
                "Arena guard: replaced " + ", ".join(f"{o}→{n}" for o, n in arena_swaps),
            )
        else:
            result.notes.insert(0, "Arena guard: all non-commander cards verified on MTG Arena.")
        crow = conn.execute(
            "SELECT name, games FROM cards WHERE name = ? COLLATE NOCASE", (commander.name,)
        ).fetchone()
        from weaver.build.pool import _on_arena
        if crow is not None and not _on_arena(crow):
            result.notes.insert(
                0,
                f"Heads up: {commander.name} isn't on MTG Arena, so this deck can't be "
                "imported into Arena Brawl even though the other cards are Arena-legal.",
            )
    if combo_added:
        result.notes.insert(
            0,
            f"auto-completed {len(combo_added)} combo(s) for bracket {request.bracket}: "
            + ", ".join(combo_added),
        )
    result.notes.append(f"pool size after color/legality/budget filter: {len(pool)}")
    return result
