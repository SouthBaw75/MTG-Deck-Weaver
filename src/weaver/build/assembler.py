"""The assembler: turn a scored candidate pool into a legal 100-card deck.

Algorithm (greedy fill + theme flex + demand-sized mana base):

1. Resolve the target shape from the bracket template (role quotas, synergy
   flex, land count) with any request overrides.
2. Fill each role quota with the highest-scored on-color candidates that carry
   a tag in that role group, respecting the singleton rule, the bracket's Game
   Changer cap, and the running budget.
3. Fill the synergy-flex slots with the best remaining candidates (theme bias
   already baked into their score).
4. Build the mana base: take the best on-color utility/fixing lands, then fill
   the rest with basics split by the colored-pip demand of the chosen cards.
5. Return a BuildResult recording every pick's role and reason, plus any role
   whose quota could not be met.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from weaver.analysis.analyzers.manabase import RAMP_TAGS, recommend_land_count
from weaver.build.types import BuildRequest, BuildResult, Candidate, SlotAssignment
from weaver.db.connection import repo_root

_PIP = re.compile(r"\{([^}]+)\}")
_COLORS = ("W", "U", "B", "R", "G")


def _mv_and_ramp(assignments: list[SlotAssignment]) -> tuple[float, int]:
    """Average nonland mana value and ramp-piece count of the chosen spells —
    the inputs the shared land-count formula needs."""
    n = len(assignments) or 1
    total_mv = sum(a.candidate.mana_value for a in assignments)
    avg_mv = round(total_mv / n, 2)
    ramp = sum(1 for a in assignments if any(t in a.candidate.tags for t in RAMP_TAGS))
    return avg_mv, ramp


def _resize_nonlands(
    assignments: list[SlotAssignment],
    nonland_pool: list[Candidate],
    picker: "_Picker",
    target: int,
) -> None:
    """Trim or extend the nonland picks to exactly `target`, so nonlands + lands
    stay at 99. Drops the lowest-value synergy/goodstuff picks first (never seed),
    and extends from the best remaining candidates."""
    if len(assignments) > target:
        drop = len(assignments) - target
        removable = sorted(
            (a for a in assignments if a.role != "seed"),
            key=lambda a: (0 if a.role == "synergy" else 1, a.score),
        )[:drop]
        remove_ids = {id(a) for a in removable}
        for a in removable:
            picker.release(a.candidate)
        assignments[:] = [a for a in assignments if id(a) not in remove_ids]
    else:
        for cand in nonland_pool:
            if len(assignments) >= target:
                break
            if not picker.can_take(cand):
                continue
            picker.take(cand)
            reason = cand.reasons[0] if cand.reasons else "synergy/goodstuff"
            assignments.append(SlotAssignment(cand, "synergy", cand.score, reason))

# Game Changers allowed by bracket (mirrors data/curated/brackets.json).
_GC_LIMIT = {1: 0, 2: 0, 3: 3, 4: None, 5: None}

# Fraction of the mana base that may be nonbasic utility/fixing lands.
_MAX_UTILITY_LAND_FRACTION = 0.45


def _role_group_tags() -> dict[str, list[str]]:
    """group name -> its taxonomy tags, from role_benchmarks.json."""
    path = repo_root() / "data" / "curated" / "role_benchmarks.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {g: spec["tags"] for g, spec in data["role_groups"].items()}


def _pip_demand(cands: list[Candidate]) -> dict[str, int]:
    demand = {c: 0 for c in _COLORS}
    for cand in cands:
        for raw in _PIP.findall(cand.card.mana_cost or ""):
            sym = raw.upper()
            if sym in _COLORS:
                demand[sym] += 1
            elif "/" in sym:
                for p in sym.split("/"):
                    if p in _COLORS:
                        demand[p] += 1
    return demand


class _Picker:
    """Tracks the running deck state and enforces global constraints."""

    def __init__(self, request: BuildRequest, gc_limit: int | None):
        self.request = request
        self.gc_limit = gc_limit
        self.chosen: set[str] = set()
        self.gc_count = 0
        self.spent = 0.0

    def can_take(self, cand: Candidate) -> bool:
        if cand.name in self.chosen:
            return False
        if cand.is_game_changer and self.gc_limit is not None and self.gc_count >= self.gc_limit:
            return False
        if self.request.budget is not None and cand.price_usd:
            if self.spent + cand.price_usd > self.request.budget:
                return False
        return True

    def take(self, cand: Candidate) -> None:
        self.chosen.add(cand.name)
        if cand.is_game_changer:
            self.gc_count += 1
        if cand.price_usd:
            self.spent += cand.price_usd

    def release(self, cand: Candidate) -> None:
        """Undo take(): free a slot (used when rebalancing lands/combos)."""
        self.chosen.discard(cand.name)
        if cand.is_game_changer:
            self.gc_count = max(0, self.gc_count - 1)
        if cand.price_usd:
            self.spent = max(0.0, self.spent - cand.price_usd)


def assemble(
    commander: Candidate,
    partner: Candidate | None,
    pool: list[Candidate],
    request: BuildRequest,
    template: dict,
) -> BuildResult:
    group_tags = _role_group_tags()
    gc_limit = _GC_LIMIT.get(request.bracket)
    picker = _Picker(request, gc_limit)

    role_quotas: dict[str, int] = dict(template["roles"])
    flex = template.get("synergy_flex", 0)

    nonlands = [c for c in pool if not c.is_land]
    lands = [c for c in pool if c.is_land]
    nonlands.sort(key=lambda c: c.score, reverse=True)
    lands.sort(key=lambda c: c.score, reverse=True)

    assignments: list[SlotAssignment] = []
    unfilled: dict[str, int] = {}

    # --- seed cards (must-includes) ----------------------------------------
    seed_lower = {s.lower() for s in request.seed_cards}
    for cand in nonlands:
        if cand.name.lower() in seed_lower and picker.can_take(cand):
            picker.take(cand)
            assignments.append(SlotAssignment(cand, "seed", cand.score, "requested include"))

    # --- fill role quotas ---------------------------------------------------
    for group, quota in role_quotas.items():
        tags = group_tags.get(group, [])
        filled = 0
        for cand in nonlands:
            if filled >= quota:
                break
            if not picker.can_take(cand):
                continue
            if cand.has_any_tag(tags):
                picker.take(cand)
                reason = cand.reasons[0] if cand.reasons else group
                assignments.append(SlotAssignment(cand, group, cand.score, reason))
                filled += 1
        if filled < quota:
            unfilled[group] = quota - filled

    # --- fill synergy flex with best remaining -----------------------------
    # Absorb any unfilled role slots into the flex count so we still aim for 100.
    flex_target = flex + sum(unfilled.values())
    filled_flex = 0
    for cand in nonlands:
        if filled_flex >= flex_target:
            break
        if not picker.can_take(cand):
            continue
        picker.take(cand)
        reason = cand.reasons[0] if cand.reasons else "synergy/goodstuff"
        assignments.append(SlotAssignment(cand, "synergy", cand.score, reason))
        filled_flex += 1

    # --- size the mana base to the deck's real curve + ramp ----------------
    # Static templates under-land high-curve decks; recompute the land count
    # from the chosen spells with the same formula the Mana Base analyzer uses,
    # then rebalance the nonland slots so the deck stays at 100.
    if request.land_count is not None:
        land_count = request.land_count
    else:
        avg_mv, ramp_count = _mv_and_ramp(assignments)
        land_count = recommend_land_count(avg_mv, ramp_count)
    _resize_nonlands(assignments, nonlands, picker, target=99 - land_count)

    # --- mana base ----------------------------------------------------------
    land_assignments = _build_manabase(commander, partner, assignments, lands, land_count, picker)

    notes: list[str] = []
    total = 1 + (1 if partner else 0) + len(assignments) + sum(a.quantity for a in land_assignments)
    if total != 100:
        notes.append(f"assembled {total} cards (target 100) — pool may be too small to fill every slot")
    if unfilled:
        notes.append(
            "role shortfalls (filled from synergy pool instead): "
            + ", ".join(f"{g} -{n}" for g, n in unfilled.items())
        )

    return BuildResult(
        request=request,
        commander=commander,
        partner=partner,
        assignments=assignments,
        lands=land_assignments,
        unfilled=unfilled,
        notes=notes,
    )


def _build_manabase(
    commander: Candidate,
    partner: Candidate | None,
    nonland_assignments: list[SlotAssignment],
    land_pool: list[Candidate],
    land_count: int,
    picker: _Picker,
) -> list[SlotAssignment]:
    identity = set(commander.color_identity) | (set(partner.color_identity) if partner else set())

    # Utility/fixing lands first (best-scored, on-color), capped.
    utility_cap = int(land_count * _MAX_UTILITY_LAND_FRACTION)
    utility: list[SlotAssignment] = []
    for cand in land_pool:
        if len(utility) >= utility_cap:
            break
        if cand.is_basic_land:
            continue
        if not picker.can_take(cand):
            continue
        picker.take(cand)
        utility.append(SlotAssignment(cand, "land.utility", cand.score, cand.reasons[0] if cand.reasons else "utility land"))

    # Basics fill the remainder, split by colored-pip demand.
    basics_needed = max(0, land_count - len(utility))
    chosen_cands = [a.candidate for a in nonland_assignments]
    demand = _pip_demand(chosen_cands)
    colors = [c for c in _COLORS if c in identity]
    basics: list[SlotAssignment] = []
    if colors and basics_needed:
        total_demand = sum(demand[c] for c in colors) or len(colors)
        _BASIC = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
        allocated = 0
        alloc: dict[str, int] = {}
        for c in colors:
            share = demand[c] / total_demand if total_demand else 1 / len(colors)
            alloc[c] = int(round(basics_needed * share))
            allocated += alloc[c]
        # fix rounding drift
        drift = basics_needed - allocated
        if drift and colors:
            top = max(colors, key=lambda c: demand[c])
            alloc[top] += drift
        for c in colors:
            if alloc[c] > 0:
                basics.append(
                    SlotAssignment(
                        _basic_candidate(_BASIC[c], c),
                        "land.basic",
                        0.0,
                        f"{demand[c]} {c} pips of demand",
                        quantity=alloc[c],
                    )
                )
    elif basics_needed:
        # colorless commander: use Wastes
        basics.append(SlotAssignment(_basic_candidate("Wastes", None), "land.basic", 0.0, "colorless", quantity=basics_needed))

    return utility + basics


def _basic_candidate(name: str, color: str | None) -> Candidate:
    from weaver.knowledge.cardview import CardView

    tl = f"Basic Land — {name}"
    return Candidate(
        name=name,
        oracle_id=f"basic:{name}",
        card=CardView.from_dict({"name": name, "type_line": tl}),
        tags={},
        color_identity=[color] if color else [],
        mana_value=0.0,
        type_line=tl,
        price_usd=0.0,
        edhrec_rank=None,
        is_game_changer=False,
        legal_commander="legal",
    )
