# MTG Deck Weaver

A Commander (EDH) deck-building intelligence engine for Magic: The Gathering.

Deck Weaver's goal is to be a **master of MTG rules and play mechanics** that can:

- Analyze any Commander deck for strategy, synergy, consistency, and power level
- Detect combos, engines, and win conditions (including lines you didn't know you had)
- Build custom, lethal, tuned-to-you Commander decks from a commander, a theme, or a pile of cards you own
- Explain *why* — every recommendation is backed by rules knowledge, synergy data, and format statistics

## Project Status

**Planning phase.** See the planning documents:

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
