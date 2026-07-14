"""Render analysis sections to the terminal via rich."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from weaver.analysis.base import AnalysisSection

_ICON = {"ok": "[green]✓[/green]", "info": "[cyan]•[/cyan]",
         "warn": "[yellow]▲[/yellow]", "problem": "[red]✗[/red]"}
_BORDER = {"ok": "green", "info": "cyan", "warn": "yellow", "problem": "red"}


def render_report(console: Console, deck, sections: list[AnalysisSection]) -> None:
    cmdrs = ", ".join(c.name for c in deck.commanders) or "[dim]none declared[/dim]"
    console.print(f"[bold]Commander:[/bold] {cmdrs}    "
                  f"[dim]{deck.total_cards} cards, {deck.land_count} lands[/dim]")
    if deck.unresolved:
        console.print(
            f"[yellow]⚠ {len(deck.unresolved)} unresolved card(s):[/yellow] "
            + ", ".join(deck.unresolved[:8])
            + (" ..." if len(deck.unresolved) > 8 else "")
        )
    console.print()

    for section in sections:
        body = []
        for f in section.findings:
            body.append(f"{_ICON.get(f.severity, '•')} {f.message}")
        panel = Panel(
            "\n".join(body) or "[dim]no findings[/dim]",
            title=f"[bold]{section.title}[/bold]",
            border_style=_BORDER.get(section.worst_severity, "white"),
            title_align="left",
        )
        console.print(panel)
