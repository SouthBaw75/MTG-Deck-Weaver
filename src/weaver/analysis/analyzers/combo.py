"""Combo section: win lines the deck already has, and ones it's one card from.

Reads the combo matches the loader attached to the DeckView (deck.combos_present
and deck.combos_near_miss). Pure: no DB access here.
"""

from __future__ import annotations

from weaver.analysis.base import AnalysisSection

ORDER = 60

# Cap how many near-miss suggestions we list so the report stays readable.
_MAX_NEAR = 8


def _produces_str(match) -> str:
    return ", ".join(match.produces) if match.produces else "a combo result"


def analyze(deck) -> AnalysisSection:
    section = AnalysisSection(title="Combos & Win Lines")

    present = list(getattr(deck, "combos_present", []))
    near = list(getattr(deck, "combos_near_miss", []))
    section.data["present_count"] = len(present)
    section.data["near_miss_count"] = len(near)
    section.data["present"] = [
        {"id": m.combo_id, "cards": m.cards, "produces": m.produces} for m in present
    ]
    section.data["near_miss"] = [
        {"id": m.combo_id, "cards": m.cards, "missing": m.missing, "produces": m.produces}
        for m in near
    ]

    if not present and not near:
        section.add(
            "info",
            "no known combos detected (this reflects the combo database, which "
            "may be empty until `weaver update` mirrors Commander Spellbook)",
        )
        return section

    # Present combos — actual win lines / engines in the deck.
    if present:
        section.add(
            "ok" if len(present) <= 3 else "info",
            f"{len(present)} known combo(s) already in the deck",
        )
        for m in present:
            section.add("info", f"{' + '.join(m.cards)} → {_produces_str(m)}")
    else:
        section.add("info", "no complete combos in the deck as built")

    # Near-miss — one card away, and legal in the deck's colors.
    if near:
        section.add(
            "info",
            f"{len(near)} combo(s) are one card away (missing card is in your colors)",
        )
        for m in near[:_MAX_NEAR]:
            missing = m.missing[0] if m.missing else "?"
            section.add(
                "info",
                f"add [bold]{missing}[/bold] → {' + '.join(m.cards)} "
                f"({_produces_str(m)})",
            )
        if len(near) > _MAX_NEAR:
            section.add("info", f"…and {len(near) - _MAX_NEAR} more one-card-away combos")

    return section
