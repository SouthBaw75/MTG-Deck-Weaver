"""Helpers to hand-build DeckView fixtures for analyzer tests (no DB needed)."""

from __future__ import annotations

from weaver.analysis.deck import DeckCard, DeckView
from weaver.knowledge.cardview import CardView


def make_card(
    name: str,
    *,
    qty: int = 1,
    commander: bool = False,
    type_line: str = "",
    mana_cost: str = "",
    mana_value: float = 0.0,
    oracle_text: str = "",
    color_identity: list[str] | None = None,
    tags: dict[str, float] | None = None,
    legal_commander: str = "legal",
    game_changer: bool = False,
    price_usd: float | None = None,
) -> DeckCard:
    cv = CardView.from_dict(
        {
            "name": name,
            "type_line": type_line,
            "mana_cost": mana_cost,
            "mana_value": mana_value,
            "oracle_text": oracle_text,
            "color_identity": color_identity or [],
        }
    )
    return DeckCard(
        quantity=qty,
        name=name,
        is_commander=commander,
        card=cv,
        tags=dict(tags or {}),
        mana_value=mana_value,
        type_line=type_line,
        color_identity=color_identity or [],
        legal_commander=legal_commander,
        is_game_changer=game_changer,
        price_usd=price_usd,
    )


def make_deck(cards: list[DeckCard], unresolved: list[str] | None = None) -> DeckView:
    return DeckView(cards=cards, unresolved=unresolved or [])


def basic_lands(counts: dict[str, int]) -> list[DeckCard]:
    """counts like {"Forest": 20, "Island": 10} -> basic land DeckCards."""
    ci = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}
    out = []
    for name, n in counts.items():
        out.append(
            make_card(
                name,
                qty=n,
                type_line=f"Basic Land — {name}",
                color_identity=[ci[name]] if name in ci else [],
                oracle_text=f"({{T}}: Add {{{ci.get(name, 'C')}}}.)",
            )
        )
    return out
