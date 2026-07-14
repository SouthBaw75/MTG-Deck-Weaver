"""Engine-parts + utility pattern matcher.

Owns exactly these taxonomy tags:
    token-producer, treasure-producer, sac-outlet, death-payoff,
    counters-matter, landfall-payoff, spellslinger-payoff, untapper,
    copy-effect, blink, cheat-into-play, graveyard-fill, discard-payoff,
    haste-granting, flash-granting
"""

from __future__ import annotations

import re

from weaver.knowledge.cardview import CardView, TagHit

DOMAIN = "engine"

# ---------------------------------------------------------------------------
# Precompiled patterns (all matched against lowercase, reminder-stripped text)
# ---------------------------------------------------------------------------

# A line whose effect repeats: triggered ability or "each ... step" static.
_REPEAT_TRIGGER = re.compile(r"\b(whenever|at the beginning of)\b")

_MANA_IN_COST = re.compile(r"\{(?![tqe]\})[^}]+\}")  # any symbol except {T}/{Q}/{E}

# token-producer ------------------------------------------------------------
_CREATE_CREATURE_TOKEN = re.compile(r"creates? [^.]*?creature tokens?")
_MULTI_TOKEN = re.compile(
    r"creates? (?:up to )?(?:two|three|four|five|six|seven|eight|nine|ten|x)\b"
    r"|creature tokens?[^.]* for each"
    r"|creates? [^.]*?creature tokens? for each"
)

# treasure-producer ----------------------------------------------------------
_CREATE_TREASURE = re.compile(r"creates? [^.]*?(?:treasure|gold) tokens?")
_SCALED_TREASURE = re.compile(
    r"creates? (?:x|two|three|four|five) [^.]*?(?:treasure|gold) tokens?"
    r"|(?:treasure|gold) tokens?, where x"
    r"|for each [^.]*?, create [^.]*?(?:treasure|gold) token"
    r"|creates? [^.]*?(?:treasure|gold) tokens? for each"
)

# sac-outlet -----------------------------------------------------------------
# Cost segment (before ":") that sacrifices creatures/permanents other than ~.
_SAC_COST = re.compile(r"sacrifice (?:a|an|another|two|three|x) (?:[\w'/-]+ )*?(?:creature|permanent)s?\b")

# death-payoff ---------------------------------------------------------------
_DEATH_TRIGGER = re.compile(
    r"whenever (?:~ or )?(?:a|an|another|one or more)(?: other)?"
    r"(?: [\w'-]+)*? creatures?(?: an opponent controls?)?(?: you control)? (?:die|dies)\b"
)

# counters-matter ------------------------------------------------------------
_COUNTER_DOUBLER = re.compile(
    r"(?:twice that many|that many plus one|double the number of) [^.]*?counters?"
)
_PROLIFERATE = re.compile(r"\bproliferate\b")
_PUT_P1P1 = re.compile(
    r"puts? (?:a|an|one|two|three|four|five|x|that many|a number of|any number of) "
    r"[^.]*?\+1/\+1 counters? on "
    r"(?:each|all|target|another|any|up to|it|that|those|the|creatures)"
)
_COUNTER_TRIGGER = re.compile(
    r"whenever (?:one or more )?\+1/\+1 counters? (?:is|are) put on"
    r"|with counters? on (?:it|them), "
)
_MOVE_COUNTERS = re.compile(r"\bmove (?:all|a|an|any number of|x|up to \w+) [^.]*?counters?")

# landfall-payoff ------------------------------------------------------------
_LANDFALL = re.compile(
    r"whenever (?:a|another|one or more) lands? (?:you control )?enters?"
    r"(?: the battlefield)?(?: under your control)?"
    r"|\blandfall\b"
    r"|whenever you play a land"
)

# spellslinger-payoff --------------------------------------------------------
_CAST_IS = re.compile(r"whenever you cast (?:or copy )?an instant or sorcery spell")
_CAST_OR_COPY = re.compile(r"whenever you cast or copy an instant or sorcery spell|\bmagecraft\b")
_CAST_NONCREATURE = re.compile(r"whenever you cast a noncreature spell")

# untapper -------------------------------------------------------------------
_UNTAP_OTHERS = re.compile(r"untap (?:all|each|target|another target|up to|that creature|those|x target)")
_UNTAP_ALL_PERMANENTS = re.compile(r"untap all permanents")

# copy-effect ----------------------------------------------------------------
_COPY_SPELL = re.compile(r"copy (?:target|that|the) (?:[\w']+ )*?spell|you may copy")
_COPY_TOKEN = re.compile(r"tokens? that(?:'s a| are) cop(?:y|ies) of|enters?(?: the battlefield)? as a copy of")

# blink ----------------------------------------------------------------------
_BLINK_EXILE = re.compile(r"exile (?:target|another target|up to|any number of|all|each|one or more)")
_BLINK_RETURN = re.compile(r"return (?:it|them|that card|those cards|the exiled cards?) to the battlefield")
_EXILE_UNTIL = re.compile(r"until ~ leaves|until (?:it|this) leaves")

# cheat-into-play ------------------------------------------------------------
_PUT_ONTO_BF = re.compile(r"\bputs?\b")
_NONLAND_TYPE = re.compile(r"\b(?:creature|artifact|enchantment|planeswalker)\b")
_RETURN_FROM_GY = re.compile(
    r"returns? [^.]*?(?:creature|artifact|enchantment|planeswalker)[^.]*? cards?"
    r"[^.]*?from (?:your|a|each|all) [^.]*?graveyards?[^.]*? to the battlefield"
)

# graveyard-fill -------------------------------------------------------------
_MILL = re.compile(r"\bmills?\b")
_OPPONENT_MILL = re.compile(r"(?:player|opponent)s? mills?")
_LOOT = re.compile(r"draws? (?:a card|(?:two|three|four|five|x) cards)[^.]*?then discards?")
_RUMMAGE = re.compile(r"discards? (?:a card|(?:two|three|four|x) cards?)[^.]*?then draws?")
_ENTOMB = re.compile(r"search your library for [^.]*?cards?[^.]*?put (?:it|them|that card|those cards) into your graveyard")
_CARDS_TO_GY = re.compile(r"\bputs? [^.]*?cards? [^.]*?into your graveyard")
_SURVEIL = re.compile(r"\bsurveils? \d")

# discard-payoff -------------------------------------------------------------
_DISCARD_TRIGGER = re.compile(
    r"whenever (?:you|an opponent|a player|each opponent) (?:cycle or )?discards?\b"
    r"|if (?:an opponent|a player|you) discarded a card this turn"
)

# haste-granting -------------------------------------------------------------
_HASTE_TEAM = re.compile(r"creatures? you control (?:have|has|gain|gains) haste")
_HASTE_ALL = re.compile(r"all creatures (?:have|gain) haste")
_HASTE_ATTACHED = re.compile(r"(?:equipped|enchanted) creature (?:has|gains|gets [^.]*? and has) haste")
_HASTE_ONESHOT = re.compile(r"(?:it|they|that creature|target creature|those creatures) (?:gains?|have|has) haste")
_RIOT_GRANT = re.compile(r"(?:have|gain|gains) riot")

# flash-granting -------------------------------------------------------------
_AS_THOUGH_FLASH = re.compile(r"as though (?:it|they) had flash")
_HAVE_FLASH = re.compile(r"(?:spells?|cards?)[^.]{0,60}? have flash\b")

_SENT_SPLIT = re.compile(r"[.;\n]")


def _is_activated(line: str, at: int) -> bool:
    """True if `at` falls inside the effect of an activated ability on `line`."""
    colon = line.find(":")
    return 0 <= colon < at


def _repeatable(line: str, at: int) -> bool:
    return bool(_REPEAT_TRIGGER.search(line)) or _is_activated(line, at)


# ---------------------------------------------------------------------------
# match()
# ---------------------------------------------------------------------------

def match(card: CardView) -> list[TagHit]:  # noqa: C901 - one dispatch per tag
    hits: dict[str, TagHit] = {}

    def add(tag: str, quality: float, why: str) -> None:
        prev = hits.get(tag)
        if prev is None or quality > prev.quality:
            hits[tag] = TagHit(tag, quality, why)

    one_shot_spell = bool(card.types & {"instant", "sorcery"})

    for line in card.lines_lower:
        # ---- token-producer ------------------------------------------------
        m = _CREATE_CREATURE_TOKEN.search(line)
        if m:
            if _repeatable(line, m.start()):
                add("token-producer", 0.9, "repeatable creature-token production")
            elif _MULTI_TOKEN.search(line):
                q = 0.6 if one_shot_spell else 0.65
                add("token-producer", q, "one-shot multi-token")
            else:
                add("token-producer", 0.35, "single one-shot token")

        # ---- treasure-producer ----------------------------------------------
        m = _CREATE_TREASURE.search(line)
        if m:
            if _repeatable(line, m.start()):
                add("treasure-producer", 0.9, "repeatable Treasure production")
            elif _SCALED_TREASURE.search(line):
                q = 0.65 if one_shot_spell else 0.85
                add("treasure-producer", q, "scaled Treasure burst")
            else:
                add("treasure-producer", 0.5, "one-shot Treasure")

        # ---- sac-outlet ------------------------------------------------------
        colon = line.find(":")
        if colon > 0:
            cost, effect = line[:colon], line[colon + 1:]
            if _SAC_COST.search(cost):
                if _MANA_IN_COST.search(cost):
                    add("sac-outlet", 0.6, "sac outlet with mana cost")
                elif effect.strip().startswith("add"):
                    add("sac-outlet", 0.95, "free sac outlet producing mana")
                else:
                    add("sac-outlet", 0.9, "free sac outlet")

        # ---- death-payoff ----------------------------------------------------
        m = _DEATH_TRIGGER.search(line)
        if m:
            q = 0.95 if "you control" not in m.group(0) else 0.9
            add("death-payoff", q, "creature-death trigger")

        # ---- counters-matter -------------------------------------------------
        if _COUNTER_DOUBLER.search(line):
            add("counters-matter", 1.0, "counter doubler/amplifier")
        if _PROLIFERATE.search(line):
            add("counters-matter", 0.85, "proliferate")
        if _PUT_P1P1.search(line):
            q = 0.9 if _repeatable(line, 0) else 0.7
            add("counters-matter", q, "puts +1/+1 counters on creatures")
        if _COUNTER_TRIGGER.search(line):
            add("counters-matter", 0.9, "triggers off +1/+1 counters")
        if _MOVE_COUNTERS.search(line):
            add("counters-matter", 0.85, "moves counters")

        # ---- landfall-payoff -------------------------------------------------
        if _LANDFALL.search(line):
            add("landfall-payoff", 0.9, "land-enters trigger")

        # ---- spellslinger-payoff ---------------------------------------------
        if _CAST_OR_COPY.search(line):
            add("spellslinger-payoff", 0.95, "magecraft cast-or-copy trigger")
        elif _CAST_IS.search(line):
            add("spellslinger-payoff", 0.9, "instant/sorcery cast trigger")
        elif _CAST_NONCREATURE.search(line):
            add("spellslinger-payoff", 0.8, "noncreature cast trigger")

        # ---- untapper ---------------------------------------------------------
        m = _UNTAP_OTHERS.search(line)
        if m:
            if _UNTAP_ALL_PERMANENTS.search(line):
                add("untapper", 1.0, "untaps all your permanents")
            elif "untap all" in m.group(0) or "untap each" in m.group(0):
                add("untapper", 0.9, "mass untap")
            else:
                add("untapper", 0.8, "targeted untap")

        # ---- copy-effect -----------------------------------------------------
        m = _COPY_SPELL.search(line)
        if m:
            q = 0.95 if _repeatable(line, m.start()) else 0.85
            add("copy-effect", q, "copies spells")
        m = _COPY_TOKEN.search(line)
        if m:
            q = 0.95 if _repeatable(line, m.start()) else 0.8
            add("copy-effect", q, "copies permanents")

        # ---- blink ------------------------------------------------------------
        em = _BLINK_EXILE.search(line)
        if em and _BLINK_RETURN.search(line) and not _EXILE_UNTIL.search(line):
            if _repeatable(line, em.start()) and "when ~ enters" not in line and not line.startswith("when ~ enters"):
                add("blink", 0.95, "repeatable flicker")
            elif one_shot_spell and card.mana_value <= 2:
                add("blink", 0.95, "cheap flicker spell")
            else:
                add("blink", 0.85, "one-shot flicker")

        # ---- cheat-into-play ---------------------------------------------------
        for sent in _SENT_SPLIT.split(line):
            if (
                "onto the battlefield" in sent
                and _PUT_ONTO_BF.search(sent)
                and "card" in sent
                and _NONLAND_TYPE.search(sent)
                and "token" not in sent
            ):
                q = 0.95 if _repeatable(line, line.find("onto the battlefield")) else 0.85
                add("cheat-into-play", q, "puts cards onto battlefield uncast")
        if _RETURN_FROM_GY.search(line):
            add("cheat-into-play", 0.85, "reanimates onto battlefield")

        # ---- graveyard-fill -----------------------------------------------------
        if _MILL.search(line) and not _OPPONENT_MILL.search(line):
            add("graveyard-fill", 0.85, "self-mill")
        m = _LOOT.search(line)
        if m:
            q = 0.9 if card.mana_value <= 1 else 0.8
            add("graveyard-fill", q, "draw-then-discard looting")
        if _RUMMAGE.search(line):
            add("graveyard-fill", 0.75, "rummage")
        if _ENTOMB.search(line):
            add("graveyard-fill", 0.95, "tutors cards into graveyard")
        elif _CARDS_TO_GY.search(line):
            q = 0.95 if _is_activated(line, len(line) - 1) else 0.85
            add("graveyard-fill", q, "puts cards into your graveyard")
        if _SURVEIL.search(line):
            add("graveyard-fill", 0.7, "surveil")

        # ---- discard-payoff ----------------------------------------------------
        m = _DISCARD_TRIGGER.search(line)
        if m:
            n_triggers = len(_DISCARD_TRIGGER.findall(card.text_lower))
            if n_triggers >= 2:
                add("discard-payoff", 0.95, "multiple discard triggers")
            elif "opponent" in m.group(0) or "player" in m.group(0):
                add("discard-payoff", 0.9, "opponent-discard payoff")
            else:
                add("discard-payoff", 0.85, "self-discard payoff")

        # ---- haste-granting --------------------------------------------------
        if _HASTE_TEAM.search(line):
            add("haste-granting", 0.9, "team haste")
        elif _HASTE_ALL.search(line):
            add("haste-granting", 0.75, "symmetric haste")
        elif _HASTE_ATTACHED.search(line):
            add("haste-granting", 0.75, "grants haste to attached creature")
        elif _RIOT_GRANT.search(line):
            add("haste-granting", 0.8, "grants riot")
        elif _HASTE_ONESHOT.search(line):
            add("haste-granting", 0.5, "incidental haste grant")

        # ---- flash-granting ----------------------------------------------------
        if _AS_THOUGH_FLASH.search(line):
            q = 0.8 if "this turn" in line else 0.95
            add("flash-granting", q, "cast as though spells had flash")
        elif _HAVE_FLASH.search(line):
            add("flash-granting", 0.9, "gives your cards flash")

    # keyword-level signals (not tied to a text line) --------------------------
    if "storm" in card.keywords_lower:
        add("spellslinger-payoff", 0.8, "storm scales with spells cast")
    if "prowess" in card.keywords_lower:
        add("spellslinger-payoff", 0.5, "prowess")
    if "dredge" in card.keywords_lower or re.search(r"\bdredge \d", card.text_lower):
        add("graveyard-fill", 0.8, "dredge")

    return list(hits.values())
