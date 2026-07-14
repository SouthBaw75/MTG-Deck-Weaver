"""Defense & offense pattern matchers.

Owns: protection.self, protection.board, fog, pillow-fort, deterrent,
lifegain, blocker.value, wincon.combat, wincon.alt, evasion-granting,
buff.anthem, extra-combat, extra-turn, burn.

Judgment calls encoded here (kept consistent with the golden set):

- protection.self is for cards that GRANT protection to a single permanent
  or player (equipment, auras, activated grants, "You have hexproof").
  A creature that merely HAS hexproof/shroud itself gets no tag.
- protection.board is the mass version ("creatures/permanents you control
  gain hexproof/indestructible"); "protection from everything" (Teferi's
  Protection) is the gold standard at 1.0.
- fog is strictly "prevent all (combat) damage ... this turn". Exiling or
  destroying attackers is interaction's removal, never fog.
- lifegain: triggered engines ("whenever ..., you gain ... life") always
  count; one-shot gains need 4+ life; lifelink counts only on power >= 3
  bodies or when granted team-wide. Incidental ETB "gain 1-3 life": no tag.
- wincon.combat bar: team-wide overrun/double-strike finishers, combat
  damage "loses the game"/"life total becomes 1" triggers, or a native
  power >= 7 body with evasion. Single-target combat tricks never qualify.
- Non-combat "loses the game"/"you win the game" text is wincon.alt; a
  one-shot 20+ damage activation (Aetherflux Reservoir) also counts.
- evasion-granting: team grants and repeatable single-target grants from
  permanents (Rogue's Passage). A one-shot instant/sorcery "target
  creature gains flying" is NOT tagged (too weak, keeps precision high).
- buff.anthem is static (no "until end of turn") team +N/+N, including
  lords; team pumps until end of turn belong to wincon.combat instead.
- burn requires a player-facing target (any target / each opponent /
  target player ...); "deals N damage to target creature" alone is
  interaction's removal, not burn. Mass "each opponent loses N life"
  counts as burn.
"""

from __future__ import annotations

import re

from weaver.knowledge.cardview import CardView, TagHit

DOMAIN = "defense_offense"

OWNED_TAGS = frozenset({
    "protection.self",
    "protection.board",
    "fog",
    "pillow-fort",
    "deterrent",
    "lifegain",
    "blocker.value",
    "wincon.combat",
    "wincon.alt",
    "evasion-granting",
    "buff.anthem",
    "extra-combat",
    "extra-turn",
    "burn",
})

# ---- protection ------------------------------------------------------------
_PROT_KW = r"(?:hexproof|shroud|indestructible|protection from|\bward\b)"
RE_PROT_SELF_TARGET = re.compile(
    r"target (?:creature|permanent|artifact|enchantment|planeswalker|player)"
    r"[^.]*?gains?[^.]*?" + _PROT_KW
)
RE_PROT_SELF_ATTACHED = re.compile(
    r"(?:equipped|enchanted) (?:creature|permanent)[^.]*?(?:has|have|gains?)[^.]*?" + _PROT_KW
)
RE_PROT_SELF_YOU = re.compile(r"\byou (?:have|gain) (?:hexproof|shroud)\b")
RE_PROT_BOARD = re.compile(
    r"(?:creatures|permanents|nonland permanents) you control[^.]*?"
    r"(?:gain|have|are|get)[^.]*?(?:hexproof|shroud|indestructible|protection from)"
)
RE_PROT_EVERYTHING = re.compile(r"you gain protection from everything")

# ---- fog -------------------------------------------------------------------
RE_FOG = re.compile(
    r"prevent all (?:combat )?damage that would be dealt(?: to you(?: and [^.]*?)?)? this turn"
)

# ---- pillow-fort -----------------------------------------------------------
RE_PF_TAX = re.compile(r"creatures can't attack you[^.]*?unless")
RE_PF_NOATTACK_YOU = re.compile(r"creatures can't attack you\b")
RE_PF_NOATTACK_LINE = re.compile(r"^creatures can't attack\.?$")
RE_PF_LIMIT = re.compile(r"no more than (?:one|two) creatures? can attack")

# ---- deterrent -------------------------------------------------------------
RE_DET_ATTACK = re.compile(
    r"whenever (?:a|an opposing) creature attacks you|whenever an opponent attacks you"
)
RE_DET_DAMAGE = re.compile(
    r"whenever a (?:creature|permanent|source)[^.]*? deals (?:combat )?damage to you, "
    r"(?:destroy|exile|return|sacrifice|that player|its controller|it deals|~ deals)"
)
RE_DET_TARGET = re.compile(r"whenever you(?:'re| become| are) the target")

# ---- lifegain --------------------------------------------------------------
RE_TRIGGERED = re.compile(r"\b(?:whenever|at the beginning of)\b")
RE_YOU_GAIN_LIFE = re.compile(r"you gain [^.]{0,50}?life\b")
RE_GAIN_N = re.compile(r"you (?:may )?gain (\d+) life")
RE_GAIN_EQUAL = re.compile(r"you gain life equal to")
RE_TEAM_LIFELINK = re.compile(r"creatures you control (?:have|gain|get)[^.]*?lifelink")
RE_LIFE_DOUBLER = re.compile(r"if you would gain life[^.]*?instead")

# ---- blocker.value ---------------------------------------------------------
RE_ETB_DRAW = re.compile(r"when ~ enters(?: the battlefield)?, draw a card")

# ---- wincon.combat ---------------------------------------------------------
RE_TEAM_PT_BUFF = re.compile(r"creatures you control (?:get|gain)[^.]*?\+(x|\d+)/\+(?:x|\d+)")
RE_TEAM_DSTRIKE = re.compile(r"creatures you control (?:gain|have|get)[^.]*?double strike")
RE_LIFE_TOTAL_1 = re.compile(r"life total becomes 1\b")
_EVASION_KWS = {"flying", "trample", "menace", "shadow", "fear", "intimidate"}

# ---- wincon.alt ------------------------------------------------------------
RE_WIN = re.compile(r"you win the game")
RE_OPP_LOSES_GAME = re.compile(
    r"(?:each opponent|each other player|each player|that player|target player|target opponent)"
    r" loses the game"
)
RE_CANT_LOSE = re.compile(r"you can't lose the game")

# ---- evasion-granting ------------------------------------------------------
RE_TEAM_EVASION = re.compile(
    r"creatures you control (?:have|gain|get)[^.]*?"
    r"\b(flying|menace|fear|intimidate|shadow|skulk|trample)\b"
)
RE_TEAM_UNBLOCKABLE = re.compile(r"creatures you control[^.]*?can't be blocked")
RE_ST_EVASION = re.compile(
    r"target creature[^.]*?(?:can't be blocked|gains? (?:flying|menace|fear|intimidate|shadow))"
)
RE_ATTACHED_EVASION = re.compile(
    r"(?:equipped|enchanted) creature (?:has|gains?)[^.]*?"
    r"(?:flying|menace|fear|intimidate|shadow|can't be blocked)"
)

# ---- buff.anthem -----------------------------------------------------------
RE_ANTHEM = re.compile(r"creatures you control get \+(\d+)/\+(\d+)")
RE_LORD = re.compile(r"other [a-z]+(?: creatures)? you control get \+\d+/\+\d+")

# ---- extra combat / extra turn ---------------------------------------------
RE_EXTRA_COMBAT = re.compile(r"additional combat phase")
RE_EXTRA_TURN = re.compile(r"takes? an extra turn")
RE_EXTRA_TURN_OPP = re.compile(r"(?:each|target|an) opponent takes an extra turn")

# ---- burn ------------------------------------------------------------------
RE_DEALS_N = re.compile(r"deals (x|\d+) damage")
RE_OPP_LOSE_LIFE = re.compile(r"each opponent loses (x|\d+) life")
RE_DAMAGE_PLUS = re.compile(r"deals that much damage plus \d+")
_PLAYERISH = (
    "any target",
    "each opponent",
    "each player",
    "target player",
    "target opponent",
    "each of your opponents",
    "to that player",
    "player or planeswalker",
)


def _num(s: str | None) -> int | None:
    try:
        return int(s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# ---- per-tag helpers --------------------------------------------------------

def _protection(card: CardView, add) -> None:
    text = card.text_lower
    if RE_PROT_EVERYTHING.search(text):
        add("protection.board", 1.0, "protection from everything")
    for ln in card.lines_lower:
        if RE_PROT_BOARD.search(ln):
            q = 0.9 if card.is_instant_speed else 0.8
            add("protection.board", q, "mass protection grant")
        if RE_PROT_SELF_ATTACHED.search(ln):
            q = 0.9 if ("equip {" in text and card.mana_value <= 2) else 0.75
            add("protection.self", q, "attached protection grant")
        if RE_PROT_SELF_TARGET.search(ln):
            q = 0.85 if ln.startswith("{t}") else 0.7
            add("protection.self", q, "targeted protection grant")
        if RE_PROT_SELF_YOU.search(ln):
            add("protection.self", 0.75, "gives you hexproof/shroud")


def _fog(card: CardView, add) -> None:
    for ln in card.lines_lower:
        if RE_FOG.search(ln):
            if "buyback" in card.text_lower:
                q = 0.9  # Constant Mists: repeatable fog
            elif card.is_creature:
                q = 0.8  # Spore Frog: recurrable body
            else:
                q = 0.7
            add("fog", q, "prevents combat damage this turn")


def _pillow_fort(card: CardView, add) -> None:
    if not card.is_permanent:
        return
    for ln in card.lines_lower:
        if RE_PF_TAX.search(ln):
            add("pillow-fort", 0.9, "attack tax")
        elif RE_PF_NOATTACK_YOU.search(ln):
            add("pillow-fort", 0.85, "creatures can't attack you")
        elif RE_PF_NOATTACK_LINE.match(ln):
            add("pillow-fort", 0.75, "creatures can't attack")
        if RE_PF_LIMIT.search(ln):
            add("pillow-fort", 0.8, "limits attackers per combat")


def _deterrent(card: CardView, add) -> None:
    for ln in card.lines_lower:
        if RE_DET_DAMAGE.search(ln):
            add("deterrent", 0.85, "punishes damage dealt to you")
        if RE_DET_ATTACK.search(ln):
            add("deterrent", 0.75, "punishes attacking you")
        if RE_DET_TARGET.search(ln):
            add("deterrent", 0.7, "punishes targeting you")


def _lifegain(card: CardView, add) -> None:
    for ln in card.lines_lower:
        if RE_TRIGGERED.search(ln) and RE_YOU_GAIN_LIFE.search(ln):
            q = 0.85 if ("that much life" in ln or "for each" in ln) else 0.75
            add("lifegain", q, "repeatable lifegain trigger")
            continue
        m = RE_GAIN_N.search(ln)
        if m and int(m.group(1)) >= 4:
            n = int(m.group(1))
            add("lifegain", min(0.4 + 0.03 * n, 0.7), f"one-shot gain {n} life")
        elif RE_GAIN_EQUAL.search(ln):
            add("lifegain", 0.7, "scaling one-shot lifegain")
    if RE_TEAM_LIFELINK.search(card.text_lower):
        add("lifegain", 0.8, "team lifelink")
    if "lifelink" in card.keywords_lower and card.is_creature:
        p = _num(card.power)
        if p is not None and p >= 3:
            add("lifegain", 0.6, "lifelink on a real body")
    if RE_LIFE_DOUBLER.search(card.text_lower):
        add("lifegain", 0.7, "lifegain doubler")


def _blocker(card: CardView, add) -> None:
    if not card.is_creature:
        return
    t = _num(card.toughness)
    if t is None:
        return
    p = _num(card.power) or 0
    kws = card.keywords_lower
    if "defender" in kws and t >= 3:
        q = 0.5
        if kws & {"flying", "reach"}:
            q += 0.15
        if t >= 6:
            q += 0.1
        if RE_ETB_DRAW.search(card.text_lower):
            q += 0.2
        add("blocker.value", min(q, 0.85), "defensive wall")
    elif t >= 4 and card.mana_value <= 3 and t >= p + 2:
        q = 0.55 + (0.1 if kws & {"flying", "reach"} else 0.0)
        add("blocker.value", q, "cheap high-toughness body")


def _wincon_combat(card: CardView, add) -> None:
    for ln in card.lines_lower:
        if "creatures you control" in ln and "until end of turn" in ln:
            m = RE_TEAM_PT_BUFF.search(ln)
            trample = "trample" in ln
            infect = "infect" in ln
            if m:
                a = m.group(1)
                if infect:
                    add("wincon.combat", 0.95, "overrun with infect")
                elif a == "x" and trample:
                    q = 1.0 if "enters" in ln else 0.9
                    add("wincon.combat", q, "mass overrun")
                elif a == "x":
                    add("wincon.combat", 0.85, "scaling team pump")
                elif int(a) >= 3 and trample:
                    add("wincon.combat", 0.85, "overrun")
                elif int(a) >= 5:
                    add("wincon.combat", 0.7, "huge team pump")
        if RE_TEAM_DSTRIKE.search(ln):
            add("wincon.combat", 0.8, "team double strike")
        if "combat damage" in ln and "loses the game" in ln:
            add("wincon.combat", 0.9, "combat damage kill trigger")
        if RE_LIFE_TOTAL_1.search(ln):
            add("wincon.combat", 0.85, "sets a life total to 1")
    p = _num(card.power)
    if card.is_creature and p is not None and p >= 7 and card.keywords_lower & _EVASION_KWS:
        add("wincon.combat", 0.6, "huge evasive body")


def _wincon_alt(card: CardView, add) -> None:
    for ln in card.lines_lower:
        if RE_WIN.search(ln):
            q = 0.95 if card.mana_value <= 3 else 0.9
            add("wincon.alt", q, "explicit win-the-game")
        if RE_OPP_LOSES_GAME.search(ln) and "combat damage" not in ln:
            add("wincon.alt", 0.85, "makes opponents lose the game")
        if RE_CANT_LOSE.search(ln):
            add("wincon.alt", 0.7, "can't lose the game")


def _evasion(card: CardView, add) -> None:
    for ln in card.lines_lower:
        m = RE_TEAM_EVASION.search(ln)
        if m:
            kw = m.group(1)
            q = 0.6 if kw == "trample" else 0.85
            add("evasion-granting", q, f"grants team {kw}")
        if RE_TEAM_UNBLOCKABLE.search(ln):
            add("evasion-granting", 0.9, "makes your team unblockable")
        if card.is_permanent and RE_ST_EVASION.search(ln):
            add("evasion-granting", 0.6, "repeatable targeted evasion")
        if RE_ATTACHED_EVASION.search(ln):
            add("evasion-granting", 0.55, "attached evasion grant")


def _anthem(card: CardView, add) -> None:
    if not card.is_permanent:
        return
    for ln in card.lines_lower:
        if "until end of turn" in ln:
            continue
        m = RE_ANTHEM.search(ln)
        if m:
            n = int(m.group(1))
            add("buff.anthem", 0.85 if n >= 3 else 0.8, "static team buff")
        elif RE_LORD.search(ln):
            add("buff.anthem", 0.75, "lord effect")


def _extra_phases(card: CardView, add) -> None:
    text = card.text_lower
    if RE_EXTRA_COMBAT.search(text):
        q = 0.9 if "untap all" in text else 0.8
        add("extra-combat", q, "additional combat phase")
    if RE_EXTRA_TURN.search(text) and not RE_EXTRA_TURN_OPP.search(text):
        q = 0.35 if "you lose the game" in text else 0.9
        add("extra-turn", q, "extra turn")


def _burn(card: CardView, add) -> None:
    for ln in card.lines_lower:
        m = RE_DEALS_N.search(ln)
        if m and any(w in ln for w in _PLAYERISH):
            a = m.group(1)
            if a == "x":
                q = 0.8
            else:
                n = int(a)
                q = 0.75 if n >= 4 else (0.7 if n >= 2 else 0.5)
                if n >= 20:
                    add("wincon.alt", 0.8, "one-shot lethal damage")
            if "each opponent" in ln or "each player" in ln:
                q = min(q + 0.05, 0.9)
            add("burn", q, "damage at players")
        m2 = RE_OPP_LOSE_LIFE.search(ln)
        if m2:
            add("burn", 0.75 if m2.group(1) == "x" else 0.7, "mass life loss")
        if RE_DAMAGE_PLUS.search(ln):
            add("burn", 0.7, "damage amplifier")


_HELPERS = (
    _protection,
    _fog,
    _pillow_fort,
    _deterrent,
    _lifegain,
    _blocker,
    _wincon_combat,
    _wincon_alt,
    _evasion,
    _anthem,
    _extra_phases,
    _burn,
)


def match(card: CardView) -> list[TagHit]:
    hits: dict[str, TagHit] = {}

    def add(tag: str, quality: float, why: str) -> None:
        assert tag in OWNED_TAGS, f"{DOMAIN} does not own tag {tag}"
        q = round(min(max(quality, 0.05), 1.0), 3)
        prev = hits.get(tag)
        if prev is None or q > prev.quality:
            hits[tag] = TagHit(tag, q, why)

    for helper in _HELPERS:
        helper(card, add)
    return sorted(hits.values(), key=lambda h: (-h.quality, h.tag))
