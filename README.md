# MTG Deck Weaver

![The Deck Weaver at the loom](assets/splash.png)

A Commander (EDH) deck-building intelligence engine for Magic: The Gathering.

Deck Weaver's goal is to be a **master of MTG rules and play mechanics** that can:

- Analyze any Commander deck for strategy, synergy, consistency, and power level
- Detect combos, engines, and win conditions (including lines you didn't know you had)
- Build custom, lethal, tuned-to-you Commander decks from a commander, a theme, or a pile of cards you own
- Explain *why* — every recommendation is backed by rules knowledge, synergy data, and format statistics

## Project Status

**All planned phases are built (0–5).** The `weaver` CLI downloads all public data
sources into a local SQLite knowledge base, answers card and rules lookups, tags
every card with its strategic roles (ramp, draw, removal, wincon, ...) scored by
quality — validated against a hand-labeled 348-card golden corpus at 100% recall
with zero false-positive violations — reasons about how mechanics interact via a
150-edge **synergy graph**, **analyzes whole decklists** across seven angles
(legality & bracket floor, mana base, role coverage, synergy density,
hypergeometric consistency, combo detection, defense/weakness), and **builds tuned
decks**: give it a commander and a bracket and it constructs a legal 100-card
singleton deck around the commander's archetype — choosing cards that actually
interact — then self-validates it through the analyzer. A local **web app**
(`weaver serve`) puts a browser UI on all of it, with the splash art as the front
door.

### Quickstart

```bash
pip install -e ".[dev]"      # install the weaver CLI (Python 3.11+)
weaver update                # download + build the knowledge base (needs internet)
weaver card "Rhystic Study"  # card lookup: oracle text, legality, roles, Game Changer flag
weaver rule 702.2            # Comprehensive Rules lookup (or full-text: weaver rule deathtouch)
weaver tag                   # (re)run the role-tagging engine over all cards
weaver tags ramp.rock        # best cards for a role; `weaver tags` lists the taxonomy
weaver synergies "Blood Artist"  # cards that interact with a given card
weaver analyze mydeck.txt    # full deck report: legality, bracket, mana base, synergy, ...
weaver build --commander "Meren of Clan Nel Toth" --bracket 3 --budget 300 --out deck.txt
                             # build a tuned deck, then self-validate it
weaver serve                 # launch the web app at http://127.0.0.1:8000
weaver stats                 # knowledge base row counts and freshness
```

The web app (`pip install -e ".[web]"` then `weaver serve`) wraps everything in a
browser UI: card lookup, deck analysis with charts, and the deck builder — the
splash screen is the front door.

```bash
pytest                       # offline test suite (500+ tests, no network needed)
```

`weaver update` fetches from api.scryfall.com, mtgjson.com, media.wizards.com /
magic.wizards.com, and backend.commanderspellbook.com — allow those hosts if you
run it in a restricted environment. Everything else works offline.

### Planning documents

| Document | Purpose |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | Vision, architecture, and phased roadmap |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | Researched data sources: what we ingest and from where |
| [docs/KNOWLEDGE_MODEL.md](docs/KNOWLEDGE_MODEL.md) | How the program "understands" cards: tagging, synergy, and combo modeling |

## The Short Version

1. **Data layer** — nightly-refreshable local database built from Scryfall bulk data (every card, full Oracle text), MTGJSON (keywords/types), Commander Spellbook (30k+ combos), EDHREC (play-rate and synergy statistics), and the official Comprehensive Rules text.
2. **Knowledge layer** — a card-role tagging engine (ramp, draw, removal, tutor, wincon, protection...), a mechanic-interaction graph (how abilities play off each other), and archetype/defense-style profiles.
3. **Analysis engine** — deck grading: mana math, role coverage, synergy density, combo detection, bracket/power estimation, and weakness reports.
4. **Deck builder** — constraint-based optimizer that assembles a 100-card deck around a commander and strategy, tuned for lethality within your chosen power bracket and budget.
