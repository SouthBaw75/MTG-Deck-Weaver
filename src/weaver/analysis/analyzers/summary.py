"""Deck summary: a lightweight overview section that always runs.

Kept deliberately simple — it reports composition facts (counts, resolution
status) that don't belong to any single specialist analyzer.
"""

from __future__ import annotations

from weaver.analysis.base import AnalysisSection

ORDER = 0


def analyze(deck) -> AnalysisSection:
    section = AnalysisSection(title="Overview")
    total = deck.total_cards
    section.data["total_cards"] = total
    section.data["land_count"] = deck.land_count

    expected = 100
    if deck.commanders:
        section.add("info", f"{len(deck.commanders)} commander(s) declared")
    else:
        section.add("warn", "no commander declared (use a 'Commander' header or *CMDR* marker)")

    if total == expected:
        section.add("ok", f"{total} cards — a legal Commander deck size")
    else:
        sev = "problem" if abs(total - expected) > 0 else "ok"
        section.add(sev, f"{total} cards (Commander decks are exactly {expected})")

    nonland = total - deck.land_count
    section.add("info", f"{deck.land_count} lands / {nonland} nonlands")

    if deck.unresolved:
        section.add(
            "warn",
            f"{len(deck.unresolved)} card(s) not found in the knowledge base "
            "(names below are excluded from analysis)",
        )
    return section
