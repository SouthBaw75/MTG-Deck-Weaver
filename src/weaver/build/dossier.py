"""Render a BuildResult as a human-readable dossier: the decklist plus the
reasoning — what each card is for, and how the deck came together."""

from __future__ import annotations

from collections import defaultdict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from weaver.build.types import BuildResult

# Order role sections read top-to-bottom in a sensible build order.
_ROLE_ORDER = [
    "seed", "ramp", "card_advantage", "spot_removal", "board_wipe",
    "targeted_disruption", "protection", "wincon", "synergy",
]
_ROLE_LABEL = {
    "seed": "Requested includes",
    "ramp": "Ramp",
    "card_advantage": "Card advantage",
    "spot_removal": "Spot removal",
    "board_wipe": "Board wipes",
    "targeted_disruption": "Disruption",
    "protection": "Protection",
    "wincon": "Win conditions",
    "synergy": "Synergy / theme",
}


def render_dossier(console: Console, result: BuildResult) -> None:
    r = result.request
    cmd = result.commander.name + (f" + {result.partner.name}" if result.partner else "")
    spent = sum(a.candidate.price_usd or 0 for a in result.all_cards)

    header = [f"[bold]{cmd}[/bold]"]
    header.append(f"bracket {r.bracket} · {result.total_cards} cards")
    if r.budget is not None:
        header.append(f"~${spent:.0f} / ${r.budget:.0f} budget")
    console.print(" · ".join(header))
    for note in result.notes:
        console.print(f"  [dim]{note}[/dim]")
    console.print()

    # Group nonland assignments by role.
    by_role: dict[str, list] = defaultdict(list)
    for a in result.assignments:
        by_role[a.role].append(a)

    for role in _ROLE_ORDER:
        picks = by_role.get(role)
        if not picks:
            continue
        table = Table(title=f"{_ROLE_LABEL.get(role, role)} ({len(picks)})", title_justify="left", show_header=False, box=None, padding=(0, 1))
        for a in sorted(picks, key=lambda x: x.score, reverse=True):
            price = f"${a.candidate.price_usd:.0f}" if a.candidate.price_usd else ""
            table.add_row(a.candidate.name, f"[dim]{a.reason}[/dim]", price)
        console.print(table)

    # Lands summary.
    land_total = sum(a.quantity for a in result.lands)
    land_bits = []
    for a in result.lands:
        land_bits.append(f"{a.quantity}× {a.candidate.name}" if a.quantity > 1 else a.candidate.name)
    console.print(Panel(", ".join(land_bits) or "[dim]none[/dim]",
                        title=f"[bold]Mana base ({land_total})[/bold]", title_align="left", border_style="green"))
