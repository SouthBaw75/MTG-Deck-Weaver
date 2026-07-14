"""The canonical card-role taxonomy (KNOWLEDGE_MODEL.md, Layer 1).

Every tag a matcher may emit is registered here; the tagger rejects
unregistered tags so the taxonomy stays the single source of truth.
"""

# tag -> (category, description)
TAGS: dict[str, tuple[str, str]] = {
    # ---- mana ----------------------------------------------------------
    "ramp.land": ("mana", "Puts extra lands onto the battlefield or fetches them to hand ahead of curve"),
    "ramp.rock": ("mana", "Artifact that produces or accelerates mana (Sol Ring)"),
    "ramp.dork": ("mana", "Creature that produces mana (Llanowar Elves)"),
    "ramp.ritual": ("mana", "One-shot burst mana (Dark Ritual, Jeska's Will)"),
    "cost-reduction": ("mana", "Makes your spells cheaper to cast"),
    "mana-fixing": ("mana", "Fixes colors (any-color producers, filtering, fetching any land type)"),
    "land.utility": ("mana", "Land with a meaningful non-mana ability"),
    # ---- card advantage --------------------------------------------------
    "draw.burst": ("card_advantage", "One-shot multi-card draw (Harmonize)"),
    "draw.engine": ("card_advantage", "Repeatable draw over time (Rhystic Study)"),
    "impulse-draw": ("card_advantage", "Exile-and-may-play card advantage"),
    "wheel": ("card_advantage", "Discard-and-refill effects (Wheel of Fortune)"),
    "recursion": ("card_advantage", "Returns cards from graveyard to hand/battlefield"),
    "tutor.broad": ("card_advantage", "Searches for any card / very wide card class (Demonic Tutor)"),
    "tutor.narrow": ("card_advantage", "Searches for a narrow card class (Worldly Tutor)"),
    # ---- interaction ------------------------------------------------------
    "removal.spot.creature": ("interaction", "Kills/exiles/neutralizes a single creature"),
    "removal.spot.any": ("interaction", "Flexible single-target removal (any/most permanent types)"),
    "removal.spot.artifact-enchantment": ("interaction", "Destroys/exiles a single artifact or enchantment"),
    "wipe.creature": ("interaction", "Mass creature removal (Wrath of God)"),
    "wipe.any": ("interaction", "Mass removal hitting multiple permanent types (Farewell)"),
    "wipe.artifact-enchantment": ("interaction", "Mass artifact/enchantment removal"),
    "counterspell": ("interaction", "Counters a spell on the stack"),
    "graveyard-hate": ("interaction", "Exiles or punishes graveyards"),
    "stax": ("interaction", "Asymmetric resource denial / lock pieces"),
    "theft": ("interaction", "Steals or borrows opponents' cards/permanents"),
    "taxing": ("interaction", "Makes opponents' actions cost more"),
    # ---- defense ----------------------------------------------------------
    "protection.self": ("defense", "Protects a specific permanent/player (hexproof, indestructible, Greaves)"),
    "protection.board": ("defense", "Protects your whole board/you from mass effects (Teferi's Protection)"),
    "fog": ("defense", "Prevents combat damage for a turn"),
    "pillow-fort": ("defense", "Static effects that make attacking you hard (Ghostly Prison)"),
    "deterrent": ("defense", "Punishes opponents for attacking/targeting you"),
    "lifegain": ("defense", "Meaningful, repeatable or large life gain"),
    "blocker.value": ("defense", "Efficient defensive body (high toughness, defender value)"),
    # ---- offense ----------------------------------------------------------
    "wincon.combat": ("offense", "Closes games through combat (overruns, huge threats)"),
    "wincon.combo-piece": ("offense", "Known combo piece that enables game-ending loops"),
    "wincon.alt": ("offense", "Alternate win condition text (Thassa's Oracle, Approach)"),
    "evasion-granting": ("offense", "Grants evasion (flying, unblockable, menace) to your team"),
    "buff.anthem": ("offense", "Static team-wide power/toughness or keyword boost"),
    "extra-combat": ("offense", "Additional combat phases"),
    "extra-turn": ("offense", "Additional turns"),
    "burn": ("offense", "Direct damage to players/planeswalkers"),
    # ---- engine parts ------------------------------------------------------
    "token-producer": ("engine", "Creates creature tokens (repeatably or in numbers)"),
    "treasure-producer": ("engine", "Creates Treasure/Gold/mana-battery tokens"),
    "sac-outlet": ("engine", "Free/cheap repeatable sacrifice outlet"),
    "death-payoff": ("engine", "Rewards your creatures dying (aristocrats)"),
    "counters-matter": ("engine", "+1/+1 counter synergy: adds, doubles, or rewards counters"),
    "landfall-payoff": ("engine", "Rewards lands entering the battlefield"),
    "spellslinger-payoff": ("engine", "Rewards casting instants/sorceries"),
    "untapper": ("engine", "Untaps permanents (Kiora's Follower)"),
    "copy-effect": ("engine", "Copies spells or permanents"),
    "blink": ("engine", "Exiles-and-returns permanents to re-trigger ETBs"),
    "cheat-into-play": ("engine", "Puts cards onto the battlefield without paying mana costs"),
    "graveyard-fill": ("engine", "Self-mill / discard that stocks your graveyard as a resource"),
    "discard-payoff": ("engine", "Rewards discarding or opponents discarding"),
    # ---- utility -----------------------------------------------------------
    "haste-granting": ("utility", "Gives your creatures haste"),
    "flash-granting": ("utility", "Lets you cast spells at instant speed"),
}

CATEGORIES = sorted({cat for cat, _ in TAGS.values()})


def is_valid_tag(tag: str) -> bool:
    return tag in TAGS


def category_of(tag: str) -> str:
    return TAGS[tag][0]
