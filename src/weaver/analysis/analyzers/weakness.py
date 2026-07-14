"""Defense & weaknesses: what kind of deck is this defensively, and what beats it?

Every Commander deck has a defensive *shape*. Some grind through removal by
rebuilding; some slam the door shut and reset the board; some simply race and
never intend to play defense at all. This analyzer reads the deck's
defensive/interactive toolkit from the tag vocabulary, classifies the deck into
a small set of defense *profiles*, and — the real payoff — reasons about the
holes: the archetypes and lines of play that this particular configuration is
structurally weak to ("blind spots").

Pure and offline: everything comes from ``DeckView`` tags, so it unit-tests
against hand-built fixtures with no DB or network.

Caveat on "instant-speed" interaction: the tag vocabulary records *what* a card
does (removal, counter) but not reliably *when* it can do it. We therefore
approximate a deck's ability to interact on opponents' turns as
``counterspell`` + all spot/mass removal, and label it explicitly as an
approximation — a sorcery-speed Wrath is counted here even though it cannot
answer an instant-speed haymaker. Treat the instant-interaction number as an
upper bound.
"""

from __future__ import annotations

from weaver.analysis.base import AnalysisSection

ORDER = 50

# --- bucket definitions: label -> the exact taxonomy tags that feed it -------
# A card counts once per bucket even if it carries several of the bucket's tags
# (dedupe within a bucket), quantity-weighted — same idea as roles.py.
_BUCKETS: dict[str, list[str]] = {
    "spot_removal": [
        "removal.spot.creature",
        "removal.spot.any",
        "removal.spot.artifact-enchantment",
    ],
    "board_wipes": [
        "wipe.creature",
        "wipe.any",
        "wipe.artifact-enchantment",
    ],
    "counters": ["counterspell"],
    "protection": ["protection.self", "protection.board"],
    "fog": ["fog"],
    "pillow_fort": ["pillow-fort", "deterrent"],
    "lifegain": ["lifegain"],
    "graveyard_hate": ["graveyard-hate"],
    "recursion": ["recursion"],
}

# "Can this deck interact on an opponent's turn?" — approximated as counters
# plus all removal (see module docstring caveat: not all removal is instant).
_INSTANT_TAGS: list[str] = (
    ["counterspell"] + _BUCKETS["spot_removal"] + _BUCKETS["board_wipes"]
)

# Threat / wincon density — a proxy for "wins before it needs to defend".
_THREAT_TAGS: list[str] = [
    "wincon.combat",
    "wincon.combo-piece",
    "wincon.alt",
    "extra-combat",
    "extra-turn",
]

# --- tuning knobs (documented heuristics, not magic) -------------------------
_SPOT_FLOOR = 5  # community rule of thumb: want ~5+ pieces of spot removal
_INSTANT_LOW = 3  # below this, "little stack/instant interaction"
_LIFEGAIN_LOW = 3
_INSUFFICIENT = 2  # fewer than this many tagged-relevant copies total -> thin data
_BLEND_DELTA = 0.15  # style scores within 15% of the top -> note a blend

_STYLE_LABELS = {
    "control": "Control / Interaction-heavy",
    "fortress": "Fortress",
    "resilience": "Resilience",
    "speed": "Speed / Race",
    "fragile": "Fragile / Underdefended",
}


def _bucket_count(deck, tags: list[str]) -> int:
    """Quantity-weighted count of cards carrying ANY tag in `tags` (deduped)."""
    tagset = set(tags)
    return sum(c.quantity for c in deck.cards if tagset.intersection(c.tags))


def _score_styles(b: dict[str, int], threat: int, total_defense: int) -> dict[str, float]:
    """Score each defense profile from the bucket counts.

    Heuristics (weights reflect how *defining* each ingredient is for a style):
      - control:    counters are the signature, backed by spot removal + wipes.
      - fortress:   pillow-fort/deterrent to discourage, wipes + lifegain to
                    survive and reset.
      - resilience: recursion to rebuild + protection to grind through removal.
      - speed:      raw threat density, discounted by how much defense the deck
                    is carrying (a deck loaded with answers isn't racing).
      - fragile:    the absence of everything — high only when total defense is
                    near zero.
    """
    return {
        "control": 2.0 * b["counters"] + 1.0 * b["spot_removal"] + 1.5 * b["board_wipes"],
        "fortress": 2.0 * b["pillow_fort"] + 1.5 * b["board_wipes"] + 1.0 * b["lifegain"],
        "resilience": 1.5 * b["recursion"] + 2.0 * b["protection"],
        "speed": max(0.0, 1.0 * threat - 0.5 * total_defense),
        "fragile": max(0.0, float(_SPOT_FLOOR + 1 - total_defense)),
    }


def analyze(deck) -> AnalysisSection:
    section = AnalysisSection(title="Defense & Weaknesses")

    # --- count the toolkit ---------------------------------------------------
    counts = {name: _bucket_count(deck, tags) for name, tags in _BUCKETS.items()}
    instant_interaction = _bucket_count(deck, _INSTANT_TAGS)
    threat = _bucket_count(deck, _THREAT_TAGS)
    total_defense = sum(counts.values())
    commander_reliant = len(deck.commanders) > 0

    section.data["buckets"] = dict(counts)
    section.data["instant_interaction"] = instant_interaction
    section.data["instant_interaction_approx"] = True
    section.data["threat_density"] = threat
    section.data["total_defense"] = total_defense
    section.data["commander_reliant"] = commander_reliant

    # --- defense-style classification ---------------------------------------
    scores = _score_styles(counts, threat, total_defense)
    section.data["style_scores"] = {k: round(v, 2) for k, v in scores.items()}
    top = max(scores, key=lambda k: scores[k])
    top_score = scores[top]
    section.data["defense_style"] = top

    # Blend note: any other style within _BLEND_DELTA of the top (and non-trivial).
    blends = [
        k
        for k, v in scores.items()
        if k != top and top_score > 0 and (top_score - v) <= _BLEND_DELTA * top_score and v > 0
    ]
    section.data["style_blend"] = blends

    rationale = {
        "control": f"counters={counts['counters']}, spot removal={counts['spot_removal']}, "
        f"wipes={counts['board_wipes']} — answers threats on the stack and the board",
        "fortress": f"pillow-fort/deterrent={counts['pillow_fort']}, wipes={counts['board_wipes']}, "
        f"lifegain={counts['lifegain']} — discourage attacks, reset, outlast",
        "resilience": f"recursion={counts['recursion']}, protection={counts['protection']} — "
        f"rebuild and protect, grind through removal",
        "speed": f"threat density={threat} vs total defense={total_defense} — "
        f"aims to win before defense matters",
        "fragile": f"total defense pieces={total_defense} — thin across every answer type",
    }
    style_line = f"Defense style: {_STYLE_LABELS[top]} ({rationale[top]})"
    if blends:
        style_line += " — blends with " + ", ".join(_STYLE_LABELS[b] for b in blends)
    section.add("info", style_line)

    # --- blind spots: what beats this deck ----------------------------------
    # Collected in priority order (most game-losing first) so the headline can
    # pick the single most important one.
    blind_spots: list[dict] = []

    def flag(severity: str, message: str) -> None:
        blind_spots.append({"severity": severity, "message": message})

    if counts["board_wipes"] == 0:
        flag(
            "warn",
            "No board wipes: vulnerable to go-wide token/aggro swarms you can't "
            "reset once they establish.",
        )
    if counts["counters"] == 0 and instant_interaction < _INSTANT_LOW:
        flag(
            "warn",
            "Little/no stack interaction: vulnerable to combo and instant-speed "
            "haymakers (approx: no counters and few instant-capable answers).",
        )
    if counts["spot_removal"] < _SPOT_FLOOR:
        flag(
            "warn",
            f"Thin on spot removal ({counts['spot_removal']}, want ~{_SPOT_FLOOR}+): "
            "struggles to answer a single problematic permanent.",
        )
    if counts["protection"] == 0 and commander_reliant:
        flag(
            "warn",
            "No protection with a commander declared: your commander/key pieces are "
            "exposed to targeted removal.",
        )
    if counts["fog"] == 0 and counts["lifegain"] < _LIFEGAIN_LOW and counts["spot_removal"] < _SPOT_FLOOR:
        flag(
            "warn",
            "Few emergency answers to a big alpha strike (Craterhoof, voltron): no "
            "fogs, little lifegain, thin removal.",
        )
    if counts["graveyard_hate"] == 0:
        # Info by default; a higher-power context might upgrade this to warn.
        flag(
            "info",
            "No graveyard hate: reanimator/recursion decks get to operate freely.",
        )

    section.data["blind_spots"] = [bs["message"] for bs in blind_spots]

    # --- well-rounded positive note -----------------------------------------
    all_present = all(v > 0 for v in counts.values())
    if all_present:
        section.add(
            "ok",
            "Well-rounded defense: every answer type is represented (removal, "
            "wipes, counters, protection, fog, pillow-fort, lifegain, graveyard "
            "hate, recursion).",
        )

    # --- insufficient-data guard --------------------------------------------
    thin_data = (total_defense + threat) < _INSUFFICIENT
    if thin_data:
        section.add(
            "info",
            "Insufficient tagged data to judge defense — few interactive/threat "
            "tags present; results below are low-confidence.",
        )

    # --- headline: the single most important blind spot, or all-clear -------
    warns = [bs for bs in blind_spots if bs["severity"] == "warn"]
    if warns:
        section.add("warn", "Biggest blind spot: " + warns[0]["message"])
    elif not thin_data:
        section.add(
            "ok",
            "Well-defended: no major structural blind spots — the deck can answer "
            "the common threat vectors.",
        )

    # --- emit the remaining blind-spot findings (dedupe the headline) --------
    for i, bs in enumerate(blind_spots):
        if warns and bs is warns[0]:
            continue  # already surfaced as the headline
        section.add(bs["severity"], bs["message"])

    return section
