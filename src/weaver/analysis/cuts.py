"""Suggest which cards to cut when adding an upgrade, so the deck stays at 100.

Given a loaded DeckView, rank the nonland, non-commander spells by how safe they
are to remove, and attach a plain-language reason to each. The intent is to give
the user a short menu of *decidable* options — not to auto-cut — when they accept
a combo upgrade in the Analyze view.

Protected (never suggested):
  * commanders,
  * lands (cutting a spell to fit an added spell keeps the land count stable),
  * combo pieces — any card in a combo the deck already has or is one card away
    from completing (that includes the card being added),
  * a card that singlehandedly holds up an under-filled functional role.

Preferred as cuts, in priority order: unresolved (typo/unsupported) cards, then
anti-synergy participants, then role-surplus cards, then the lowest-synergy /
"dead" cards. Pure: reads the DeckView and the curated role benchmark; no DB.
"""

from __future__ import annotations

import json
from pathlib import Path

from weaver.db.connection import repo_root
from weaver.knowledge.synergy import deck_synergy

_BENCHMARK_REL = Path("data") / "curated" / "role_benchmarks.json"

_LABELS = {
    "ramp": "ramp",
    "card_advantage": "card advantage",
    "spot_removal": "spot removal",
    "board_wipe": "board wipes",
    "targeted_disruption": "disruption",
    "protection": "protection",
    "wincon": "win conditions",
}


def _load_role_groups() -> dict:
    try:
        with (repo_root() / _BENCHMARK_REL).open(encoding="utf-8") as fh:
            return json.load(fh).get("role_groups", {}) or {}
    except (OSError, ValueError):
        return {}


def _label(group: str) -> str:
    return _LABELS.get(group, group.replace("_", " "))


def _combo_locked_names(deck) -> set[str]:
    """Cards that must never be cut: they belong to a combo the deck already has
    or is one card away from completing."""
    locked: set[str] = set()
    matches = list(getattr(deck, "combos_present", [])) + list(
        getattr(deck, "combos_near_miss", [])
    )
    for m in matches:
        for name in getattr(m, "cards", []) or []:
            locked.add(name)
    return locked


def _fmt_mv(mv: float) -> str:
    return str(int(mv)) if float(mv).is_integer() else f"{mv:g}"


def suggest_cuts(deck, *, adding: str | None = None, count: int = 5) -> list[dict]:
    """Return up to `count` cut candidates, weakest/safest first. Each item:
    {name, reason, mv, type_line}. `adding` is protected (never suggested)."""
    role_groups = _load_role_groups()

    # Quantity-weighted role coverage, mirroring the Role Coverage analyzer.
    group_tags: dict[str, set] = {
        g: set(spec.get("tags", [])) for g, spec in role_groups.items()
    }
    group_count: dict[str, int] = {
        g: sum(c.quantity for c in deck.cards if tags & set(c.tags))
        for g, tags in group_tags.items()
    }

    def groups_of(card) -> list[str]:
        ct = set(card.tags)
        return [g for g, tags in group_tags.items() if tags & ct]

    def under_min(group: str) -> bool:
        return group_count.get(group, 0) <= int(role_groups.get(group, {}).get("min", 0))

    def over_ideal(group: str) -> bool:
        spec = role_groups.get(group, {})
        return group_count.get(group, 0) > int(spec.get("ideal", spec.get("min", 0)))

    locked = _combo_locked_names(deck)
    if adding:
        locked.add(adding)
    commander_names = {c.name for c in deck.commanders}

    # Synergy across tagged nonland, non-commander spells.
    tagged = [
        c for c in deck.cards if c.tags and not c.is_land and not c.is_commander
    ]
    syn = deck_synergy(tagged) if len(tagged) >= 2 else {"per_card": {}, "nonbos": []}
    per_card = syn.get("per_card", {})
    nonbo_partner: dict[str, str] = {}
    for a, b, _score, _note in syn.get("nonbos", []):
        nonbo_partner.setdefault(a, b)
        nonbo_partner.setdefault(b, a)

    suggestions: list[dict] = []
    seen: set[str] = set()
    for card in deck.cards:
        if card.is_land or card.is_commander:
            continue
        name = card.name
        if name in commander_names or name in locked or name in seen:
            continue
        seen.add(name)

        groups = groups_of(card)
        # Protect a card that is holding up an under-filled role on its own.
        if groups and all(under_min(g) for g in groups):
            continue

        if not card.resolved:
            score = 100.0
            reason = "not found in the card database — likely a typo or unsupported card"
        elif name in nonbo_partner:
            score = 50.0
            reason = f"anti-synergy with {nonbo_partner[name]}"
        else:
            syn_score = per_card.get(name, 0.0)
            surplus = [g for g in groups if over_ideal(g)]
            if groups and surplus and len(surplus) == len(groups):
                g = surplus[0]
                spec = role_groups.get(g, {})
                ideal = spec.get("ideal", spec.get("min", 0))
                score = 20.0 - syn_score
                reason = (
                    f"surplus {_label(g)} — the deck has {group_count.get(g, 0)}, "
                    f"about {ideal} is plenty"
                )
            elif abs(syn_score) < 0.05:
                score = 10.0
                reason = "interacts little with the rest of the deck"
            else:
                score = 5.0 - syn_score
                reason = f"low synergy ({syn_score:+.2f}) with the rest of the deck"

        suggestions.append(
            {
                "name": name,
                "reason": reason,
                "mv": card.mana_value,
                "mv_label": _fmt_mv(card.mana_value),
                "type_line": card.type_line,
                "_score": score,
            }
        )

    suggestions.sort(key=lambda s: (s["_score"], s["mv"]), reverse=True)
    top = suggestions[:count]
    for s in top:
        s.pop("_score", None)
    return top
