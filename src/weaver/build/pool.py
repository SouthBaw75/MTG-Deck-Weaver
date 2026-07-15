"""Candidate pool: the legal, eligible cards the builder may choose from.

Given a commander (and optional partner), this computes the color identity and
returns every card in the knowledge base that is:
  - legal in Commander (not banned),
  - within the commander's color identity,
  - affordable per the per-card budget guard (if a budget is set),
  - in the owned-collection set (if one was provided),
  - not the commander(s) themselves.
"""

from __future__ import annotations

import json
import sqlite3

from weaver.build.types import BuildRequest, Candidate
from weaver.knowledge.cardview import CardView


def _row_to_candidate(row) -> Candidate:
    return Candidate(
        name=row["name"],
        oracle_id=row["oracle_id"],
        card=CardView.from_row(row),
        tags={},  # filled below
        color_identity=json.loads(row["color_identity"]) if row["color_identity"] else [],
        mana_value=row["mana_value"] or 0.0,
        type_line=row["type_line"] or "",
        price_usd=row["price_usd"],
        edhrec_rank=row["edhrec_rank"],
        is_game_changer=bool(row["is_game_changer"]),
        legal_commander=row["legal_commander"],
    )


def resolve_commander(conn: sqlite3.Connection, name: str) -> Candidate | None:
    row = conn.execute(
        "SELECT * FROM cards WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row is None:
        return None
    cand = _row_to_candidate(row)
    cand.tags = _tags_for(conn, cand.oracle_id)
    return cand


def _tags_for(conn: sqlite3.Connection, oracle_id: str) -> dict[str, float]:
    return {
        r["tag"]: r["quality"]
        for r in conn.execute(
            "SELECT tag, quality FROM card_tags WHERE oracle_id = ?", (oracle_id,)
        )
    }


def commander_color_identity(commander: Candidate, partner: Candidate | None) -> set[str]:
    ci = set(commander.color_identity)
    if partner:
        ci |= set(partner.color_identity)
    return ci


def build_pool(conn: sqlite3.Connection, request: BuildRequest) -> tuple[Candidate, Candidate | None, list[Candidate]]:
    """Return (commander, partner, candidates). Raises ValueError if the
    commander can't be resolved."""
    commander = resolve_commander(conn, request.commander)
    if commander is None:
        raise ValueError(f"commander not found: {request.commander!r}")
    partner = resolve_commander(conn, request.partner) if request.partner else None

    ci = commander_color_identity(commander, partner)
    exclude = {commander.name.lower()}
    if partner:
        exclude.add(partner.name.lower())

    owned_lower = {n.lower() for n in request.owned} if request.owned else None
    # Per-card budget guard: nothing above the whole-deck budget, and a soft cap
    # so a single card can't eat the entire budget in a cheap build.
    per_card_cap = None
    if request.budget is not None:
        per_card_cap = max(request.budget * 0.5, 5.0)

    candidates: list[Candidate] = []
    for row in conn.execute("SELECT * FROM cards"):
        name = row["name"]
        if name.lower() in exclude:
            continue
        if row["legal_commander"] == "banned":
            continue
        card_ci = json.loads(row["color_identity"]) if row["color_identity"] else []
        if not set(card_ci).issubset(ci):
            continue
        if owned_lower is not None and name.lower() not in owned_lower:
            continue
        price = row["price_usd"]
        if per_card_cap is not None and price is not None and price > per_card_cap:
            continue
        cand = _row_to_candidate(row)
        cand.tags = _tags_for(conn, cand.oracle_id)
        candidates.append(cand)
    return commander, partner, candidates
