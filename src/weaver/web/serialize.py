"""Serialize the engine's structured output to plain JSON for the web API.

The analyzers and dossier were written for a terminal (rich markup like
``[bold]`` and ``[dim]`` appears in some messages). This module strips that
markup and flattens the dataclasses into JSON-friendly dicts, so the frontend
never has to know about rich or the internal types.
"""

from __future__ import annotations

import re
import sqlite3
import json as _json

from weaver.analysis.base import AnalysisSection
from weaver.build.types import BuildResult

_MARKUP = re.compile(r"\[/?[a-z0-9#_ ]+\]", re.IGNORECASE)


def strip_markup(text: str) -> str:
    return _MARKUP.sub("", text or "")


# ---- analyzer sections ----------------------------------------------------
def section_to_dict(section: AnalysisSection) -> dict:
    return {
        "title": section.title,
        "worst_severity": section.worst_severity,
        "findings": [
            {"severity": f.severity, "message": strip_markup(f.message)}
            for f in section.findings
        ],
        "data": _jsonable(section.data),
    }


def analysis_to_dict(deck, sections: list[AnalysisSection]) -> dict:
    # Resolved cards that aren't on MTG Arena — surfaced so an Arena deck can be
    # warned about cards that will fail to import into Brawl.
    off_arena = sorted(
        {c.name for c in deck.cards if c.on_arena is False and not c.is_commander}
    )
    return {
        "commanders": [c.name for c in deck.commanders],
        "total_cards": deck.total_cards,
        "land_count": deck.land_count,
        "unresolved": list(deck.unresolved),
        "unresolved_detail": list(getattr(deck, "unresolved_detail", []) or []),
        "off_arena": off_arena,
        "sections": [section_to_dict(s) for s in sections],
    }


# ---- build result ---------------------------------------------------------
_ROLE_LABEL = {
    "seed": "Requested includes",
    "ramp": "Ramp",
    "card_advantage": "Card advantage",
    "spot_removal": "Spot removal",
    "board_wipe": "Board wipes",
    "targeted_disruption": "Disruption",
    "protection": "Protection",
    "wincon": "Win conditions",
    "synergy": "Synergy / theme",
}
_ROLE_ORDER = list(_ROLE_LABEL)


def build_result_to_dict(result: BuildResult) -> dict:
    groups: dict[str, list] = {}
    for a in result.assignments:
        groups.setdefault(a.role, []).append(
            {
                "name": a.candidate.name,
                "reason": strip_markup(a.reason),
                "score": round(a.score, 3),
                "price_usd": a.candidate.price_usd,
                "mana_value": a.candidate.mana_value,
                "type_line": a.candidate.type_line,
            }
        )
    ordered_groups = [
        {"role": r, "label": _ROLE_LABEL.get(r, r), "cards": groups[r]}
        for r in _ROLE_ORDER
        if r in groups
    ]
    lands = [
        {"name": a.candidate.name, "quantity": a.quantity, "role": a.role}
        for a in result.lands
    ]
    spent = sum((a.candidate.price_usd or 0) for a in result.all_cards)
    return {
        "commander": result.commander.name,
        "partner": result.partner.name if result.partner else None,
        "bracket": result.request.bracket,
        "budget": result.request.budget,
        "arena_only": result.request.arena_only,
        "spent_usd": round(spent, 2),
        "total_cards": result.total_cards,
        "notes": [strip_markup(n) for n in result.notes],
        "unfilled": dict(result.unfilled),
        "groups": ordered_groups,
        "lands": lands,
        "land_count": sum(a.quantity for a in result.lands),
        "decklist": result.to_decklist(),
    }


from urllib.parse import quote as _quote


def _image_url(row) -> str:
    """A Scryfall image URL for this card. Uses the exact printing when we have
    a Scryfall id, else falls back to an exact-name lookup (works for any real
    card). Loaded client-side by the browser, so it needs internet — the rest
    of the app stays offline.
    """
    sid = _try(row, "scryfall_id")
    if sid:
        return f"https://api.scryfall.com/cards/{sid}?format=image&version=normal"
    return f"https://api.scryfall.com/cards/named?exact={_quote(row['name'])}&format=image&version=normal"


def _try(row, col):
    try:
        return row[col]
    except (IndexError, KeyError):
        return None


# ---- card lookup ----------------------------------------------------------
def card_to_dict(conn: sqlite3.Connection, row) -> dict:
    roles = [
        {"tag": r["tag"], "quality": r["quality"]}
        for r in conn.execute(
            "SELECT tag, quality FROM card_tags WHERE oracle_id = ? ORDER BY quality DESC",
            (row["oracle_id"],),
        )
    ]
    combo_count = conn.execute(
        "SELECT COUNT(*) FROM combo_cards WHERE card_name = ?", (row["name"],)
    ).fetchone()[0]
    return {
        "name": row["name"],
        "mana_cost": row["mana_cost"],
        "mana_value": row["mana_value"],
        "type_line": row["type_line"],
        "oracle_text": row["oracle_text"],
        "color_identity": _load(row["color_identity"]),
        "legal_commander": row["legal_commander"],
        "is_game_changer": bool(row["is_game_changer"]),
        "edhrec_rank": row["edhrec_rank"],
        "price_usd": row["price_usd"],
        "roles": roles,
        "combo_count": combo_count,
        "image_url": _image_url(row),
    }


# ---- helpers --------------------------------------------------------------
def _load(raw):
    return _json.loads(raw) if raw else []


def _jsonable(obj):
    """Recursively coerce section.data into JSON-safe primitives."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)
