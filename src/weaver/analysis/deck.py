"""Decklist parsing and the resolved DeckView the analyzers consume.

A decklist is plain text (the universal export format). We accept the common
dialects:

    1 Sol Ring
    1x Sol Ring
    Sol Ring
    1 Sol Ring (C21) 263          # set/collector annotations are ignored
    1 Atraxa, Praetors' Voice *CMDR*   # Archidekt commander marker

Section headers are recognized case-insensitively: a "Commander" / "Commanders"
header puts the cards beneath it in the command zone; "Sideboard", "Maybeboard",
"Considering", and "Tokens" sections are ignored. Blank lines and comment lines
(# or //) are skipped.

Name resolution against the `cards` table is done by the DeckView builder, not
the parser, so parsing stays pure and testable offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from weaver.knowledge.cardview import CardView

# "1 ", "1x ", "01 " prefix (quantity); default 1 when absent.
_QTY = re.compile(r"^\s*(\d+)\s*[xX]?\s+(.*)$")
# Trailing set/collector annotation: "(C21) 263", "[FOIL]", "<f>"
_ANNOT = re.compile(r"\s*(\([^)]*\)\s*[\w-]*|\[[^\]]*\]|<[^>]*>)\s*$")
_CMDR_MARK = re.compile(r"\*\s*(cmdr|commander)\s*\*", re.IGNORECASE)

_IGNORE_SECTIONS = {"sideboard", "maybeboard", "considering", "tokens", "maybe"}
_COMMANDER_SECTIONS = {"commander", "commanders", "command zone"}
_DECK_SECTIONS = {"deck", "mainboard", "main", "commanderdeck"}


@dataclass
class ParsedEntry:
    quantity: int
    name: str
    is_commander: bool = False


def parse_decklist(text: str) -> list[ParsedEntry]:
    """Parse decklist text into entries. Pure: no DB access."""
    entries: list[ParsedEntry] = []
    section = "deck"  # default bucket
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue

        # Section header? ("Commander", "Commander (1)", "Deck", "SB:")
        header = line.rstrip(":").strip()
        header_key = re.sub(r"\s*\(\d+\)\s*$", "", header).lower()
        if header_key in _IGNORE_SECTIONS:
            section = "ignore"
            continue
        if header_key in _COMMANDER_SECTIONS:
            section = "commander"
            continue
        if header_key in _DECK_SECTIONS:
            section = "deck"
            continue
        if line.upper().startswith("SB:"):
            continue
        if section == "ignore":
            continue

        is_cmdr = bool(_CMDR_MARK.search(line))
        line = _CMDR_MARK.sub("", line).strip()

        m = _QTY.match(line)
        if m:
            qty = int(m.group(1))
            name = m.group(2).strip()
        else:
            qty, name = 1, line
        name = _ANNOT.sub("", name).strip()
        # Normalize DFC/split separators to Scryfall's " // ".
        name = re.sub(r"\s*/{1,3}\s*", " // ", name) if "/" in name else name
        if not name:
            continue

        entries.append(ParsedEntry(qty, name, is_cmdr or section == "commander"))
    return entries


@dataclass
class DeckCard:
    quantity: int
    name: str
    is_commander: bool
    card: CardView | None  # None if unresolved (not found in cards table)
    tags: dict[str, float] = field(default_factory=dict)  # tag -> quality
    # raw passthrough of useful scalar columns for analyzers
    mana_value: float = 0.0
    type_line: str = ""
    color_identity: list[str] = field(default_factory=list)
    legal_commander: str | None = None
    is_game_changer: bool = False

    @property
    def resolved(self) -> bool:
        return self.card is not None

    @property
    def is_land(self) -> bool:
        return self.card.is_land if self.card else "land" in self.type_line.lower()

    @property
    def is_basic_land(self) -> bool:
        return self.is_land and "basic" in self.type_line.lower()


@dataclass
class DeckView:
    cards: list[DeckCard]
    unresolved: list[str] = field(default_factory=list)

    @property
    def commanders(self) -> list[DeckCard]:
        return [c for c in self.cards if c.is_commander]

    @property
    def nonland_spells(self) -> list[DeckCard]:
        return [c for c in self.cards if not c.is_land and not c.is_commander]

    @property
    def total_cards(self) -> int:
        return sum(c.quantity for c in self.cards)

    @property
    def land_count(self) -> int:
        return sum(c.quantity for c in self.cards if c.is_land)

    def cards_with_tag(self, tag: str) -> list[DeckCard]:
        return [c for c in self.cards if tag in c.tags]

    def tag_count(self, tag: str) -> int:
        """Deck copies carrying `tag` (quantity-weighted)."""
        return sum(c.quantity for c in self.cards if tag in c.tags)
