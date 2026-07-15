"""Deck Value: an approximate total based on current card prices.

Sums each card's USD price (from Scryfall, quantity-weighted). Basic lands and
some cards have no price on file; those are counted separately so the estimate
stays honest rather than silently undercounting. Pure: reads DeckCard.price_usd.
"""

from __future__ import annotations

from weaver.analysis.base import AnalysisSection

ORDER = 15  # right after Legality & Bracket


def analyze(deck) -> AnalysisSection:
    section = AnalysisSection(title="Deck Value")

    total = 0.0
    priced = 0
    unpriced = 0
    priced_cards: list[tuple[str, float, int]] = []  # (name, unit price, qty)

    unresolved = sum(c.quantity for c in deck.cards if not c.resolved)
    for c in deck.cards:
        if not c.resolved:
            continue
        if c.price_usd is None:
            # Basic lands legitimately have no price; don't nag about those.
            if not c.is_basic_land:
                unpriced += c.quantity
            continue
        total += c.price_usd * c.quantity
        priced += c.quantity
        priced_cards.append((c.name, c.price_usd, c.quantity))

    section.data["total_usd"] = round(total, 2)
    section.data["priced_cards"] = priced
    section.data["unpriced_cards"] = unpriced
    section.data["unresolved_cards"] = unresolved

    section.add("info", f"Approximate deck value: [bold]${total:,.2f}[/bold] "
                        f"(based on current prices for {priced} card(s)).")

    # Most expensive cards — where the money is.
    priced_cards.sort(key=lambda t: t[1] * t[2], reverse=True)
    top = priced_cards[:5]
    section.data["top_cards"] = [
        {"name": n, "unit": round(p, 2), "quantity": q, "line": round(p * q, 2)}
        for n, p, q in top
    ]
    for name, unit, qty in top:
        line = unit * qty
        qty_str = f"{qty}× " if qty > 1 else ""
        section.add("info", f"  {qty_str}{name} — ${line:,.2f}")

    caveats = []
    if unpriced:
        caveats.append(f"{unpriced} card(s) had no price on file")
    if unresolved:
        caveats.append(f"{unresolved} unresolved card(s) couldn't be priced")
    if caveats:
        section.add("warn", "Estimate excludes: " + "; ".join(caveats) + " — actual value is higher.")

    section.add("info", "Prices are approximate (Scryfall market data) and drift over time.")
    return section
