"""Consistency analyzer: hypergeometric odds of the deck doing its job on time.

This analyzer is pure (no DB / no network): everything it needs is already on
the DeckView. It answers "how reliably does this deck hit its land drops, find
ramp/interaction/card advantage, and keep a sensible opening hand?" using the
hypergeometric distribution — the exact model for drawing without replacement.

All math is stdlib only (``math.comb``, Python 3.11) — no scipy/numpy.

Turn model (all probabilities are quoted "on the play" as the baseline):

* Opening hand = 7 cards (Commander).
* On the play you draw no card for your first turn, so **by turn T you have
  seen ``7 + (T - 1)`` cards**. "On the draw" simply adds one more card to every
  count — we mention it rather than double-reporting.

Proxies and caveats (echoed into findings so the numbers stay honest):

* **Keepable-by-land-count** is ``P(2..5 lands in the opening 7)``. It is a
  proxy for "hands you'd keep" based purely on land count — it is *not* a full
  keep/mulligan model (it ignores curve, colors, and what the spells actually
  do).
* Tag-based counts only see resolved, tagged cards. Unresolved cards still
  count toward the deck size ``N`` (they are real cards you can draw) — they
  just never contribute to a success count ``K``.
"""

from __future__ import annotations

from math import comb

from weaver.analysis.base import AnalysisSection

ORDER = 40

# --- tunable heuristics ----------------------------------------------------
OPENING_HAND = 7

# A card may carry several tags in a family; we dedupe to distinct copies.
RAMP_TAGS = ("ramp.rock", "ramp.land", "ramp.dork", "ramp.ritual")
INTERACTION_TAGS = (
    "removal.spot.creature",
    "removal.spot.any",
    "removal.spot.artifact-enchantment",
    "wipe.creature",
    "wipe.any",
    "wipe.artifact-enchantment",
    "counterspell",
)
CARD_ADVANTAGE_TAGS = ("draw.burst", "draw.engine", "impulse-draw", "wheel")
TUTOR_TAGS = ("tutor.broad", "tutor.narrow")

# Warn thresholds.
_MULLIGAN_RISK = 0.30      # P(screw) + P(flood) above this is worth a warning
# Hitting the 4th land drop by turn 4 on the play is only ~57-63% even at
# 38-40 lands, so a 0.60 floor would warn on nearly every healthy deck. 0.50
# instead flags genuinely land-light builds (<~35 lands).
_LAND_DROP_T4_FLOOR = 0.50  # P(4th land by turn 4) below this is shaky
_INTERACTION_FLOOR = 0.55   # P(>=1 interaction in opening 7) below this is low


# ---- hypergeometric core --------------------------------------------------
def hypergeom_exactly(k: int, N: int, K: int, n: int) -> float:
    """P(exactly k successes) drawing n cards from a deck of N with K successes.

    Draws are without replacement. Guards every degenerate input: a non-positive
    deck, over-drawing (n > N), impossible success counts, and K > N all return
    a sensible 0.0/valid probability rather than raising.
    """
    if N <= 0 or n < 0:
        return 0.0
    n = min(n, N)          # can't draw more cards than are in the deck
    K = max(0, min(K, N))  # can't have more successes than the whole deck
    if k < 0 or k > K or k > n:
        return 0.0
    if n - k > N - K:      # not enough non-successes to fill the rest of the draw
        return 0.0
    return comb(K, k) * comb(N - K, n - k) / comb(N, n)


def hypergeom_at_least(k: int, N: int, K: int, n: int) -> float:
    """P(at least k successes). ``k <= 0`` is certain (P(X >= 0) == 1)."""
    if N <= 0 or n < 0:
        return 0.0
    n = min(n, N)
    K = max(0, min(K, N))
    if k <= 0:
        return 1.0
    upper = min(n, K)
    if k > upper:
        return 0.0
    return sum(hypergeom_exactly(i, N, K, n) for i in range(k, upper + 1))


def hypergeom_at_least_one(N: int, K: int, n: int) -> float:
    """Convenience: P(drawing >= 1 success). 0.0 when there are no successes."""
    return hypergeom_at_least(1, N, K, n)


# ---- helpers --------------------------------------------------------------
def _pct(p: float) -> str:
    return f"{round(p * 100)}%"


def _seen_by_turn(turn: int) -> int:
    """Cards seen by turn ``turn`` on the play: opening 7 + one draw per later turn."""
    return OPENING_HAND + (turn - 1)


def _distinct_copies(deck, tags) -> int:
    """Quantity-weighted copies carrying *any* of ``tags`` (deduped per card)."""
    return sum(c.quantity for c in deck.cards if any(t in c.tags for t in tags))


# ---- analyzer -------------------------------------------------------------
def analyze(deck) -> AnalysisSection:
    section = AnalysisSection(title="Consistency")

    N = deck.total_cards or 100
    lands = deck.land_count

    # ---- opening-hand land distribution -----------------------------------
    hand_dist = {
        l: hypergeom_exactly(l, N, lands, OPENING_HAND)
        for l in range(OPENING_HAND + 1)
    }
    p_keepable = sum(hand_dist[l] for l in range(2, 6))   # 2..5 lands
    p_screw = hand_dist[0] + hand_dist[1]                 # 0..1 lands
    p_flood = hand_dist[6] + hand_dist[7]                 # 6..7 lands
    p_mull_risk = p_screw + p_flood

    # ---- land drops on the play -------------------------------------------
    land_drops = {
        t: hypergeom_at_least(t, N, lands, _seen_by_turn(t)) for t in (2, 3, 4, 5)
    }

    # ---- ramp access -------------------------------------------------------
    ramp_count = _distinct_copies(deck, RAMP_TAGS)
    ramp_open = hypergeom_at_least_one(N, ramp_count, OPENING_HAND)
    ramp_t3 = hypergeom_at_least_one(N, ramp_count, _seen_by_turn(3))

    # ---- interaction access -----------------------------------------------
    interaction_count = _distinct_copies(deck, INTERACTION_TAGS)
    interaction_open = hypergeom_at_least_one(N, interaction_count, OPENING_HAND)

    # ---- card-advantage access --------------------------------------------
    ca_count = _distinct_copies(deck, CARD_ADVANTAGE_TAGS)
    ca_t3 = hypergeom_at_least_one(N, ca_count, _seen_by_turn(3))

    # ---- tutor / finisher access (optional) -------------------------------
    tutor_count = _distinct_copies(deck, TUTOR_TAGS)
    tutor_turn = 4
    tutor_by_turn = (
        hypergeom_at_least_one(N, tutor_count, _seen_by_turn(tutor_turn))
        if tutor_count
        else 0.0
    )

    # ---- stash structured results -----------------------------------------
    section.data.update(
        deck_size=N,
        land_count=lands,
        opening_hand={
            "distribution": hand_dist,
            "p_keepable_2_5": p_keepable,
            "p_screw_0_1": p_screw,
            "p_flood_6_7": p_flood,
            "p_mulligan_risk": p_mull_risk,
        },
        land_drops=land_drops,
        ramp={
            "count": ramp_count,
            "p_opening": ramp_open,
            "p_by_turn3": ramp_t3,
        },
        interaction={
            "count": interaction_count,
            "p_opening": interaction_open,
        },
        card_advantage={
            "count": ca_count,
            "p_by_turn3": ca_t3,
        },
        tutors={
            "count": tutor_count,
            "turn": tutor_turn,
            "p_by_turn": tutor_by_turn,
        },
        assumptions=(
            "Hypergeometric, on the play (no turn-1 draw); by turn T you have "
            f"seen {OPENING_HAND} + (T-1) cards. On the draw adds 1 card to every "
            "count. Keepable = P(2-5 lands in 7), a land-count proxy, not a full "
            "keep model."
        ),
    )

    # ---- findings: opening hand -------------------------------------------
    section.add(
        "info",
        f"Opening hand (7 cards, {lands}/{N} lands): {_pct(p_keepable)} keep-able "
        f"by land count (2-5 lands) — a proxy, not a full keep model. "
        f"Screw (0-1) {_pct(p_screw)}, flood (6-7) {_pct(p_flood)}.",
    )
    if p_mull_risk > _MULLIGAN_RISK:
        section.add(
            "warn",
            f"High mulligan risk: {_pct(p_mull_risk)} of opening hands have too few "
            f"(0-1) or too many (6-7) lands — consider adjusting the land count.",
        )

    # ---- findings: land drops ---------------------------------------------
    curve = ", ".join(f"T{t} {_pct(land_drops[t])}" for t in (2, 3, 4, 5))
    section.add(
        "info",
        f"Land drops on the play (P of hitting your Tth land drop by turn T): "
        f"{curve}. On the draw is a little better.",
    )
    if land_drops[4] < _LAND_DROP_T4_FLOOR:
        section.add(
            "warn",
            f"Only {_pct(land_drops[4])} to have your 4th land by turn 4 — "
            f"expect stumbly starts; more lands or cheap ramp would help.",
        )

    # ---- findings: ramp ----------------------------------------------------
    if ramp_count:
        section.add(
            "info",
            f"Ramp access: {_pct(ramp_open)} to open with a ramp piece, "
            f"{_pct(ramp_t3)} to have seen one by turn 3 ({ramp_count} in deck).",
        )
    else:
        section.add("info", "Ramp access: no tagged ramp in the deck.")

    # ---- findings: interaction --------------------------------------------
    if interaction_count:
        sev = "warn" if interaction_open < _INTERACTION_FLOOR else "info"
        section.add(
            sev,
            f"Interaction access: {_pct(interaction_open)} to open with a piece of "
            f"interaction ({interaction_count} in deck)."
            + ("" if sev == "info" else " That's low — reactive hands will be rare."),
        )
    else:
        section.add(
            "warn",
            "Interaction access: no tagged removal/counterspells found — the deck "
            "may be unable to answer threats.",
        )

    # ---- findings: card advantage -----------------------------------------
    if ca_count:
        section.add(
            "info",
            f"Card advantage: {_pct(ca_t3)} to have seen a draw/advantage engine "
            f"by turn 3 ({ca_count} in deck).",
        )
    else:
        section.add("info", "Card advantage: no tagged draw/advantage sources.")

    # ---- findings: tutors (optional) --------------------------------------
    if tutor_count:
        section.add(
            "info",
            f"Tutor access: {_pct(tutor_by_turn)} to have seen a tutor by turn "
            f"{tutor_turn} ({tutor_count} in deck) — a proxy for finding your wincon.",
        )

    return section
