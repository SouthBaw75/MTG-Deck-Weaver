"""Mana-domain matcher.

Owns: ramp.land, ramp.rock, ramp.dork, ramp.ritual, cost-reduction,
mana-fixing, land.utility.

Encoding decisions (kept consistent with the golden set):
- Fetching a land ONTO THE BATTLEFIELD from a nonland card = ramp.land
  (plus mana-fixing when the search is color-flexible: basics, multiple
  land types, or "a land card").
- Fetching a land TO HAND (Land Tax, Weathered Wayfarer) = mana-fixing
  only, never ramp.land.
- A LAND that fetches lands to the battlefield (Evolving Wilds) is
  mana-fixing, not ramp.land — it is land-count-neutral.
- Treasure/Gold token creation is engine-domain (`treasure-producer`)
  and is never emitted here; ramp.rock requires an actual mana ability.
- One-shot ETB mana on a creature (Priest of Gix) is neither ramp.dork
  (no repeatable tap ability) nor ramp.ritual (not an instant/sorcery).
"""

from __future__ import annotations

import re

from weaver.knowledge.cardview import CardView, TagHit, cheaper_is_better, clamp01

DOMAIN = "mana"

# ---------------------------------------------------------------------------
# Precompiled patterns (all applied to lowercase, reminder-stripped text)
# ---------------------------------------------------------------------------

_LAND_WORD = r"(?:lands?|plains|island|swamp|mountain|forest|gate|locus)"

# "Search your library for ... land ... put ... onto the battlefield"
SEARCH_LAND_TO_BF = re.compile(
    rf"search your library for [^.]*\b{_LAND_WORD}\b[^.]*\bput\b[^.]*onto the battlefield"
)
# "Search your library for ... land ... put ... into your hand"
SEARCH_LAND_TO_HAND = re.compile(
    rf"search your library for [^.]*\b{_LAND_WORD}\b[^.]*\bput\b[^.]*into your hand"
)
# "put a land card from your hand onto the battlefield" (Exploration-adjacent)
PUT_LAND_FROM_HAND = re.compile(
    r"put (?:a|one|two|three|up to \w+|any number of) land cards? from your hand onto the battlefield"
)
# "play an additional land" / "play two additional lands"
EXTRA_LAND_DROP = re.compile(r"play (?:an|one|two|three|\w+) additional lands?")

# Activated mana ability with {T} in the cost: "{T}: Add ...", "{1}, {T}: Add ..."
TAP_FOR_MANA = re.compile(r"\{t\}[^:\n]*:[^\n]*\badds? ")
# Enchant-land style acceleration: "...enchanted land is tapped for mana, its controller adds..."
TAPPED_FOR_MANA_BONUS = re.compile(r"tapped for mana[^.\n]*\badds?\b")

# "Add {B}{B}{B}" — explicit mana symbols after "add"
ADD_SYMBOLS = re.compile(r"\badds? ((?:\{[wubrgcs\d]\})+)")
# Burst that scales: "Add {R} for each ..." / "equal to ..."
ADD_SCALING = re.compile(r"\badds? [^.\n]*(?:for each|equal to)")
# Any-color production (fixing)
ANY_COLOR = re.compile(r"mana of any (?:one )?color|in any combination of colors")

# Cost reduction for your own spells: "... you cast ... cost {N} less to cast"
COST_LESS = re.compile(r"\bcosts? (?:\{[\dwubrgcx]+\})+ less to cast")
COST_LESS_AMOUNT = re.compile(r"\bcosts? \{(\d+)\} less")

# Lines on lands that are pure mana abilities: "{T}: Add ...", "{2}, {T}: Add ..."
PURE_MANA_ABILITY = re.compile(r"^(?:\{[^}]+\}, )*\{t\}(?:, [^:\n]*)?: add ")
# Land boilerplate / drawbacks that do NOT make a land a utility land
_LAND_BOILERPLATE = (
    re.compile(r"^~ enters(?: the battlefield)? tapped"),
    re.compile(r"^as ~ enters"),
    re.compile(r"^when(?:ever)? ~ enters(?: the battlefield)?, sacrifice"),
    re.compile(r"deals? \d+ damage to you"),
    re.compile(r"you lose \d+ life"),
    re.compile(r"doesn't untap"),
)
LIFEGAIN_ETB = re.compile(r"^when(?:ever)? ~ enters(?: the battlefield)?, you gain \d+ life")
BECOMES_CREATURE = re.compile(r"becomes? an? [^.\n]*creature")
UNBLOCKABLE = re.compile(r"can't be blocked")

_BASIC_TYPES = ("plains", "island", "swamp", "mountain", "forest")


# ---------------------------------------------------------------------------
# Quality helpers
# ---------------------------------------------------------------------------

def _rock_quality(mv: float) -> float:
    """Sol Ring ≈ 1.0, 2-mana rocks ≈ 0.85, 3-mana ≈ 0.6, 4+ ≈ 0.4."""
    if mv <= 1:
        return 1.0
    if mv <= 2:
        return 0.85
    if mv <= 3:
        return 0.6
    return 0.4


def _dork_quality(mv: float) -> float:
    if mv <= 1:
        return 0.95
    if mv <= 2:
        return 0.8
    if mv <= 3:
        return 0.55
    return 0.35


def _search_is_flexible(segment: str) -> bool:
    """Does a fetched-land search also fix colors?"""
    if "basic land" in segment:
        return True
    if re.search(r"\bland cards?\b", segment):
        return True
    return sum(1 for t in _BASIC_TYPES if t in segment) >= 2


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------

def match(card: CardView) -> list[TagHit]:
    best: dict[str, TagHit] = {}

    def emit(tag: str, quality: float, why: str) -> None:
        quality = clamp01(quality)
        if quality <= 0:
            return
        prev = best.get(tag)
        if prev is None or quality > prev.quality:
            best[tag] = TagHit(tag, quality, why)

    text = card.text_lower
    mv = card.mana_value
    is_land = card.is_land
    is_creature = card.is_creature
    is_spell = bool(card.types & {"instant", "sorcery"})

    # ---- land ramp / land fetch -----------------------------------------
    m_bf = SEARCH_LAND_TO_BF.search(text)
    if m_bf and not is_land:
        emit("ramp.land", cheaper_is_better(mv, best=2.0, worst=7.0),
             "fetches land(s) onto the battlefield")
        if _search_is_flexible(m_bf.group(0)):
            emit("mana-fixing", 0.6, "fetched land can be any needed color")
    elif m_bf and is_land:
        # Fetchland: land-count neutral, but fixes colors.
        emit("mana-fixing", 0.7, "fetchland: trades itself for the land type you need")

    if not m_bf and SEARCH_LAND_TO_HAND.search(text):
        # Land tutor to hand: fixing / weak ramp, never ramp.land.
        emit("mana-fixing", 0.5, "tutors a land to hand (fixing, not acceleration)")

    if not is_land:
        if PUT_LAND_FROM_HAND.search(text):
            emit("ramp.land", 0.85 * cheaper_is_better(mv, best=2.0, worst=6.0),
                 "puts a land from hand onto the battlefield")
        if EXTRA_LAND_DROP.search(text):
            emit("ramp.land", 0.9 * cheaper_is_better(mv, best=1.0, worst=6.0),
                 "grants additional land drops")

    # ---- mana permanents: rocks and dorks --------------------------------
    has_tap_mana = bool(TAP_FOR_MANA.search(text))
    if is_creature and not is_land and has_tap_mana:
        emit("ramp.dork", _dork_quality(mv), "creature that taps for mana")
    if not is_creature and not is_land and (card.types & {"artifact", "enchantment"}):
        if has_tap_mana:
            emit("ramp.rock", _rock_quality(mv), "noncreature permanent with a tap-for-mana ability")
        elif TAPPED_FOR_MANA_BONUS.search(text):
            emit("ramp.rock", _rock_quality(mv), "makes a land produce extra mana when tapped")

    # ---- rituals ----------------------------------------------------------
    if is_spell:
        sym = ADD_SYMBOLS.findall(text)
        scaling = ADD_SCALING.search(text)
        if scaling:
            emit("ramp.ritual", 0.85, "burst mana that scales with board/game state")
        elif sym:
            produced = max(s.count("{") for s in sym)
            net = produced - mv
            emit("ramp.ritual", clamp01(min(0.95, max(0.3, 0.5 + 0.2 * net))),
                 f"one-shot burst of {produced} mana")
        elif ANY_COLOR.search(text):
            emit("ramp.ritual", 0.5, "one-shot mana of flexible colors")

    # ---- cost reduction ---------------------------------------------------
    for ln in card.lines_lower:
        if "opponent" in ln:
            continue  # taxing is interaction-domain, not ours
        if COST_LESS.search(ln) and "you cast" in ln:
            m_amt = COST_LESS_AMOUNT.search(ln)
            amount = int(m_amt.group(1)) if m_amt else 1
            emit("cost-reduction", 0.85 if amount >= 2 else 0.7,
                 f"your spells cost {{{amount}}} less to cast")

    # ---- mana fixing (production-side) ------------------------------------
    if ANY_COLOR.search(text) and (has_tap_mana or is_land or ADD_SYMBOLS.search(text)
                                   or "add one mana" in text or "add two mana" in text
                                   or "add three mana" in text):
        emit("mana-fixing", 0.9, "produces mana of any color")
    colored = {c for c in card.produced_mana if c in {"W", "U", "B", "R", "G"}}
    if len(colored) >= 2:
        emit("mana-fixing", clamp01(0.5 + 0.15 * (len(colored) - 2)),
             f"produces {len(colored)} colors of mana")

    # ---- utility lands ----------------------------------------------------
    if is_land:
        weak_only = None
        for ln in card.lines_lower:
            if any(p.search(ln) for p in _LAND_BOILERPLATE):
                continue
            if LIFEGAIN_ETB.search(ln):
                weak_only = weak_only or ("land.utility", 0.2, "minor lifegain rider on a land")
                continue
            if SEARCH_LAND_TO_BF.search(ln) or SEARCH_LAND_TO_HAND.search(ln):
                continue  # fetch ability, handled as fixing above
            if PURE_MANA_ABILITY.match(ln):
                if ADD_SCALING.search(ln):
                    emit("land.utility", 0.8, "scaling mana engine on a land")
                continue
            if not ln.strip():
                continue
            # A non-mana, non-boilerplate ability line: this is a utility land.
            if BECOMES_CREATURE.search(ln):
                emit("land.utility", 0.8, "creature-land: attacks and blocks")
            elif UNBLOCKABLE.search(ln):
                emit("land.utility", 0.7, "grants unblockability from a land slot")
            elif ADD_SCALING.search(ln):
                emit("land.utility", 0.8, "scaling mana engine on a land")
            elif "search your library" in ln:
                emit("land.utility", 0.7, "tutor ability on a land")
            else:
                emit("land.utility", 0.5, "non-mana ability on a land")
        if weak_only and "land.utility" not in best:
            emit(*weak_only)

    return sorted(best.values(), key=lambda h: (-h.quality, h.tag))
