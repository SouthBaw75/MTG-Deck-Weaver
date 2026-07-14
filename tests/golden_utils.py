"""Helpers for the hand-labeled golden card sets in tests/golden/*.yaml.

Golden file format:

    cards:
      - name: Cultivate
        mana_cost: "{2}{G}"
        mana_value: 3
        type_line: Sorcery
        oracle_text: |
          Search your library for up to two basic land cards, reveal those
          cards, and put one onto the battlefield tapped and the other into
          your hand. Then shuffle.
        keywords: []          # optional
        expect: [ramp.land, mana-fixing]
        forbid: [draw.burst]  # optional: tags that must NOT be emitted
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from weaver.knowledge.cardview import CardView
from weaver.knowledge.taxonomy import is_valid_tag

GOLDEN_DIR = Path(__file__).parent / "golden"


@dataclass
class GoldenCard:
    card: CardView
    expect: set[str]
    forbid: set[str]


def load_golden(path: Path) -> list[GoldenCard]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for entry in doc["cards"]:
        expect = set(entry.get("expect", []))
        forbid = set(entry.get("forbid", []))
        bad = [t for t in expect | forbid if not is_valid_tag(t)]
        assert not bad, f"{path.name}: {entry['name']}: unregistered tags {bad}"
        out.append(GoldenCard(CardView.from_dict(entry), expect, forbid))
    return out


def load_all_golden() -> list[GoldenCard]:
    cards = []
    for path in sorted(GOLDEN_DIR.glob("*.yaml")):
        cards.extend(load_golden(path))
    return cards
