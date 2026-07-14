# MTG Deck Weaver — Master Plan

## Vision

A program with mastery-level knowledge of Magic: The Gathering rules and mechanics,
purpose-built for Commander. You give it a commander, a strategy, a budget, or an
existing deck — it gives you back a lethal, synergistic, *custom* 100-card build and can
explain every choice: what each card does for the deck, how the pieces interact, how the
deck wins, and how it defends itself.

**Design principles**

1. **Local-first.** All knowledge lives in a local database built from public data
   sources ([DATA_SOURCES.md](DATA_SOURCES.md)). Fast, offline-capable, no rate-limit
   anxiety, reproducible.
2. **Explainable.** Never "trust me" — every synergy claim cites an interaction pattern
   or rule; every deck slot states its role; every combo lists its steps.
3. **Understanding over lookup.** The knowledge model
   ([KNOWLEDGE_MODEL.md](KNOWLEDGE_MODEL.md)) reasons over mechanics and patterns, so it
   handles new cards and off-meta brews — not just netdeck averages.
4. **Lethal within context.** Power is tuned to the official bracket system (1–5).
   "Amazing" means maximally effective *at your table*, whether that's bracket 3 or cEDH.

## Proposed Tech Stack

| Piece | Choice | Why |
|---|---|---|
| Language | **Python 3.12+** | Best ecosystem for data pipelines + analysis; existing MTG libs (`pyedhrec`, Scryfall wrappers); easy for us to iterate together |
| Storage | **SQLite** (+ FTS5 full-text search) | Single-file DB, zero setup, comfortably handles ~30k unique cards + 30k combos + rules text |
| Interface v1 | **CLI** (`weaver` command, rich terminal output) | Fastest path to a working brain; UI comes after the engine is smart |
| Interface v2 | **Local web app** (FastAPI + simple frontend) | Visual deck view, curve charts, synergy graph — once the engine earns it |
| Card text analysis | Rule-based parsers + curated data first; LLM assist optional later | Deterministic, testable, free |

## Repository Layout (target)

```
MTG-Deck-Weaver/
├── docs/                  # These planning docs, design notes
├── data/
│   ├── curated/           # Hand-maintained: game_changers.json, tag_overrides.yaml,
│   │                      #   interaction_seeds.yaml, archetypes/, bracket_templates/
│   └── cache/             # Downloaded bulk data (gitignored)
├── src/weaver/
│   ├── ingest/            # Scryfall/MTGJSON/Spellbook/EDHREC/rules downloaders & parsers
│   ├── db/                # Schema, migrations, query layer
│   ├── knowledge/         # Tagging engine, interaction graph, archetypes
│   ├── analysis/          # Deck math, role coverage, combo detection, bracket estimator
│   ├── builder/           # Deck construction & optimization
│   ├── rules/             # Comprehensive Rules lookup / Q&A
│   └── cli/               # The `weaver` command
└── tests/                 # Heavy on golden tests: known decks → expected analyses
```

## Roadmap

### Phase 0 — Data Foundation *(the "prepare the data" phase — first code we write)*
Build `weaver update`: download and parse all sources into SQLite.
- Scryfall Oracle Cards (JSONL) → `cards` table (name, oracle text, types, colors,
  color identity, keywords, mana value, legalities, EDHREC rank, prices)
- MTGJSON → `keywords`, `card_types` vocabulary tables
- Commander Spellbook `/variants/` mirror → `combos`, `combo_cards` tables
- Comprehensive Rules TXT → parsed `rules` table (rule number → text) + glossary, FTS-indexed
- Curated seeds: `game_changers.json`, bracket definitions
- `weaver card "Sol Ring"` and `weaver rule 702.2` work end to end
- **Exit test:** fresh clone → `weaver update` → full knowledge base in < 10 min

### Phase 1 — Card Understanding
The tagging engine: role tags with quality weights for all ~30k Commander-legal cards
(rules-pattern pass + curated overrides; EDHREC pass can come later).
- **Exit test:** golden set of ~300 hand-labeled cards ≥ 95% tag accuracy;
  `weaver card` shows roles ("Swords to Plowshares — removal.spot.creature, quality 0.95")

### Phase 2 — Deck Analysis (first *useful* release)
`weaver analyze deck.txt`: legality check, mana math, hypergeometric consistency, role
coverage vs. bracket benchmark, combo detection (local Spellbook mirror), Game Changer
count + bracket estimate, weakness report (defense-style blind spots), upgrade hints.
- **Exit test:** analyses of a known-strong cEDH list, a precon, and a janky brew all
  read as accurate to an experienced player

### Phase 3 — Synergy Engine
The mechanic-interaction graph + archetype profiles. Deck analysis gains a synergy-density
score and "hidden gem / dead card" detection; `weaver synergies <card>` finds partners
for any card; near-miss combos ("one card away from...") surface with tutors weighted in.

### Phase 4 — Deck Builder (the headline feature)
`weaver build --commander "Yuriko, the Tiger's Shadow" --bracket 4 --budget 400 [--own collection.txt]`
1. Resolve strategy: commander → viable archetypes (interaction graph + EDHREC priors) → user picks or auto
2. Candidate pool: color-identity-legal cards scored by synergy with commander + archetype
3. Constraint solve: fill a bracket-appropriate role template maximizing synergy density
   under budget/bracket/collection constraints (greedy + local-search swaps)
4. Emit decklist + full dossier: role of every card, combo lines, mulligan guide, how it
   wins, how it defends, weaknesses to watch
- **Exit test:** built decks pass Phase 2 analysis at target bracket and goldfish
  competitively vs. the EDHREC average deck for the same commander

### Phase 5 — Polish & Surface
Local web UI (deck canvas, curve/color charts, interactive synergy graph), Moxfield/
Archidekt import, collection management, meta-tuning ("my pod plays lots of graveyard
decks — adjust"), optional LLM-assisted natural-language rules Q&A on top of the rules DB.

## Sequencing Logic

Each phase ships something usable and feeds the next: you can't tag cards without data
(0→1), can't judge decks without tags (1→2), can't find deep synergy without analysis
plumbing (2→3), and the builder (4) is "analysis run in reverse" — it needs everything
before it. UI last, brain first.

## Open Decisions (defaults chosen, easy to change)

1. **Python + CLI first** — chosen for iteration speed. If you'd rather have a
   point-and-click app from day one, we'd swap Phase 5 forward and accept a slower start.
2. **Bracket-aware by default** — decks target a bracket (default 3). Say the word if
   you only care about cEDH-style maximum lethality and we'll default to bracket 4–5.
3. **EDHREC as enhancement, not dependency** — unofficial endpoints, so the engine must
   stand alone without them. Priority of that integration can move up or down.
4. **No card images / proxy printing in scope** — analysis and building only, until asked.
