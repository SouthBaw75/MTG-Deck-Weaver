"""Card-advantage matchers: burst draw, draw engines, impulse draw, wheels,
recursion, and tutors.

Owns exactly: draw.burst, draw.engine, impulse-draw, wheel, recursion,
tutor.broad, tutor.narrow.

Deliberate non-goals (other domains / traps):
- cantrips ("draw a card" once on a spell) are card *selection*, not advantage
- looting ("draw ... then discard") belongs to graveyard-fill
- land-only searches belong to ramp/mana-fixing
- "target opponent draws" is group hug, not our advantage
- "if you would draw ... instead" replacement effects are not draw sources
"""

from __future__ import annotations

import re

from weaver.knowledge.cardview import CardView, TagHit, cheaper_is_better, clamp01

DOMAIN = "card_advantage"

# --------------------------------------------------------------------------
# precompiled patterns
# --------------------------------------------------------------------------

_NUM_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    # X / "that many" are variable; treat as a solid three for quality purposes
    "x": 3, "that many": 3,
}
_NUM = r"(two|three|four|five|six|seven|x|that many)"

# Wheels: symmetric dump-and-refill. Third-person "draws" keeps these out of
# the burst patterns below.
WHEEL_RE = re.compile(
    r"each player (?:discards (?:his or her|their) hand,? (?:and |then )?draws"
    r"|shuffles (?:his or her|their) hand(?: and graveyard)? into (?:his or her|their) library, then draws)"
)

# One-shot multi-draw. Bare "draw" only matches the imperative (no trailing
# "s"), so "each player draws" / "target opponent draws" never hit; "target
# player draws" (Blue Sun's Zenith, Sign in Blood) is usually pointed at
# yourself and is included explicitly.
DRAW_N_RE = re.compile(
    rf"(?:you (?:may )?draw|target player draws|draw)\s+(?:up to )?{_NUM}\s+(?:additional\s+)?cards"
)

# Repeatable draw (N >= 1) for engine effects.
ENGINE_DRAW_RE = re.compile(
    rf"(?:you (?:may )?draw|draw)\s+(?:up to )?(?:an? (?:additional )?card\b|{_NUM}\s+(?:additional\s+)?cards)"
)

# Looting / Brainstorm-style give-back: draw that is immediately paid for.
LOOT_RE = re.compile(
    r"(?:,? then discards? |if you do, discard |then put [^.]* from your hand on top of your library)"
)

ETB_RE = re.compile(r"^when (?:~|this \w+) enters(?: the battlefield)?\b")

# Trigger line split: everything after the first comma is the effect, so a
# draw in the *condition* ("whenever you draw a card, ...") never matches.
TRIG_SPLIT_RE = re.compile(r"\b(whenever|at the beginning of)\b[^,]*,\s*(.*)")
TRIGGER_WORD_RE = re.compile(r"\b(?:whenever|at the beginning of)\b")

# Impulse draw: exile from your own library plus permission to play/cast it.
IMPULSE_EXILE_RE = re.compile(
    rf"exiles? the top (?:card|{_NUM} cards) of your library"
)
IMPULSE_PLAY_RE = re.compile(
    r"you may (?:play|cast) (?:it|them|that card|those cards|one of them|any number of (?:them|those cards))"
)

# Recursion: graveyard -> hand or battlefield.
RECUR_TO_RE = re.compile(
    r"returns? (?:up to \w+ )?(?:target |all |any number of target )?[^.]*?"
    r" from (?:your|a|their) graveyards? to (?:your hand|its owner's hand|the battlefield)"
)
RECUR_PUT_RE = re.compile(
    r"put (?:up to \w+ )?target [^.]*? from (?:a|your) graveyard onto the battlefield"
)
RECUR_ENCHANTED_RE = re.compile(r"return enchanted creature card to the battlefield")

# Tutors: capture the qualifier between the article and "card(s)".
TUTOR_RE = re.compile(
    r"search your library for (?:up to (?:one|two|three|four|x) )?(?:an? )?"
    r"((?:[\w'’/-]+ )*?)cards?\b"
)
_LAND_QUALIFIERS = {"land", "lands", "plains", "island", "swamp", "mountain", "forest", "gate"}

_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
_SAC_SELF_RE = re.compile(r"sacrifice (?:~|this \w+)")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _add(hits: dict[str, TagHit], tag: str, quality: float, why: str) -> None:
    quality = clamp01(quality)
    if quality <= 0:
        return
    prev = hits.get(tag)
    if prev is None or quality > prev.quality:
        hits[tag] = TagHit(tag, quality, why)


def _draw_count(word: str) -> int:
    return _NUM_WORDS.get(word, 2)


# --------------------------------------------------------------------------
# per-tag detectors
# --------------------------------------------------------------------------

def _match_wheel(card: CardView, hits: dict[str, TagHit]) -> None:
    if WHEEL_RE.search(card.text_lower):
        q = clamp01(0.70 + 0.25 * cheaper_is_better(card.mana_value, best=2, worst=7))
        _add(hits, "wheel", q, "mass discard-and-refill")


def _match_draw_burst(card: CardView, hits: dict[str, TagHit]) -> None:
    is_spell = bool(card.types & {"instant", "sorcery"})
    for ln in card.lines_lower:
        if WHEEL_RE.search(ln) or LOOT_RE.search(ln):
            continue
        m = DRAW_N_RE.search(ln)
        if m and (is_spell or ETB_RE.match(ln)):
            n = _draw_count(m.group(1))
            q = 0.30 + 0.08 * min(n, 5) + 0.35 * cheaper_is_better(card.mana_value, best=2, worst=7)
            if card.is_instant_speed:
                q += 0.05
            src = "ETB" if not is_spell else "spell"
            _add(hits, "draw.burst", clamp01(q), f"one-shot draw {n}+ ({src})")
            return
    # Fact or Fiction / Steam Augury style pile split nets multiple cards.
    if is_spell and "into two piles" in card.text_lower and "into your hand" in card.text_lower:
        q = 0.30 + 0.16 + 0.35 * cheaper_is_better(card.mana_value, best=2, worst=7)
        if card.is_instant_speed:
            q += 0.05
        _add(hits, "draw.burst", clamp01(q), "pile split into hand")


def _match_draw_engine(card: CardView, hits: dict[str, TagHit]) -> None:
    if not card.is_permanent:
        return
    bullets = [ln for ln in card.lines_lower if ln.startswith(("•", "* "))]
    for ln in card.lines_lower:
        if WHEEL_RE.search(ln):
            continue
        # triggered: "whenever ... , <effect>" / "at the beginning of ... , <effect>"
        tm = TRIG_SPLIT_RE.search(ln)
        if tm:
            effect = tm.group(2)
            if ENGINE_DRAW_RE.search(effect) and not LOOT_RE.search(effect):
                q = 0.85 if tm.group(1) == "whenever" else 0.80
                _add(hits, "draw.engine", q, f"draws on {tm.group(1)} trigger")
                continue
            # modal trigger (Black Market Connections): draw hides in a bullet
            if "choose" in effect and bullets:
                if any(ENGINE_DRAW_RE.search(b) and not LOOT_RE.search(b) for b in bullets):
                    _add(hits, "draw.engine", 0.75, "modal trigger can draw")
                    continue
        # activated: "<cost>: draw ..."
        cost, sep, effect = ln.partition(":")
        if sep and ENGINE_DRAW_RE.search(effect) and not LOOT_RE.search(effect):
            if _SAC_SELF_RE.search(cost):
                continue  # one-shot cash-in, not an engine
            nonfree = [s for s in _SYMBOL_RE.findall(cost) if s != "t"]
            q = 0.80 if not nonfree else 0.65
            _add(hits, "draw.engine", q, "activated draw")


def _match_impulse(card: CardView, hits: dict[str, TagHit]) -> None:
    for ln in card.lines_lower:
        if IMPULSE_EXILE_RE.search(ln) and IMPULSE_PLAY_RE.search(ln):
            if TRIGGER_WORD_RE.search(ln) and card.is_permanent:
                _add(hits, "impulse-draw", 0.80, "repeatable exile-and-play")
            else:
                q = 0.45 + 0.25 * cheaper_is_better(card.mana_value, best=1, worst=6)
                _add(hits, "impulse-draw", clamp01(q), "one-shot exile-and-play")
            return


def _match_recursion(card: CardView, hits: dict[str, TagHit]) -> None:
    for ln in card.lines_lower:
        m = RECUR_TO_RE.search(ln) or RECUR_PUT_RE.search(ln) or RECUR_ENCHANTED_RE.search(ln)
        if not m:
            continue
        span = m.group(0)
        if "~ from" in span:
            _add(hits, "recursion", 0.5, "recurs itself")
            continue
        to_battlefield = "battlefield" in span
        repeatable = TRIGGER_WORD_RE.search(ln[: m.start()]) or ":" in ln[: m.start()]
        if repeatable and card.is_permanent:
            _add(hits, "recursion", 0.85, "repeatable graveyard recursion")
        else:
            base = 0.55 if to_battlefield else 0.45
            q = base + 0.35 * cheaper_is_better(card.mana_value, best=1, worst=6)
            dest = "battlefield" if to_battlefield else "hand"
            _add(hits, "recursion", clamp01(q), f"graveyard to {dest}")


def _match_tutors(card: CardView, hits: dict[str, TagHit]) -> None:
    m = TUTOR_RE.search(card.text_lower)
    if not m:
        return
    qualifier = m.group(1).strip()
    tokens = set(qualifier.split())
    if tokens & _LAND_QUALIFIERS:
        return  # land search is ramp/fixing (mana domain), not a tutor here
    rest = card.text_lower[m.end():].lstrip()
    if not qualifier and not rest.startswith("named"):
        q = min(0.98, 0.55 + 0.45 * cheaper_is_better(card.mana_value, best=2, worst=7))
        _add(hits, "tutor.broad", q, "searches for any card")
    else:
        what = qualifier or "named card"
        q = clamp01(0.45 + 0.45 * cheaper_is_better(card.mana_value, best=1, worst=7))
        _add(hits, "tutor.narrow", q, f"tutors only: {what}")


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def match(card: CardView) -> list[TagHit]:
    hits: dict[str, TagHit] = {}
    _match_wheel(card, hits)
    _match_draw_burst(card, hits)
    _match_draw_engine(card, hits)
    _match_impulse(card, hits)
    _match_recursion(card, hits)
    _match_tutors(card, hits)
    return list(hits.values())
