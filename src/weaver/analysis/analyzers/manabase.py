"""Mana-base analyzer: land count, color sources vs. pip demand, and curve.

This analyzer is pure (no DB / no network): everything it needs is already on
the DeckView the loader handed it. It is tuned for 100-card Commander singleton
decks, so all of the constants below are Commander heuristics, not 60-card
constructed numbers.

Everything here is deliberately explainable — the exact constants matter less
than being transparent about them, so the reasoning is echoed into findings and
into ``section.data['recommendations']``.

Heuristics encoded (all documented inline where used):

* **Recommended land count.** ``base = 31 + 3 * avg_mv`` of the nonland,
  non-commander spells, then ``-1`` land per ``RAMP_PER_LAND`` ramp pieces beyond
  a small ``RAMP_BASELINE``, clamped to a sane 33-42 window. A low curve and/or a
  fat ramp package pushes the recommendation down; a top-heavy curve pushes it up.

* **Color sources vs. pips (simplified Karsten).** Frank Karsten's mana-source
  tables say that in a ~100-card singleton deck you want roughly 14+ sources of a
  color to reliably cast a single-pip card near curve, more for double pips, and
  fewer for a light splash. We approximate that with a pip-demand-scaled target
  (see ``_source_target``). A color's *sources* are the lands whose color identity
  contains it plus the repeatable mana producers (rocks/dorks) whose color
  identity contains it — an approximation, since we read produced colors off
  color identity rather than the produced-mana list.

* **Pip demand.** Parsed from each spell's ``mana_cost`` string ("{2}{G}{G}"
  → 2 green pips). Generic ({2}, {X}, {C}) contribute nothing to colored demand;
  true hybrid ({G/U}) counts as **half a pip to each** color; Phyrexian ({G/P})
  counts as a **full pip** of its color.
"""

from __future__ import annotations

import re

from weaver.analysis.base import AnalysisSection

ORDER = 30

# --- tunable heuristics (Commander, 100-card singleton) --------------------
COLORS = ("W", "U", "B", "R", "G")
_COLOR_NAME = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}

RAMP_TAGS = ("ramp.rock", "ramp.land", "ramp.dork", "ramp.ritual")
# Repeatable, on-board mana producers double as colored mana sources.
SOURCE_RAMP_TAGS = ("ramp.rock", "ramp.dork")

# recommended_lands = round(31 + 3 * avg_mv) - ramp_reduction, clamped.
_LAND_BASE_CONST = 31.0
_LAND_MV_COEFF = 3.0
RAMP_BASELINE = 2          # a couple of ramp pieces are assumed "for free"
RAMP_PER_LAND = 3          # every 3 ramp pieces beyond baseline shaves 1 land
_MAX_RAMP_REDUCTION = 4
_LAND_FLOOR, _LAND_CEIL = 33, 42

# top-heavy: this many 5+ MV spells with a thin ramp package is a warning.
_TOP_HEAVY_5PLUS = 10
_TOP_HEAVY_RAMP = 8

_SYMBOL = re.compile(r"\{([^}]+)\}")


def _source_target(pips: float) -> int:
    """Simplified Karsten source target for a color, scaled by pip demand.

    Karsten's tables land around ~14 sources for a reliable single colored pip
    in a 100-card deck; heavier commitments want more, splashes fewer.
    """
    if pips >= 12:
        return 16      # a double-pip / heavily-invested main color
    if pips >= 6:
        return 14      # a solid main color
    if pips >= 3:
        return 10      # secondary color
    return 6           # light splash


def _parse_pips(mana_cost: str) -> dict[str, float]:
    """Colored-pip contribution of a mana_cost string.

    Generic/{X}/{C} → nothing. Hybrid {G/U} → 0.5 to each color. Phyrexian
    {G/P} → 1.0 to its color.
    """
    pips: dict[str, float] = {c: 0.0 for c in COLORS}
    for raw in _SYMBOL.findall(mana_cost or ""):
        sym = raw.upper()
        if "/" in sym:
            parts = sym.split("/")
            color_parts = [p for p in parts if p in COLORS]
            if not color_parts:
                continue
            if "P" in parts:            # Phyrexian: full pip of its color(s)
                for p in color_parts:
                    pips[p] += 1.0
            else:                       # hybrid: half a pip to each color
                for p in color_parts:
                    pips[p] += 0.5
        elif sym in COLORS:
            pips[sym] += 1.0
        # generic (digits), {X}, {C}, {S}, etc. → no colored demand
    return pips


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def analyze(deck) -> AnalysisSection:
    section = AnalysisSection(title="Mana Base")

    # ---- land count & average mana value ----------------------------------
    land_count = deck.land_count

    spells = [c for c in deck.nonland_spells if c.resolved]
    n_spells = sum(c.quantity for c in spells)
    total_mv = sum(c.mana_value * c.quantity for c in spells)
    avg_mv = round(total_mv / n_spells, 2) if n_spells else 0.0

    excluded = sum(c.quantity for c in deck.cards if not c.is_land and not c.resolved)

    # ---- ramp package ------------------------------------------------------
    ramp_by_tag = {t: deck.tag_count(t) for t in RAMP_TAGS}
    # A card may carry >1 ramp tag; count distinct copies for the total.
    ramp_count = sum(
        c.quantity for c in deck.cards if any(t in c.tags for t in RAMP_TAGS)
    )

    # ---- recommended land count -------------------------------------------
    base = _LAND_BASE_CONST + _LAND_MV_COEFF * avg_mv
    ramp_reduction = min(
        _MAX_RAMP_REDUCTION,
        max(0, ramp_count - RAMP_BASELINE) // RAMP_PER_LAND,
    )
    recommended = int(round(base)) - ramp_reduction
    recommended = max(_LAND_FLOOR, min(_LAND_CEIL, recommended))
    land_low, land_high = recommended - 1, recommended + 1

    # ---- color sources vs. pip demand -------------------------------------
    sources_by_color = {c: 0 for c in COLORS}
    for card in deck.cards:
        if card.is_land:
            for col in card.color_identity:
                if col in sources_by_color:
                    sources_by_color[col] += card.quantity
        elif card.resolved and any(t in card.tags for t in SOURCE_RAMP_TAGS):
            for col in card.color_identity:
                if col in sources_by_color:
                    sources_by_color[col] += card.quantity

    pips_by_color = {c: 0.0 for c in COLORS}
    # Pip demand comes from every castable nonland card, commanders included
    # (you have to pay the commander's cost every time you recast it).
    for card in deck.cards:
        if card.is_land or not card.resolved:
            continue
        for col, p in _parse_pips(card.card.mana_cost).items():
            pips_by_color[col] += p
    pips_by_color = {c: round(v, 1) for c, v in pips_by_color.items()}

    # ---- curve histogram (nonland, non-commander spells) ------------------
    curve = {k: 0 for k in range(8)}  # key 7 == "7 or more"
    for card in spells:
        b = min(7, max(0, int(round(card.mana_value))))
        curve[b] += card.quantity
    curve_str = " ".join(f"{k if k < 7 else '7+'}:{curve[k]}" for k in range(8))

    # ---- stash structured results -----------------------------------------
    color_targets = {
        c: _source_target(pips_by_color[c]) for c in COLORS if pips_by_color[c] > 0
    }
    recommendations = {
        "recommended_lands": recommended,
        "land_range": [land_low, land_high],
        "effective_sources": land_count + ramp_count,
        "color_targets": color_targets,
        "reasoning": (
            f"base round(31 + 3*avg_mv={_fmt(avg_mv)}) = {int(round(base))}, "
            f"minus {ramp_reduction} for {ramp_count} ramp piece(s)"
        ),
    }
    section.data.update(
        land_count=land_count,
        avg_mv=avg_mv,
        curve=curve,
        curve_str=curve_str,
        sources_by_color=sources_by_color,
        pips_by_color=pips_by_color,
        ramp_by_tag=ramp_by_tag,
        ramp_count=ramp_count,
        excluded_unresolved=excluded,
        recommendations=recommendations,
    )

    # ---- findings: land count ---------------------------------------------
    section.add(
        "info",
        f"Land recommendation: {recommended} (range {land_low}-{land_high}) — "
        f"{recommendations['reasoning']}.",
    )
    diff = land_count - recommended
    if abs(diff) <= 1:
        section.add("ok", f"{land_count} lands is on target for this curve.")
    elif abs(diff) <= 2:
        direction = "a touch high" if diff > 0 else "a touch low"
        section.add(
            "info",
            f"{land_count} lands is {direction} vs. the ~{recommended} target — minor.",
        )
    else:
        direction = "high" if diff > 0 else "low"
        section.add(
            "warn",
            f"{land_count} lands is meaningfully {direction} "
            f"(target ~{recommended}, range {land_low}-{land_high}).",
        )
    section.add(
        "info",
        f"Effective mana sources: {land_count + ramp_count} "
        f"({land_count} lands + {ramp_count} ramp), avg nonland MV {_fmt(avg_mv)}.",
    )

    # ---- findings: color sources vs pips ----------------------------------
    active = [c for c in COLORS if pips_by_color[c] > 0 or sources_by_color[c] > 0]
    if active:
        summary = ", ".join(
            f"{c} {sources_by_color[c]}src/{_fmt(pips_by_color[c])}pip" for c in active
        )
        section.add("info", f"Color sources vs. pips — {summary}.")
    for c in COLORS:
        pips = pips_by_color[c]
        if pips <= 0:
            continue
        target = _source_target(pips)
        have = sources_by_color[c]
        if have >= target:
            section.add(
                "ok",
                f"{_COLOR_NAME[c].capitalize()}: {have} sources meets the "
                f"~{target} target for {_fmt(pips)} pips.",
            )
        elif have >= target - 3:
            section.add(
                "info",
                f"{_COLOR_NAME[c].capitalize()}: {have} sources is a little light "
                f"for {_fmt(pips)} pips (~{target} wanted).",
            )
        else:
            section.add(
                "warn",
                f"{_COLOR_NAME[c].capitalize()}: only {have} sources for "
                f"{_fmt(pips)} pips of demand (~{target} wanted) — under-supported.",
            )

    # ---- findings: curve ---------------------------------------------------
    section.add("info", f"MV curve (nonland spells): {curve_str}.")
    five_plus = curve[5] + curve[6] + curve[7]
    if five_plus >= _TOP_HEAVY_5PLUS and ramp_count < _TOP_HEAVY_RAMP:
        section.add(
            "warn",
            f"Top-heavy curve: {five_plus} spells at MV 5+ with only "
            f"{ramp_count} ramp piece(s) — expect slow, clunky starts.",
        )

    # ---- findings: ramp package -------------------------------------------
    ramp_breakdown = ", ".join(
        f"{t.split('.')[1]} {ramp_by_tag[t]}" for t in RAMP_TAGS if ramp_by_tag[t]
    ) or "none"
    section.add("info", f"Ramp package: {ramp_count} piece(s) ({ramp_breakdown}).")

    # ---- findings: unresolved ---------------------------------------------
    if excluded:
        section.add(
            "info",
            f"{excluded} unresolved nonland card(s) excluded from pip/curve math.",
        )

    return section
