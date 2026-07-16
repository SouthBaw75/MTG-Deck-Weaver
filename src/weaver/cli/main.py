"""The `weaver` command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from weaver import __version__
from weaver.db import apply_schema, connect, default_db_path
from weaver.db.connection import default_cache_dir

console = Console()


def _open_db(db_path: str | None):
    conn = connect(db_path)
    apply_schema(conn)
    return conn


@click.group()
@click.version_option(__version__)
@click.option("--db", "db_path", default=None, help="Path to the knowledge base (default: data/cache/weaver.db)")
@click.pass_context
def cli(ctx: click.Context, db_path: str | None):
    """MTG Deck Weaver — Commander deck-building intelligence engine."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path


@cli.command()
@click.option("--only", multiple=True, help="Run only these ingesters (scryfall, mtgjson, rules, spellbook, curated)")
@click.option("--force", is_flag=True, help="Re-download sources even if cached")
@click.pass_context
def update(ctx: click.Context, only: tuple[str, ...], force: bool):
    """Download all data sources and (re)build the knowledge base."""
    from weaver.ingest import run_all

    conn = _open_db(ctx.obj["db_path"])
    results = run_all(
        conn,
        default_cache_dir(),
        only=set(only) or None,
        force=force,
        progress=lambda msg: console.print(msg, style="dim"),
    )
    table = Table(title="Knowledge base update")
    table.add_column("source")
    table.add_column("rows", justify="right")
    table.add_column("status")
    failed = False
    for r in results:
        status = r.detail or ("skipped" if r.skipped else "ok")
        if r.detail.startswith("FAILED"):
            failed = True
        table.add_row(r.name, str(r.rows), status)
        for w in r.warnings:
            console.print(f"  [yellow]warning:[/yellow] {w}")
    console.print(table)
    # Re-tag whenever we have cards: tags derive from oracle text.
    if conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]:
        from weaver.knowledge.tagger import run_tagging

        run_tagging(conn, progress=lambda msg: console.print(msg, style="dim"))
        conn.commit()
    if failed:
        raise SystemExit(1)


@cli.command()
@click.argument("name")
@click.pass_context
def card(ctx: click.Context, name: str):
    """Look up a card by (fuzzy) name and show what the engine knows."""
    conn = _open_db(ctx.obj["db_path"])
    row = conn.execute(
        "SELECT * FROM cards WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM cards WHERE name LIKE ? COLLATE NOCASE ORDER BY edhrec_rank LIMIT 1",
            (f"%{name}%",),
        ).fetchone()
    if row is None:
        console.print(f"[red]No card found matching[/red] {name!r}. Have you run `weaver update`?")
        raise SystemExit(1)

    console.print(f"[bold]{row['name']}[/bold]  {row['mana_cost'] or ''}")
    console.print(row["type_line"] or "")
    if row["oracle_text"]:
        console.print(row["oracle_text"])
    pt = [p for p in (row["power"], row["toughness"]) if p is not None]
    if pt:
        console.print("/".join(pt))
    bits = []
    bits.append(f"commander: {row['legal_commander'] or 'unknown'}")
    if row["is_game_changer"]:
        bits.append("[yellow]GAME CHANGER[/yellow]")
    if row["edhrec_rank"] is not None:
        bits.append(f"edhrec rank: {row['edhrec_rank']}")
    if row["price_usd"] is not None:
        bits.append(f"${row['price_usd']:.2f}")
    console.print(" · ".join(bits), style="dim")

    tags = conn.execute(
        "SELECT tag, quality FROM card_tags WHERE oracle_id = ? ORDER BY quality DESC, tag",
        (row["oracle_id"],),
    ).fetchall()
    if tags:
        roles = " · ".join(f"{t['tag']} ({t['quality']:.2f})" for t in tags)
        console.print(f"roles: {roles}", style="cyan")

    combos = conn.execute(
        "SELECT COUNT(*) FROM combo_cards WHERE card_name = ?", (row["name"],)
    ).fetchone()[0]
    if combos:
        console.print(f"appears in {combos} known combos", style="dim")


@cli.command()
@click.argument("query")
@click.pass_context
def rule(ctx: click.Context, query: str):
    """Show a Comprehensive Rule by number (e.g. 702.2) or search rules text."""
    conn = _open_db(ctx.obj["db_path"])
    row = conn.execute("SELECT * FROM rules WHERE rule_number = ?", (query.rstrip("."),)).fetchone()
    if row:
        console.print(f"[bold]{row['rule_number']}[/bold] {row['text']}")
        subs = conn.execute(
            "SELECT * FROM rules WHERE parent = ? ORDER BY rule_number", (row["rule_number"],)
        ).fetchall()
        for sub in subs:
            console.print(f"  [bold]{sub['rule_number']}[/bold] {sub['text']}")
        return
    # Fall back to glossary, then full-text search.
    g = conn.execute(
        "SELECT * FROM glossary WHERE term = ? COLLATE NOCASE", (query,)
    ).fetchone()
    if g:
        console.print(f"[bold]{g['term']}[/bold]: {g['definition']}")
        return
    hits = conn.execute(
        "SELECT rule_number, text FROM rules_fts WHERE rules_fts MATCH ? LIMIT 10",
        (query,),
    ).fetchall()
    if not hits:
        console.print(f"[red]No rule or glossary entry found for[/red] {query!r}")
        raise SystemExit(1)
    for h in hits:
        console.print(f"[bold]{h['rule_number']}[/bold] {h['text'][:200]}")


@cli.command()
@click.pass_context
def tag(ctx: click.Context):
    """(Re)run the role-tagging engine over the cards table."""
    from weaver.knowledge.tagger import run_tagging

    conn = _open_db(ctx.obj["db_path"])
    report = run_tagging(conn, progress=lambda msg: console.print(msg, style="dim"))
    conn.commit()
    console.print(
        f"tagged [bold]{report.cards_tagged:,}[/bold] cards with "
        f"[bold]{report.tag_rows:,}[/bold] role tags "
        f"({report.overrides_applied} curated overrides applied)"
    )
    if report.invalid_tags:
        console.print(f"[yellow]unregistered tags ignored:[/yellow] {sorted(report.invalid_tags)}")


@cli.command()
@click.argument("name")
@click.option("-n", "top_n", default=15, help="How many partners to list")
@click.pass_context
def synergies(ctx: click.Context, name: str, top_n: int):
    """Find cards that synergize with a given card via the mechanic graph."""
    from weaver.knowledge.cardview import CardView
    from weaver.knowledge.synergy import find_partners

    conn = _open_db(ctx.obj["db_path"])
    row = conn.execute("SELECT * FROM cards WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM cards WHERE name LIKE ? COLLATE NOCASE ORDER BY edhrec_rank LIMIT 1",
            (f"%{name}%",),
        ).fetchone()
    if row is None:
        console.print(f"[red]No card matching[/red] {name!r}")
        raise SystemExit(1)

    target_tags = {
        t["tag"]: t["quality"]
        for t in conn.execute("SELECT tag, quality FROM card_tags WHERE oracle_id = ?", (row["oracle_id"],))
    }
    if not target_tags:
        console.print(f"[yellow]{row['name']} has no role tags[/yellow] — run `weaver tag` first.")
        raise SystemExit(1)

    # Candidate pool: all tagged cards, tags aggregated per card.
    class _C:
        __slots__ = ("name", "tags")
        def __init__(self, name, tags):
            self.name, self.tags = name, tags

    agg: dict[str, dict[str, float]] = {}
    for r in conn.execute(
        "SELECT c.name AS name, ct.tag AS tag, ct.quality AS q "
        "FROM cards c JOIN card_tags ct ON ct.oracle_id = c.oracle_id WHERE c.name != ?",
        (row["name"],),
    ):
        agg.setdefault(r["name"], {})[r["tag"]] = r["q"]
    pool = [_C(n, tags) for n, tags in agg.items()]
    partners = find_partners(target_tags, pool, top_n=top_n)

    console.print(f"[bold]{row['name']}[/bold] — synergy partners  [dim]({', '.join(target_tags)})[/dim]")
    for pname, score, note in partners:
        tag = "[green]" if score > 0 else "[red]"
        console.print(f"  {tag}{score:+.2f}[/]  {pname}" + (f"  [dim]{note}[/dim]" if note else ""))


@cli.command()
@click.argument("tag_name", required=False)
@click.option("-n", "top_n", default=15, help="How many cards to list")
@click.pass_context
def tags(ctx: click.Context, tag_name: str | None, top_n: int):
    """List the tag taxonomy, or the best cards for one tag."""
    from weaver.knowledge.taxonomy import TAGS

    conn = _open_db(ctx.obj["db_path"])
    if tag_name is None:
        table = Table(title="Role taxonomy")
        table.add_column("tag")
        table.add_column("category")
        table.add_column("cards", justify="right")
        counts = dict(
            conn.execute("SELECT tag, COUNT(*) FROM card_tags GROUP BY tag").fetchall()
        )
        for t, (category, _desc) in sorted(TAGS.items(), key=lambda kv: (kv[1][0], kv[0])):
            table.add_row(t, category, f"{counts.get(t, 0):,}")
        console.print(table)
        return
    if tag_name not in TAGS:
        console.print(f"[red]Unknown tag[/red] {tag_name!r}. Run `weaver tags` for the list.")
        raise SystemExit(1)
    rows = conn.execute(
        "SELECT c.name, ct.quality, ct.why FROM card_tags ct"
        " JOIN cards c ON c.oracle_id = ct.oracle_id"
        " WHERE ct.tag = ?"
        " ORDER BY ct.quality DESC, c.edhrec_rank ASC LIMIT ?",
        (tag_name, top_n),
    ).fetchall()
    console.print(f"[bold]{tag_name}[/bold] — {TAGS[tag_name][1]}")
    for r in rows:
        why = f"  [dim]{r['why']}[/dim]" if r["why"] else ""
        console.print(f"  {r['quality']:.2f}  {r['name']}{why}")


@cli.command()
@click.option("--commander", required=True, help="Commander name")
@click.option("--partner", default=None, help="Partner/background/second commander")
@click.option("--bracket", default=3, type=click.IntRange(1, 5), help="Target power bracket (1-5)")
@click.option("--budget", default=None, type=float, help="Total USD budget cap")
@click.option("--theme", default=None, help="Force an archetype (e.g. aristocrats)")
@click.option("--own", "owned", default=None, type=click.Path(exists=True, dir_okay=False),
              help="Restrict to cards in this collection file")
@click.option("--out", "out_path", default=None, type=click.Path(dir_okay=False),
              help="Write the built decklist to this file")
@click.option("--validate/--no-validate", default=True, help="Run the analyzer on the built deck")
@click.option("--arena", is_flag=True, help="Restrict to cards available on MTG Arena (for Brawl)")
@click.pass_context
def build(ctx: click.Context, commander, partner, bracket, budget, theme, owned, out_path, validate, arena):
    """Build a tuned Commander deck around a commander."""
    from weaver.build.builder import build_deck
    from weaver.build.dossier import render_dossier
    from weaver.build.types import BuildRequest

    conn = _open_db(ctx.obj["db_path"])
    if conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0:
        console.print("[red]Knowledge base is empty.[/red] Run `weaver update` first.")
        raise SystemExit(1)

    owned_set = None
    if owned:
        from weaver.analysis.deck import parse_decklist
        with open(owned, encoding="utf-8") as fh:
            owned_set = {e.name for e in parse_decklist(fh.read())}

    request = BuildRequest(
        commander=commander, partner=partner, bracket=bracket,
        budget=budget, theme=theme, owned=owned_set, arena_only=arena,
    )
    try:
        result = build_deck(conn, request)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    render_dossier(console, result)

    decklist = result.to_decklist()
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(decklist + "\n")
        console.print(f"\n[green]decklist written to {out_path}[/green]")

    if validate:
        from weaver.analysis.engine import analyze_deck
        from weaver.analysis.loader import load_deck
        from weaver.analysis.report import render_report

        console.print("\n[bold]— validation (analyzing the built deck) —[/bold]\n")
        deck = load_deck(conn, decklist)
        render_report(console, deck, analyze_deck(deck))


@cli.command()
@click.argument("decklist", type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def analyze(ctx: click.Context, decklist: str):
    """Analyze a decklist (plain-text `1 Card Name` format)."""
    from weaver.analysis.engine import analyze_deck
    from weaver.analysis.loader import load_deck
    from weaver.analysis.report import render_report

    conn = _open_db(ctx.obj["db_path"])
    if conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0:
        console.print("[red]Knowledge base is empty.[/red] Run `weaver update` first.")
        raise SystemExit(1)
    with open(decklist, encoding="utf-8") as fh:
        deck = load_deck(conn, fh.read())
    sections = analyze_deck(deck)
    render_report(console, deck, sections)


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=8000, type=int, help="Bind port")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int):
    """Launch the local web app (browser UI for lookup, analyze, and build)."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]Web dependencies not installed.[/red] Run: pip install -e \".[web]\"")
        raise SystemExit(1)
    from weaver.web.app import create_app

    app = create_app(ctx.obj["db_path"])
    console.print(f"[green]MTG Deck Weaver[/green] running at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


@cli.command()
@click.pass_context
def stats(ctx: click.Context):
    """Show knowledge base row counts and data freshness."""
    conn = _open_db(ctx.obj["db_path"])
    table = Table(title=f"Knowledge base: {ctx.obj['db_path'] or default_db_path()}")
    table.add_column("table")
    table.add_column("rows", justify="right")
    for t in ["cards", "keywords", "card_types", "card_subtypes", "rules",
              "glossary", "combos", "combo_cards", "game_changers", "brackets"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        table.add_row(t, f"{n:,}")
    console.print(table)
    meta = conn.execute(
        "SELECT key, value FROM meta WHERE key LIKE '%.updated_at' ORDER BY key"
    ).fetchall()
    for m in meta:
        console.print(f"{m['key']}: {m['value']}", style="dim")


if __name__ == "__main__":
    cli()
