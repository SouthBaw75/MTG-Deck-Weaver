"""Interaction-domain matcher.

Owns exactly: removal.spot.creature, removal.spot.any,
removal.spot.artifact-enchantment, wipe.creature, wipe.any,
wipe.artifact-enchantment, counterspell, graveyard-hate, stax, theft, taxing.

Design notes / judgment calls:
- Bounce ("return target ... to its owner's hand") is emitted as low-quality
  spot removal; fights and bites are mid-quality removal.spot.creature.
- One-shot edicts ("target/each player sacrifices a creature", not on a
  repeating trigger) are removal.spot.creature; repeating upkeep edicts
  (Smokestack) are stax; death-triggered edicts (Grave Pact) are neither ours.
- Overloadable spot removal additionally emits the corresponding wipe tag
  (Vandalblast -> wipe.artifact-enchantment, Cyclonic Rift -> wipe.any).
- Pillow-fort ("can't attack you", attack taxes like Ghostly Prison) is
  defense-domain: any stax/taxing pattern is suppressed on lines that
  mention attacking or blocking.
- "unless ... pays" punishment on non-combat actions (Rhystic Study,
  Esper Sentinel) IS emitted as taxing, consistently.
- Symmetric cost increases (Sphere of Resistance, Thalia) are taxing only;
  stax is reserved for explicit denial/lock text.
"""

from __future__ import annotations

import re

from weaver.knowledge.cardview import CardView, TagHit, cheaper_is_better, clamp01

DOMAIN = "interaction"

# --------------------------------------------------------------------------
# spot removal
# --------------------------------------------------------------------------
_SPOT_DESTROY = re.compile(r"\b(destroys?|exiles?)\s+(?:up to \w+ )?target ([^.;\n]*)")
_SHUFFLE_AWAY = re.compile(r"owner of target ([^.;\n]*?) shuffles it into")
_TUCK = re.compile(r"put target ([^.;\n]*?) (?:on the bottom of|on top of|into) (?:its|their) owner's librar")
_BOUNCE = re.compile(r"return (?:up to \w+ )?target ([^.;\n]*?) to (?:its|their) owner")
_DMG_ANY_TARGET = re.compile(r"deals? (\d+|x) damage to any target")
_DMG_TARGET = re.compile(r"deals? (\d+|x) damage(?: divided[^.;\n]*?)? to (?:up to \w+ )?target ([^.;\n]*)")
_BITE = re.compile(r"deals damage equal to (?:its|their) power to (?:up to \w+ )?target creature")
_MINUS_NN = re.compile(r"target creature(?:[^.;\n]*?) gets -(\d+|x)/-(\d+|x)")
_FIGHT = re.compile(r"fights? (?:up to \w+ )?(?:another )?target creature")
_EDICT = re.compile(r"\b(?:target|each) (?:player|opponent) sacrifices (?:a|an|one|two|three) (?:[a-z]+ )*?creature")
_BLINK_GUARD = re.compile(r"return (?:it|that card|them|those cards) to the battlefield")
_FREE_ALT = re.compile(r"you may cast this spell without paying its mana cost")

# --------------------------------------------------------------------------
# wipes
# --------------------------------------------------------------------------
_WIPE = re.compile(r"\b(destroys?|exiles?) (?:all|each) ([^.;\n]*)")
_DMG_EACH_CREATURE = re.compile(r"deals? (\d+|x) damage to each creature")
_MINUS_ALL = re.compile(r"(?:all|each) creatures? get -(\d+|x)/-")
_BOUNCE_ALL = re.compile(r"return (?:all|each) ([^.;\n]*?) to (?:its|their) owners?'")
_NON_WORD = re.compile(r"\bnon\w+\s*")

# --------------------------------------------------------------------------
# counterspells
# --------------------------------------------------------------------------
_COUNTER_SPELL = re.compile(r"counter target ([a-z',\- ]*?)spell")
_COUNTER_ABILITY = re.compile(r"counter target [a-z ]*?abilit")
_COUNTER_COND = re.compile(r"counter (?:it|that spell) unless")

# --------------------------------------------------------------------------
# graveyard hate
# --------------------------------------------------------------------------
_GY_MASS = re.compile(
    r"exiles? all cards from [^.;\n]*graveyard"
    r"|exiles? all graveyards"
    r"|exiles? (?:target|each|every|that) (?:opponent's|player's) graveyards?"
    r"|(?:player|opponent) exiles (?:their|his or her) graveyard"
)
_GY_REPLACE = re.compile(r"would be put into [^.;\n]*graveyard[^.;\n]*(?:exile (?:it|that card)|instead exile)")
_GY_SPOT = re.compile(r"exiles? (?:up to \w+ )?target cards? from (?:a|any|each|target|an opponent's) graveyard")
_GY_STATIC = re.compile(
    r"cards? in graveyards[^.;\n]*can't"
    r"|can't cast spells from graveyards"
    r"|can't (?:enter the battlefield|leave graveyards)[^.;\n]*graveyard"
)

# --------------------------------------------------------------------------
# stax (each: pattern, quality, why)
# --------------------------------------------------------------------------
_STAX_PATTERNS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(r"(?:your opponents|opponents|players|each player|each opponent) can't"), 0.8, "denies opponents an action"),
    (re.compile(r"can't be activated"), 0.75, "locks activated abilities"),
    (re.compile(r"don't untap during (?:its|their) (?:controller's|controllers'|owner's|owners')"), 0.85, "untap denial"),
    (re.compile(r"players? skips? (?:its|their|his or her) untap"), 0.85, "untap denial"),
    (re.compile(r"at the beginning of each (?:player's|opponent's) upkeep, (?:that player|each player|each opponent) sacrifices"), 0.8, "recurring forced sacrifice"),
    (re.compile(r"if (?:a player|an opponent) would search"), 0.75, "search denial"),
    (re.compile(r"can't cause (?:them|their controllers?) to search"), 0.75, "search denial"),
    (re.compile(r"(?:your )?opponents control enters? (?:the battlefield )?tapped"), 0.6, "opponents' permanents enter tapped"),
    (re.compile(r"(?:don't|doesn't) cause abilities to trigger"), 0.7, "trigger denial"),
    (re.compile(r"you control your opponents? while"), 0.8, "hijacks opponents' actions"),
]
_COMBAT_GUARD = re.compile(r"\battack|\bblock")

# --------------------------------------------------------------------------
# taxing
# --------------------------------------------------------------------------
_TAX_COST_MORE = re.compile(r"costs? (?:\{[^}]+\})+ more to (?:cast|activate)")
_TAX_UNLESS_PAYS = re.compile(r"unless (?:that player|its controller|their controller|they|he or she) pays?")

# --------------------------------------------------------------------------
# theft
# --------------------------------------------------------------------------
_THEFT_GAIN = re.compile(r"gain control of")
_THEFT_GIVE_AWAY = re.compile(r"(?:player|opponent) gains control")
_THEFT_ENCHANT = re.compile(r"you control enchanted (?:creature|permanent|artifact)")
_THEFT_EXCHANGE = re.compile(r"exchange control of")
_THEFT_CAST_FROM = re.compile(
    r"(?:target opponent's|each opponent's|that player's|an opponent's) librar"
    r"|opponent is searching (?:their|his or her) librar"
)
_THEFT_MAY_PLAY = re.compile(r"you may (?:cast|play) (?:it|them|that card|those cards)")


def _scope(noun: str) -> set[str]:
    """Classify a target/all noun phrase into scope buckets."""
    noun = _NON_WORD.sub(" ", noun)  # "nonland permanent" -> "permanent"
    out: set[str] = set()
    if "you control" in noun:
        return out  # sac-fodder / self-target trap
    if "graveyard" in noun:
        out.add("graveyard")
        return out
    if "card" in noun:
        return out  # cards, not battlefield permanents
    if "permanent" in noun:
        out.add("any")
        return out
    cats = 0
    if "creature" in noun:
        out.add("creature")
        cats += 1
    if "artifact" in noun or "enchantment" in noun:
        out.add("artifact-enchantment")
        cats += 1
    if "planeswalker" in noun:
        cats += 1
    if "land" in noun:
        cats += 1
    if cats >= 3:
        out.add("any")
    return out


def _dmg_base(amount: str) -> float:
    if amount == "x":
        return 0.7
    n = int(amount)
    if n >= 5:
        return 0.7
    if n >= 3:
        return 0.6
    return 0.35


def match(card: CardView) -> list[TagHit]:
    hits: list[TagHit] = []
    speed_bump = 0.1 if card.is_instant_speed else 0.0
    cost = cheaper_is_better(card.mana_value)
    is_free = any(_FREE_ALT.search(ln) for ln in card.lines_lower)
    has_overload = "overload" in card.keywords_lower or "overload {" in card.text_lower

    def add(tag: str, q: float, why: str) -> None:
        hits.append(TagHit(tag, round(max(0.05, clamp01(q)), 3), why))

    spot_scopes: set[str] = set()  # for overload -> wipe promotion
    wipe_scopes: set[str] = set()  # for modal wipe.any aggregation

    def add_spot(scopes: set[str], q: float, why: str) -> None:
        spot_scopes.update(scopes)
        for s in scopes:
            if s == "graveyard":
                continue
            add(f"removal.spot.{s}", q, why)

    for line in card.lines_lower:
        # ---- spot removal ------------------------------------------------
        for m in _SPOT_DESTROY.finditer(line):
            if _BLINK_GUARD.search(line):
                continue  # blink, not removal
            verb, noun = m.group(1), m.group(2)
            scopes = _scope(noun)
            base = 0.85 if verb.startswith("exile") else 0.75
            q = base * cost + speed_bump
            if is_free:
                q = max(q, 0.9)
            add_spot(scopes, q, f"{verb} target {noun.strip()[:40]}")
        m = _SHUFFLE_AWAY.search(line)
        if m:
            add_spot(_scope(m.group(1)), 0.7 * cost + speed_bump, "shuffles target away")
        m = _TUCK.search(line)
        if m:
            add_spot(_scope(m.group(1)), 0.65 * cost + speed_bump, "tucks target into library")
        m = _BOUNCE.search(line)
        if m and "graveyard" not in line:
            add_spot(_scope(m.group(1)), 0.3 * cost + speed_bump, "bounce (tempo-only removal)")
        m = _DMG_ANY_TARGET.search(line)
        if m:
            q = _dmg_base(m.group(1)) * cost + speed_bump
            add_spot({"any", "creature"}, q, f"{m.group(1)} damage to any target")
        else:
            m = _DMG_TARGET.search(line)
            if m and "creature" in m.group(2):
                q = _dmg_base(m.group(1)) * cost + speed_bump
                add_spot({"creature"}, q, f"{m.group(1)} damage to target creature")
        if _BITE.search(line):
            add_spot({"creature"}, 0.55 * cost + speed_bump, "bite: your creature damages theirs")
        m = _MINUS_NN.search(line)
        if m:
            tou = m.group(2)
            base = 0.7 if tou == "x" else (0.65 if int(tou) >= 4 else 0.5 if int(tou) >= 2 else 0.3)
            add_spot({"creature"}, base * cost + speed_bump, f"-N/-{tou} shrink-kill")
        if _FIGHT.search(line):
            add_spot({"creature"}, 0.5 * cost + speed_bump, "fight (needs your creature)")
        if not line.startswith(("whenever", "at the beginning")) and _EDICT.search(line):
            add_spot({"creature"}, 0.55 * cost + speed_bump, "one-shot edict sacrifice")

        # ---- wipes ---------------------------------------------------------
        for m in _WIPE.finditer(line):
            verb, noun = m.group(1), m.group(2)
            scopes = _scope(noun)
            if "you control" in noun and "opponent" not in noun:
                continue
            base = 0.9 if verb.startswith("exile") else 0.8
            if "opponent" in noun or "don't control" in noun:
                base += 0.1
            cost_factor = 1.0 if card.mana_value <= 5 else (0.9 if card.mana_value <= 7 else 0.8)
            for s in scopes:
                if s == "graveyard":
                    add("graveyard-hate", 0.85, f"{verb} all graveyards")
                else:
                    wipe_scopes.add(s)
                    add(f"wipe.{s}", clamp01(base * cost_factor) + speed_bump, f"{verb} all {noun.strip()[:40]}")
        m = _DMG_EACH_CREATURE.search(line)
        if m:
            amt = m.group(1)
            base = 0.85 if (amt == "x" or int(amt) >= 5) else (0.6 if int(amt) >= 3 else 0.4)
            wipe_scopes.add("creature")
            add("wipe.creature", base + speed_bump, f"{amt} damage to each creature")
        m = _MINUS_ALL.search(line)
        if m:
            base = 0.85 if m.group(1) == "x" else (0.7 if int(m.group(1)) >= 3 else 0.45)
            wipe_scopes.add("creature")
            add("wipe.creature", base + speed_bump, f"all creatures get -{m.group(1)}/-{m.group(1)}")
        m = _BOUNCE_ALL.search(line)
        if m:
            scopes = _scope(m.group(1))
            bonus = 0.15 if "don't control" in m.group(1) else 0.0
            for s in scopes - {"graveyard"}:
                wipe_scopes.add(s)
                add(f"wipe.{s}", 0.5 + bonus + speed_bump, "mass bounce")

        # ---- counterspells -------------------------------------------------
        m = _COUNTER_SPELL.search(line)
        if m:
            mods = m.group(1).strip()
            base = 0.9 if not mods else (0.8 if ("," in mods or " or " in mods) else 0.72)
            q = 1.0 if is_free else base * cheaper_is_better(card.mana_value, best=2.0, worst=6.0) + 0.05
            add("counterspell", q, f"counters {mods or 'any'} spells")
        elif _COUNTER_ABILITY.search(line):
            add("counterspell", 0.6, "counters abilities")
        elif _COUNTER_COND.search(line):
            add("counterspell", 0.6, "conditional counter")

        # ---- graveyard hate --------------------------------------------------
        if _GY_MASS.search(line):
            add("graveyard-hate", 0.85, "mass graveyard exile")
        if _GY_REPLACE.search(line):
            add("graveyard-hate", 0.9, "graveyard replacement: exile instead")
        if _GY_SPOT.search(line):
            add("graveyard-hate", 0.45, "exiles a single graveyard card")
        if _GY_STATIC.search(line):
            add("graveyard-hate", 0.75, "static graveyard lockout")

        # ---- stax (never on combat-deterrence lines: pillow-fort) -----------
        if not _COMBAT_GUARD.search(line):
            for pat, q, why in _STAX_PATTERNS:
                if pat.search(line):
                    add("stax", q, why)

        # ---- taxing (combat taxes are pillow-fort; counters are counterspell)
        if not _COMBAT_GUARD.search(line):
            if _TAX_COST_MORE.search(line):
                add("taxing", 0.75 if "opponent" in line else 0.65, "spells/abilities cost more")
            if _TAX_UNLESS_PAYS.search(line) and "counter" not in line:
                add("taxing", 0.6, "punishes unless they pay")

        # ---- theft ---------------------------------------------------------
        if not _THEFT_GIVE_AWAY.search(line):  # Donate-style is not theft
            if _THEFT_GAIN.search(line):
                temp = "until end of turn" in line
                add("theft", 0.3 if temp else 0.85, "temporary steal" if temp else "steals a permanent")
            if _THEFT_ENCHANT.search(line):
                add("theft", 0.8, "steals via Aura")
            if _THEFT_EXCHANGE.search(line):
                add("theft", 0.6, "swaps control")
            if _THEFT_CAST_FROM.search(line) and "exile" in line and _THEFT_MAY_PLAY.search(line):
                add("theft", 0.7, "casts opponents' cards")

    # Overloadable spot removal is also a wipe.
    if has_overload:
        for s in spot_scopes - {"graveyard"}:
            best_spot = max((h.quality for h in hits if h.tag == f"removal.spot.{s}"), default=0.4)
            add(f"wipe.{s}", min(0.9, best_spot + 0.35), "overload turns it into a sweeper")
            wipe_scopes.add(s)

    # Modal wipes covering creatures AND artifacts/enchantments are flexible.
    if "any" not in wipe_scopes and {"creature", "artifact-enchantment"} <= wipe_scopes:
        add("wipe.any", 0.85, "modal wipe hits multiple permanent types")

    # Keep the best hit per tag.
    best: dict[str, TagHit] = {}
    for h in hits:
        if h.tag not in best or h.quality > best[h.tag].quality:
            best[h.tag] = h
    return sorted(best.values(), key=lambda h: (-h.quality, h.tag))
