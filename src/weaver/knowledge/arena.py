"""Single source of truth for 'is this card on MTG Arena?'.

Primary signal is Scryfall's `games` array. A small curated override file
(data/curated/arena_overrides.json) can force a verdict when that data is
wrong or stale — e.g. a Commander-set card mislabeled as Arena-available, or a
card that only reached Arena later than our snapshot.

    {"not_arena": ["Bilbo, Luckwearer // Burglar's Plot"],
     "on_arena":  []}
"""

from __future__ import annotations

import json
from pathlib import Path

from weaver.db.connection import repo_root

_OVERRIDE_REL = Path("data") / "curated" / "arena_overrides.json"
_cache: dict | None = None


def _overrides() -> tuple[frozenset[str], frozenset[str]]:
    global _cache
    if _cache is None:
        not_a: frozenset[str] = frozenset()
        on_a: frozenset[str] = frozenset()
        try:
            data = json.loads((repo_root() / _OVERRIDE_REL).read_text(encoding="utf-8"))
            not_a = frozenset(n.lower() for n in data.get("not_arena", []))
            on_a = frozenset(n.lower() for n in data.get("on_arena", []))
        except (OSError, ValueError):
            pass
        _cache = {"not": not_a, "on": on_a}
    return _cache["not"], _cache["on"]


def reload_overrides() -> None:
    """Drop the cached override sets (tests / after editing the file)."""
    global _cache
    _cache = None


def is_on_arena(name: str | None, games_raw) -> bool:
    """True if the card is playable on MTG Arena. Curated overrides win over
    the raw `games` data; otherwise 'arena' must appear in `games`."""
    not_a, on_a = _overrides()
    key = (name or "").lower()
    if key in not_a:
        return False
    if key in on_a:
        return True
    if not games_raw:
        return False
    try:
        return "arena" in json.loads(games_raw)
    except (ValueError, TypeError):
        return False
