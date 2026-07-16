"""Shared data types for the deck builder.

These are the contracts every builder component (pool, scorer, assembler,
dossier) agrees on. Kept dependency-light so each piece is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from weaver.knowledge.cardview import CardView, export_card_name


@dataclass
class BuildRequest:
    commander: str
    partner: str | None = None
    bracket: int = 3
    budget: float | None = None          # total USD cap, None = unlimited
    theme: str | None = None             # archetype hint, e.g. "aristocrats"
    owned: set[str] | None = None        # restrict pool to these names, None = all
    land_count: int | None = None        # override the template's land count
    seed_cards: list[str] = field(default_factory=list)  # must-include names
    arena_only: bool = False             # restrict to cards available on MTG Arena


@dataclass
class Candidate:
    """A card eligible for the deck, with everything the scorer/assembler need."""
    name: str
    oracle_id: str
    card: CardView
    tags: dict[str, float]               # tag -> quality
    color_identity: list[str]
    mana_value: float
    type_line: str
    price_usd: float | None
    edhrec_rank: int | None
    is_game_changer: bool
    legal_commander: str | None
    layout: str = ""  # Scryfall layout; drives Arena-safe export names

    # filled by the scorer
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def is_land(self) -> bool:
        return "land" in self.type_line.lower()

    @property
    def is_basic_land(self) -> bool:
        return self.is_land and "basic" in self.type_line.lower()

    def has_any_tag(self, tags) -> bool:
        return any(t in self.tags for t in tags)


@dataclass
class SlotAssignment:
    candidate: Candidate
    role: str                            # the role group this card was picked for
    score: float
    reason: str
    quantity: int = 1                    # >1 only for basic lands


@dataclass
class BuildResult:
    request: BuildRequest
    commander: Candidate
    partner: Candidate | None
    assignments: list[SlotAssignment]    # nonland picks with their role + reason
    lands: list[SlotAssignment]          # land picks (basics + utility/fixing)
    unfilled: dict[str, int]             # role -> how many slots we couldn't fill
    notes: list[str] = field(default_factory=list)

    @property
    def all_cards(self) -> list[SlotAssignment]:
        return self.assignments + self.lands

    @property
    def total_cards(self) -> int:
        base = 1 + (1 if self.partner else 0)
        nonland = sum(a.quantity for a in self.assignments)
        land = sum(a.quantity for a in self.lands)
        return base + nonland + land

    def to_decklist(self) -> str:
        """Emit a plain-text decklist (the universal import/export format).

        Multi-face cards use Arena-safe names (front face for DFC/transform/
        adventure; full name for split/aftermath), so the list imports cleanly
        into MTG Arena as well as paper/Commander tools.
        """
        def nm(c) -> str:
            return export_card_name(c.name, getattr(c, "layout", ""))

        lines = ["Commander", f"1 {nm(self.commander)}"]
        if self.partner:
            lines.append(f"1 {nm(self.partner)}")
        lines.append("Deck")
        for a in self.assignments:
            lines.append(f"{a.quantity} {nm(a.candidate)}")
        for a in self.lands:
            lines.append(f"{a.quantity} {nm(a.candidate)}")
        return "\n".join(lines)
