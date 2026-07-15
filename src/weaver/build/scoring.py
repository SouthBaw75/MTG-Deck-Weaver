"""Candidate scoring: how much does this card want to be in THIS deck?

The score blends three explainable components:

  role_value  — the best role this card fills, by tag quality (a premium
                removal spell beats a clunky one).
  power       — how established the card is, from EDHREC rank (a play-rate
                proxy for raw effectiveness).
  archetype   — on-theme bonus: cards whose tags match the deck's archetype
                bias score higher, so an aristocrats deck prefers sac outlets
                and death payoffs over generic goodstuff.

Every component is recorded in cand.reasons so the dossier can explain the pick.
The scorer is pure and takes the archetype bias as a plain dict, so it does not
depend on how archetypes are stored.
"""

from __future__ import annotations

from math import log10

from weaver.build.types import BuildRequest, Candidate

# component weights
_W_ROLE = 1.0
_W_POWER = 0.6
_W_ARCHETYPE = 1.3
_W_SYNERGY = 0.9

# roles that make a card a genuine functional building block (used to give a
# small floor bonus so pure-theme cards don't crowd out the skeleton).
_SKELETON_TAGS = {
    "ramp.rock", "ramp.land", "ramp.dork", "ramp.ritual",
    "draw.burst", "draw.engine", "impulse-draw", "wheel",
    "removal.spot.creature", "removal.spot.any", "removal.spot.artifact-enchantment",
    "wipe.creature", "wipe.any", "wipe.artifact-enchantment", "counterspell",
    "tutor.broad", "tutor.narrow", "protection.self", "protection.board",
}


def power_from_rank(rank: int | None) -> float:
    """EDHREC rank -> 0..1 play-rate proxy. #1 ~ 1.0, ~#100k ~ 0.0."""
    if not rank or rank <= 0:
        return 0.2  # unknown/unranked: mildly-played prior
    return max(0.05, min(1.0, 1.0 - log10(rank) / 5.0))


def best_role_quality(cand: Candidate) -> float:
    return max(cand.tags.values(), default=0.0)


def score_candidate(
    cand: Candidate,
    request: BuildRequest,
    archetype_bias: dict[str, float] | None = None,
    synergy_profile: dict[str, float] | None = None,
) -> None:
    """Set cand.score and cand.reasons in place.

    synergy_profile is an aggregated tag->weight profile of the deck's core
    (commander + theme); candidates that interact with it via the mechanic graph
    score higher. Pass None to skip the synergy component.
    """
    bias = archetype_bias or {}
    reasons: list[str] = []

    role = best_role_quality(cand)
    if role > 0:
        top_tag = max(cand.tags, key=lambda t: cand.tags[t])
        reasons.append(f"{top_tag} (q{cand.tags[top_tag]:.2f})")

    power = power_from_rank(cand.edhrec_rank)
    if cand.edhrec_rank:
        reasons.append(f"EDHREC #{cand.edhrec_rank}")

    archetype = 0.0
    for tag, quality in cand.tags.items():
        mult = bias.get(tag)
        if mult:
            archetype += (mult - 1.0) * quality  # bias 1.0 == neutral
    if archetype > 0:
        on_theme = [t for t in cand.tags if bias.get(t, 1.0) > 1.0]
        if on_theme:
            reasons.append("on-theme: " + ", ".join(sorted(on_theme)[:3]))

    synergy = 0.0
    if synergy_profile and cand.tags:
        from weaver.knowledge.synergy import synergy_with_profile

        synergy, contribs = synergy_with_profile(cand.tags, synergy_profile)
        if synergy > 0 and contribs:
            reasons.append(f"synergy: {contribs[0].note[:60]}")
        elif synergy < 0 and contribs:
            reasons.append(f"anti-synergy: {contribs[0].note[:50]}")

    score = (
        _W_ROLE * role
        + _W_POWER * power
        + _W_ARCHETYPE * archetype
        + _W_SYNERGY * synergy
    )
    # small skeleton floor so functional cards stay competitive with theme cards
    if cand.has_any_tag(_SKELETON_TAGS):
        score += 0.05

    cand.score = round(score, 4)
    cand.reasons = reasons


def score_pool(
    candidates: list[Candidate],
    request: BuildRequest,
    archetype_bias: dict[str, float] | None = None,
    synergy_profile: dict[str, float] | None = None,
) -> None:
    for cand in candidates:
        score_candidate(cand, request, archetype_bias, synergy_profile)
