"""Synergy section: how well the deck's cards interact via the mechanic graph.

Reports the deck's synergy density, its strongest interactions, any anti-synergies
(nonbos), and "dead" cards that don't interact with the rest of the deck. Pure:
reads DeckView card tags and the interaction graph, no DB access.
"""

from __future__ import annotations

from weaver.analysis.base import AnalysisSection
from weaver.knowledge.synergy import deck_synergy

ORDER = 25  # sits just after Role Coverage


def analyze(deck) -> AnalysisSection:
    section = AnalysisSection(title="Synergy")

    # Consider nonland, tagged cards (lands/basics rarely carry interaction tags).
    cards = [c for c in deck.cards if c.tags]
    if len(cards) < 2:
        section.add("info", "not enough tagged cards to assess synergy")
        return section

    result = deck_synergy(cards)
    section.data.update(result)

    density = result["density"]
    section.data["density"] = density
    if density >= 1.0:
        sev = "ok"
        verdict = "tightly synergistic — the pieces reinforce each other"
    elif density >= 0.35:
        sev = "info"
        verdict = "reasonable synergy"
    else:
        sev = "warn"
        verdict = "loose — this reads more like a goodstuff pile than an engine"
    section.add(sev, f"Synergy density {density:.2f} per card — {verdict}.")

    # Strongest interactions.
    for a, b, score, note in result["top_pairs"][:5]:
        detail = f" — {note}" if note else ""
        section.add("info", f"{a} + {b} ({score:+.2f}){detail}")

    # Anti-synergies worth surfacing.
    if result["nonbos"]:
        section.add("warn", f"{len(result['nonbos'])} anti-synergy pair(s) detected:")
        for a, b, score, note in result["nonbos"][:4]:
            detail = f" — {note}" if note else ""
            section.add("warn", f"{a} ✕ {b} ({score:+.2f}){detail}")

    # Dead cards: tagged cards contributing ~no synergy with the rest.
    dead = sorted(
        (name for name, s in result["per_card"].items() if abs(s) < 0.05),
    )
    if dead:
        section.data["dead_cards"] = dead
        preview = ", ".join(dead[:6]) + (" …" if len(dead) > 6 else "")
        section.add(
            "info",
            f"{len(dead)} card(s) interact little with the rest of the deck "
            f"(fine as standalone value, but not part of an engine): {preview}",
        )

    return section
