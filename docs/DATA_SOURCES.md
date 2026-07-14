# Data Sources

Research findings (verified July 2026) on every dataset Deck Weaver needs, where it comes
from, how it's fetched, and how often it changes. The guiding principle: **everything is
downloaded into a local database** so analysis is fast, offline-capable, and never
hammers anyone's servers.

---

## 1. Card Data — Scryfall Bulk Data (primary source of truth)

- **What:** Every Magic card ever printed: name, mana cost, full Oracle text, types,
  colors, color identity, keywords, power/toughness, legalities (including `commander`),
  EDHREC rank, prices, images.
- **Where:** https://scryfall.com/docs/api/bulk-data — the **Oracle Cards** bulk file
  (one entry per unique card, ~150 MB JSON) is exactly what we want for deck building.
  The **Default Cards** file adds every printing if we later want printing/price detail.
- **Format note (important):** Scryfall is migrating bulk files to gzipped **JSONL**
  (one JSON object per line). After **July 20, 2026** JSONL is the *only* format —
  our ingest pipeline must be built JSONL-first.
- **Refresh cadence:** Bulk files regenerate every 12–24h; Oracle text only really
  changes on set releases and rules updates. **Weekly refresh + on-demand after set
  releases** is sufficient.
- **Terms:** Free, no API key. Requires attribution and polite request rates (bulk files
  avoid per-card API calls entirely).

**Role in Deck Weaver:** canonical card table. Every other dataset joins to it via
`oracle_id` / card name.

## 2. Card Ontology — MTGJSON (supplementary)

- **What:** `AtomicCards.json` (functionally-unique cards), `CardTypes.json` (the full
  type/subtype ontology: every creature type, artifact subtype, etc.), `Keywords.json`
  (every keyword ability/action ever printed), `EnumValues.json`.
- **Where:** https://mtgjson.com/downloads/all-files/ — free, open source, multiple
  compression formats.
- **Role in Deck Weaver:** gives us the *vocabulary* of the game as structured data —
  the master lists of keywords, ability words, and types that the tagging engine and
  mechanic-interaction graph are built on, so we never hand-maintain those lists.

## 3. Rules Knowledge — Comprehensive Rules (official)

- **What:** The complete Magic Comprehensive Rules — every rule number (e.g. 601.2
  casting spells, 704 state-based actions, 903 Commander), the full keyword glossary.
- **Where:** https://magic.wizards.com/en/rules — published as **plain TXT** (also PDF/DOCX),
  e.g. `media.wizards.com/2026/downloads/MagicCompRules 20260227.txt`. Updated with each
  set release (current edition effective June 19, 2026).
- **Role in Deck Weaver:** parsed into a structured, numbered rules database. Powers
  rules Q&A ("does deathtouch + trample work like I think?") and lets the synergy engine
  ground its interaction claims in actual rules (layers, replacement effects, the stack).

## 4. Combo Database — Commander Spellbook

- **What:** 30,000+ curated, verified combos: the exact cards, prerequisites, step-by-step
  results, and outcome tags (infinite mana, infinite damage, wins the game, etc.).
- **Where:** https://commanderspellbook.com — open source (MIT), Django REST backend at
  `backend.commanderspellbook.com`. Key endpoints:
  - `/variants/` — paginated dump of all combo variants (we mirror this locally)
  - `/find-my-combos` — POST a decklist, get combos present + "one card away" combos
- **Role in Deck Weaver:** the ground truth for combo detection. Local mirror gives us
  offline "your deck contains these N win lines / is one card from these M more."

## 5. Format Statistics — EDHREC

- **What:** The largest Commander meta dataset: per-commander card inclusion rates,
  synergy scores (how much more a card is played with commander X vs. baseline), theme
  pages (e.g. "aristocrats", "+1/+1 counters"), salt scores, average decks.
- **Where:** No official API, but EDHREC exposes the same **public JSON endpoints** its
  site uses (`https://json.edhrec.com/pages/commanders/<slug>.json`, plus themes, cards).
  Community wrappers exist (`pyedhrec` on PyPI) and confirm the endpoints are stable.
- **Caveats:** Unofficial — must cache aggressively, rate-limit courteously, fetch only
  what a task needs (per-commander, on demand), and degrade gracefully if the endpoints
  change. This data *enhances* recommendations; the engine must work without it.
- **Role in Deck Weaver:** the "wisdom of the crowd" signal: candidate card pools per
  commander/theme, synergy priors, and a benchmark to measure brews against.

## 6. Format Rules — Banned List, Brackets & Game Changers

- **What:** Since Feb 2025, WotC manages Commander via a **5-bracket power system**
  (1 Exhibition → 5 cEDH) plus a **Game Changers** list (~53 cards as of the Feb 9, 2026
  update — e.g. Rhystic Study, Cyclonic Rift, Demonic Tutor). Bracket rules: Game
  Changers are disallowed in brackets 1–2, ≤3 copies in bracket 3, unlimited in 4–5.
  Banned list is separate (no overlap) and captured in Scryfall's `legalities.commander`.
- **Where:** Bans come free with Scryfall data. Game Changers + bracket definitions are
  announced at magic.wizards.com — small enough to maintain as a **versioned list in this
  repo** (`data/game_changers.json`), updated when WotC posts bracket updates (~quarterly).
- **Role in Deck Weaver:** legality validation and the backbone of **bracket-aware deck
  building** — "make me the most lethal bracket-3 deck" is a first-class constraint.

## 7. Decklists — Moxfield / Archidekt (import/export, later phase)

- **What:** Deck import/export so users can pull in existing decks and share results.
- **Where:** Neither site has a fully official public API; Moxfield public-deck endpoints
  are accessible and community-wrapped, Archidekt similar. **Plain-text decklist
  import/export (the universal `1 Sol Ring` format) is the primary interface**; site
  integrations are additive later.

## 8. Prices — Scryfall (included)

Scryfall bulk data already carries USD/EUR/TIX prices per printing — enough for budget
constraints ("build this under $200", "cheapest version of this upgrade") without any
additional source. Dedicated price APIs (TCGplayer, etc.) are gated/partner-only; not needed.

---

## Ingest Pipeline Summary

| Dataset | Method | Refresh | Size (approx) |
|---|---|---|---|
| Scryfall Oracle Cards | bulk JSONL download | weekly + on set release | ~150 MB raw → SQLite |
| MTGJSON Keywords/CardTypes | file download | on set release | < 5 MB |
| Comprehensive Rules | TXT download + parser | per rules update (~quarterly) | ~3 MB |
| Commander Spellbook | REST `/variants/` mirror | weekly | ~50–100 MB |
| EDHREC pages | on-demand JSON + local cache | 30-day cache per page | small, incremental |
| Game Changers / brackets | versioned in-repo JSON | manual, per WotC announcement | tiny |

One command (`weaver update`) refreshes everything into a single local SQLite database.

**Sources:** [Scryfall bulk data docs](https://scryfall.com/docs/api/bulk-data) ·
[MTGJSON downloads](https://mtgjson.com/downloads/all-files/) ·
[WotC rules page](https://magic.wizards.com/en/rules) ·
[Commander Spellbook](https://commanderspellbook.com/about/) and its
[open-source backend](https://github.com/SpaceCowMedia/commander-spellbook-backend) ·
[pyedhrec](https://pypi.org/project/pyedhrec/) ·
[Commander Brackets update, Feb 9 2026](https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-february-9-2026)
