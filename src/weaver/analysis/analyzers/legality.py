"""Legality & Bracket analyzer.

Rule-accurate Commander (EDH) legality checks plus a Game-Changer-driven
*floor* on which bracket the deck can legally sit in. Pure: everything is read
off the DeckView / DeckCard — no DB, no network.

Scope note: this analyzer only computes the bracket *floor* implied by the
number of Game Changers in the deck. Full bracket estimation (tutors, fast
mana, two-card combos, mass land denial, extra-turn chains) is the job of a
later, dedicated analyzer.
"""

from __future__ import annotations

import json
from pathlib import Path

from weaver.analysis.base import AnalysisSection
from weaver.db.connection import repo_root

ORDER = 10

# Cards whose own text overrides the singleton rule. We prefer to detect this
# from oracle text ("any number of cards named ~" / "up to N cards named ~"),
# but keep a small known-name set as a robust fallback for fixtures/rows whose
# oracle text is sparse.
_ANY_NUMBER_NAMES = {
    "persistent petitioners",
    "relentless rats",
    "rat colony",
    "shadowborn apostle",
    "dragon's approach",
    "seven dwarves",
    "nazgûl",
    "nazgul",
    "templar knight",
}

# Oracle phrases that support running two commanders together.
_PARTNER_PHRASES = (
    "partner with",
    "partner",
    "friends forever",
)


def analyze(deck) -> AnalysisSection:
    section = AnalysisSection(title="Legality & Bracket")
    violations: dict[str, list] = {}
    section.data["violations"] = violations

    resolved = [c for c in deck.cards if c.resolved]
    unresolved_cards = [c for c in deck.cards if not c.resolved]

    _check_deck_size(deck, section)
    _check_singleton(deck, section, violations)
    commander_identity = _check_commanders(deck, section, violations)
    _check_color_identity(deck, commander_identity, section, violations)
    _check_banned(deck, section, violations)
    _check_game_changers(deck, section)

    if unresolved_cards:
        names = ", ".join(sorted({c.name for c in unresolved_cards}))
        section.add(
            "info",
            f"{len(unresolved_cards)} card(s) could not be resolved and were "
            f"skipped by legality checks: {names}",
        )
    section.data["unresolved"] = [c.name for c in unresolved_cards]

    if not section.findings:
        section.add("ok", "no legality problems found")
    return section


# ---- deck size -----------------------------------------------------------

def _check_deck_size(deck, section) -> None:
    total = deck.total_cards
    section.data["deck_size"] = total
    if total == 100:
        section.add("ok", "100 cards including commander(s) — legal Commander deck size")
    else:
        section.add(
            "problem",
            f"deck has {total} cards; a Commander deck must be exactly 100 "
            "including the commander(s)",
        )


# ---- singleton -----------------------------------------------------------

def _any_number_allowed(dc) -> bool:
    if dc.name.lower() in _ANY_NUMBER_NAMES:
        return True
    if dc.card is None:
        return False
    text = dc.card.text_lower
    if "cards named" not in text:
        return False
    return "any number" in text or "up to" in text


def _check_singleton(deck, section, violations) -> None:
    offenders = []
    for dc in deck.cards:
        if dc.quantity <= 1:
            continue
        if dc.is_basic_land:
            continue
        if _any_number_allowed(dc):
            continue
        offenders.append((dc.name, dc.quantity))
    if offenders:
        violations["singleton"] = [{"name": n, "quantity": q} for n, q in offenders]
        for name, qty in offenders:
            section.add(
                "problem",
                f"singleton violation: {qty}x {name} (max 1 outside basic lands "
                "and cards that allow any number)",
            )
    else:
        section.add("ok", "singleton rule satisfied")


# ---- commanders ----------------------------------------------------------

def _is_legal_commander_card(dc) -> bool:
    cv = dc.card
    if cv is None:
        return False
    if "legendary" in cv.supertypes and "creature" in cv.types:
        return True
    if "can be your commander" in cv.text_lower:
        return True
    return False


def _has_partner_text(dc) -> bool:
    cv = dc.card
    if cv is None:
        return False
    return any(p in cv.text_lower for p in _PARTNER_PHRASES)


def _is_background(dc) -> bool:
    cv = dc.card
    if cv is None:
        return False
    return "background" in cv.subtypes


def _chooses_background(dc) -> bool:
    cv = dc.card
    if cv is None:
        return False
    return "choose a background" in cv.text_lower


def _check_commanders(deck, section, violations) -> list[str]:
    commanders = deck.commanders
    section.data["commanders"] = [c.name for c in commanders]

    if not commanders:
        section.add(
            "warn",
            "no commander declared — cannot verify commander legality or compute "
            "color identity",
        )
        section.data["color_identity"] = []
        return []

    # Each commander must itself be able to be a commander.
    bad = [c.name for c in commanders if not _is_legal_commander_card(c)]
    if bad:
        violations["commander"] = bad
        for name in bad:
            section.add(
                "problem",
                f"{name} is not a legal commander (needs to be a legendary "
                "creature or say it can be your commander)",
            )

    # Multiple commanders are only legal with supporting text.
    if len(commanders) > 2:
        section.add(
            "problem",
            f"{len(commanders)} commanders declared; at most 2 are allowed "
            "(via Partner / Friends forever / Background)",
        )
    elif len(commanders) == 2:
        a, b = commanders
        partner_pair = _has_partner_text(a) and _has_partner_text(b)
        background_pair = (_chooses_background(a) and _is_background(b)) or (
            _chooses_background(b) and _is_background(a)
        )
        if partner_pair or background_pair:
            how = "Partner/Friends forever" if partner_pair else "Background"
            section.add("ok", f"two commanders allowed ({how})")
        else:
            section.add(
                "problem",
                "two commanders declared but neither pairing rule "
                "(Partner, Friends forever, Background) is supported by their text",
            )
    else:
        if not bad:
            section.add("ok", f"commander {commanders[0].name} is legal")

    identity = sorted({letter for c in commanders for letter in c.color_identity})
    section.data["color_identity"] = identity
    return identity


# ---- color identity ------------------------------------------------------

def _check_color_identity(deck, commander_identity, section, violations) -> None:
    if not deck.commanders:
        return  # already warned; nothing to compare against
    allowed = set(commander_identity)
    offenders = []
    for dc in deck.cards:
        if dc.is_commander or not dc.resolved:
            continue
        extra = set(dc.color_identity) - allowed
        if extra:
            offenders.append((dc.name, sorted(dc.color_identity), sorted(extra)))
    if offenders:
        violations["color_identity"] = [
            {"name": n, "identity": ident, "outside": out} for n, ident, out in offenders
        ]
        ci_str = "{" + "".join(commander_identity) + "}" if commander_identity else "colorless"
        for name, ident, extra in offenders:
            section.add(
                "problem",
                f"{name} has color identity {{{''.join(ident)}}} outside the "
                f"commander's identity {ci_str} (offending: {{{''.join(extra)}}})",
            )
    else:
        section.add("ok", "all cards are within the commander's color identity")


# ---- banned list ---------------------------------------------------------

def _check_banned(deck, section, violations) -> None:
    banned = [c.name for c in deck.cards if c.legal_commander == "banned"]
    if banned:
        violations["banned"] = banned
        for name in banned:
            section.add("problem", f"{name} is banned in Commander")
    else:
        section.add("ok", "no banned cards")


# ---- game changers & bracket floor --------------------------------------

def _load_brackets() -> dict | None:
    path = repo_root() / "data" / "curated" / "brackets.json"
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _min_bracket_for_gc(count: int, brackets_data: dict | None) -> int | None:
    """Lowest bracket whose game_changer_limit admits `count` Game Changers."""
    if not brackets_data:
        return None
    candidates = []
    for b in brackets_data.get("brackets", []):
        limit = b.get("game_changer_limit")
        number = b.get("number")
        if number is None:
            continue
        if limit is None or count <= limit:
            candidates.append(number)
    return min(candidates) if candidates else None


def _check_game_changers(deck, section) -> None:
    gc_cards = [c for c in deck.cards if c.is_game_changer]
    count = sum(c.quantity for c in gc_cards)
    names = sorted({c.name for c in gc_cards})
    section.data["game_changers"] = names
    section.data["game_changer_count"] = count

    if count:
        section.add("info", f"{count} Game Changer(s): {', '.join(names)}")
    else:
        section.add("ok", "no Game Changers")

    brackets_data = _load_brackets()
    if brackets_data is None:
        return  # degrade gracefully — no bracket floor without the data file

    min_bracket = _min_bracket_for_gc(count, brackets_data)
    section.data["min_bracket"] = min_bracket
    if min_bracket is None:
        return

    by_number = {b.get("number"): b for b in brackets_data.get("brackets", [])}
    name = by_number.get(min_bracket, {}).get("name", "")
    label = f"{min_bracket} ({name})" if name else str(min_bracket)
    section.add(
        "info",
        f"Game Changers alone put this deck at bracket {label} or higher. "
        "This is only the Game-Changer floor; tutors, fast mana, and combos are "
        "assessed by a separate bracket analyzer.",
    )
