"""Role coverage: does the deck have enough ramp, draw, interaction, etc.?

Commander decks win or fall over on their functional skeleton, not their theme.
The community rules of thumb — roughly a dozen ramp pieces, ~10 sources of card
advantage, ~10 pieces of interaction split across spot removal and a couple of
board wipes, a win condition and some protection for it — are encoded in
``data/curated/role_benchmarks.json`` as tag GROUPS with target counts.

This analyzer counts how many deck cards fill each role and compares against the
benchmark, surfacing the biggest gap as the headline. It is pure given a
benchmark dict; when none is passed it loads the curated file relative to the
repo root and degrades gracefully (an info finding) if the file is missing.
"""

from __future__ import annotations

import json
from pathlib import Path

from weaver.analysis.base import AnalysisSection
from weaver.db.connection import repo_root

ORDER = 20

_BENCHMARK_REL = Path("data") / "curated" / "role_benchmarks.json"

# Human-readable labels for the role group keys.
_LABELS = {
    "ramp": "Ramp",
    "card_advantage": "Card advantage",
    "spot_removal": "Spot removal",
    "board_wipe": "Board wipes",
    "targeted_disruption": "Disruption",
    "protection": "Protection",
    "wincon": "Win conditions",
}

# Below this fraction of `min` the deficiency is severe (problem, not warn).
_SEVERE_FRACTION = 0.6


def _load_benchmark() -> dict | None:
    path = repo_root() / _BENCHMARK_REL
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _label(group: str) -> str:
    return _LABELS.get(group, group.replace("_", " ").title())


def _group_count(deck, tags: list[str]) -> int:
    """Quantity-weighted count of cards carrying ANY tag in `tags`.

    De-duplicated per card: a card tagged both ``removal.spot.creature`` and
    ``removal.spot.any`` counts once toward spot_removal (its full quantity).
    """
    tagset = set(tags)
    total = 0
    for card in deck.cards:
        if tagset.intersection(card.tags):
            total += card.quantity
    return total


def _readout(label: str, count: int, minimum: int, ideal: int) -> tuple[str, str]:
    """Return (severity, one-line message) for a single role group."""
    want = f"want ~{ideal}"
    if count >= ideal:
        return "ok", f"{label}: {count} ({want}) ✔ solid"
    if minimum > 0 and count < minimum * _SEVERE_FRACTION:
        return "problem", f"{label}: {count} ({want}) ▼ well short of {minimum}"
    if count < minimum:
        return "warn", f"{label}: {count} ({want}) ▲ a bit light (min {minimum})"
    # Between min and ideal — functional but not fully rounded out.
    return "info", f"{label}: {count} ({want}) ≈ ok, could add more"


def analyze(deck, benchmark: dict | None = None) -> AnalysisSection:
    section = AnalysisSection(title="Role Coverage")

    if benchmark is None:
        benchmark = _load_benchmark()
    if not benchmark or not benchmark.get("role_groups"):
        section.add(
            "info",
            "role benchmark data unavailable — skipping role coverage "
            f"(expected {_BENCHMARK_REL})",
        )
        return section

    role_groups: dict = benchmark["role_groups"]
    section.data["source"] = benchmark.get("source", "")

    roles: dict[str, dict] = {}
    # Track the single worst gap (largest shortfall below `min`) for the headline.
    biggest_gap_group: str | None = None
    biggest_gap: int = 0

    per_group_readouts: list[tuple[str, str, str]] = []  # (group, severity, msg)
    for group, spec in role_groups.items():
        tags = spec.get("tags", [])
        minimum = int(spec.get("min", 0))
        ideal = int(spec.get("ideal", minimum))
        count = _group_count(deck, tags)
        roles[group] = {"count": count, "min": minimum, "ideal": ideal}

        severity, message = _readout(_label(group), count, minimum, ideal)
        per_group_readouts.append((group, severity, message))

        shortfall = minimum - count
        if shortfall > biggest_gap:
            biggest_gap = shortfall
            biggest_gap_group = group

    section.data["roles"] = roles

    # Headline: the single biggest gap (or an all-clear).
    met = sum(1 for g in roles.values() if g["count"] >= g["min"])
    ideal_met = sum(1 for g in roles.values() if g["count"] >= g["ideal"])
    total_groups = len(roles)
    section.data["roles_meeting_min"] = met
    section.data["roles_meeting_ideal"] = ideal_met
    section.data["total_groups"] = total_groups
    if biggest_gap_group is not None:
        r = roles[biggest_gap_group]
        section.add(
            "problem" if r["min"] > 0 and r["count"] < r["min"] * _SEVERE_FRACTION else "warn",
            f"Biggest gap: {_label(biggest_gap_group)} at {r['count']} "
            f"(need at least {r['min']}, ideally {r['ideal']})",
        )
    else:
        section.add(
            "ok",
            f"All {total_groups} functional roles meet their minimums "
            f"({ideal_met}/{total_groups} at the ideal target)",
        )

    # Per-group readouts, worst-first so problems lead.
    _rank = {"problem": 0, "warn": 1, "info": 2, "ok": 3}
    for _group, severity, message in sorted(
        per_group_readouts, key=lambda t: _rank[t[1]]
    ):
        section.add(severity, message)

    return section
