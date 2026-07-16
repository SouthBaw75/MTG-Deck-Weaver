"""Normalized view of a card for the pattern matchers, plus the TagHit type.

Matchers never touch raw DB rows or Scryfall JSON — they see a CardView with
pre-normalized text so every matcher benefits from the same cleanup:

- reminder text "(...)" stripped
- the card's own name (and its short first name) replaced with "~"
- text split into ability lines, with lowercase variants precomputed
- type line parsed into supertypes / types / subtypes sets (lowercase)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_REMINDER = re.compile(r"\([^()]*\)")
_SPLIT_TYPES = re.compile(r"\s*//\s*")

# Supertypes per CR 205.4a (lowercase).
SUPERTYPES = {"basic", "legendary", "ongoing", "snow", "world"}

# Multi-face layouts whose decklist entry uses the WHOLE "Front // Back" name —
# both halves are a single castable object. Every other multi-face layout
# (transform, modal_dfc, meld, adventure, flip, …) is referenced by its FRONT
# face, which is what MTG Arena's importer requires; pasting the combined name
# yields "unknown card title".
_FULL_NAME_LAYOUTS = {"split", "aftermath"}


def export_card_name(name: str, layout: str | None = None) -> str:
    """The card name to write into an exported/importable decklist.

    Scryfall stores multi-face cards under the combined ``Front // Back`` name,
    but MTG Arena (and most import tools) key transforming/modal/adventure cards
    by their front face only. Return the front face for those, and the full name
    for split/aftermath cards (and for any single-face card, unchanged).
    """
    if " // " not in name:
        return name
    if (layout or "").lower() in _FULL_NAME_LAYOUTS:
        return name
    return name.split(" // ", 1)[0].strip()


@dataclass(frozen=True)
class TagHit:
    tag: str
    quality: float
    why: str = ""


@dataclass
class CardView:
    name: str
    type_line: str = ""
    oracle_text: str = ""
    mana_cost: str = ""
    mana_value: float = 0.0
    colors: list[str] = field(default_factory=list)
    color_identity: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    produced_mana: list[str] = field(default_factory=list)
    power: str | None = None
    toughness: str | None = None

    # -- derived, filled by __post_init__ --
    text: str = field(init=False, default="")
    text_lower: str = field(init=False, default="")
    lines: list[str] = field(init=False, default_factory=list)
    lines_lower: list[str] = field(init=False, default_factory=list)
    types: set[str] = field(init=False, default_factory=set)
    subtypes: set[str] = field(init=False, default_factory=set)
    supertypes: set[str] = field(init=False, default_factory=set)
    keywords_lower: set[str] = field(init=False, default_factory=set)

    def __post_init__(self):
        text = _REMINDER.sub("", self.oracle_text or "")
        # Self-references: full name, and the pre-comma short name
        # ("Yuriko, the Tiger's Shadow" is referenced as "Yuriko").
        for alias in self._name_aliases():
            text = text.replace(alias, "~")
        self.text = text
        self.text_lower = text.lower()
        self.lines = [ln.strip() for ln in text.split("\n") if ln.strip() and ln.strip() != "//"]
        self.lines_lower = [ln.lower() for ln in self.lines]

        # Type line: multi-face lines are merged ("Instant // Sorcery").
        for part in _SPLIT_TYPES.split(self.type_line or ""):
            left, _, right = part.partition("—")
            for word in left.split():
                w = word.strip().lower()
                if w in SUPERTYPES:
                    self.supertypes.add(w)
                elif w:
                    self.types.add(w)
            for word in right.split():
                self.subtypes.add(word.strip().lower())

        self.keywords_lower = {k.lower() for k in self.keywords}

    def _name_aliases(self) -> list[str]:
        aliases = []
        for face in self.name.split(" // "):
            aliases.append(face)
            short = face.split(",")[0].strip()
            if short and short != face:
                aliases.append(short)
        # Longest first so full names are replaced before their prefixes.
        return sorted(set(aliases), key=len, reverse=True)

    # -- convenience predicates ------------------------------------------
    @property
    def is_creature(self) -> bool:
        return "creature" in self.types

    @property
    def is_land(self) -> bool:
        return "land" in self.types

    @property
    def is_permanent(self) -> bool:
        return bool(self.types & {"creature", "artifact", "enchantment", "land", "planeswalker", "battle"})

    @property
    def is_instant_speed(self) -> bool:
        return "instant" in self.types or "flash" in self.keywords_lower

    def has_keyword(self, kw: str) -> bool:
        return kw.lower() in self.keywords_lower

    # -- constructors -------------------------------------------------------
    @classmethod
    def from_row(cls, row) -> "CardView":
        """Build from a `cards` table row (sqlite3.Row)."""

        def js(col):
            raw = row[col]
            return json.loads(raw) if raw else []

        return cls(
            name=row["name"],
            type_line=row["type_line"] or "",
            oracle_text=row["oracle_text"] or "",
            mana_cost=row["mana_cost"] or "",
            mana_value=row["mana_value"] or 0.0,
            colors=js("colors"),
            color_identity=js("color_identity"),
            keywords=js("keywords"),
            produced_mana=js("produced_mana"),
            power=row["power"],
            toughness=row["toughness"],
        )

    @classmethod
    def from_dict(cls, d: dict) -> "CardView":
        """Build from a golden-fixture dict (see tests/golden/*.yaml)."""
        return cls(
            name=d["name"],
            type_line=d.get("type_line", ""),
            oracle_text=d.get("oracle_text", ""),
            mana_cost=d.get("mana_cost", ""),
            mana_value=d.get("mana_value", 0.0),
            colors=d.get("colors", []),
            color_identity=d.get("color_identity", []),
            keywords=d.get("keywords", []),
            produced_mana=d.get("produced_mana", []),
            power=str(d["power"]) if "power" in d else None,
            toughness=str(d["toughness"]) if "toughness" in d else None,
        )


# ---- quality helpers ------------------------------------------------------

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def cheaper_is_better(mana_value: float, best: float = 1.0, worst: float = 7.0) -> float:
    """1.0 at `best` mana value or less, scaling linearly down to 0.3 at `worst`."""
    if mana_value <= best:
        return 1.0
    if mana_value >= worst:
        return 0.3
    return clamp01(1.0 - 0.7 * (mana_value - best) / (worst - best))
