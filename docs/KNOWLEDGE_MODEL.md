# Knowledge Model — How Deck Weaver "Understands" Magic

Raw card data tells you what a card *says*. Deck Weaver needs to know what a card
*does*, what it's *for*, and what it *becomes* next to other cards. This document
defines the three layers that turn a card database into strategic understanding.

---

## Layer 1: Card Roles (functional tagging)

Every card gets zero or more **role tags** — the jobs it can do in a deck. This is the
foundation of deck-quality analysis, because a good Commander deck is a portfolio of
roles, not a pile of good cards.

### Core role taxonomy (v1)

| Category | Tags |
|---|---|
| **Mana** | `ramp.land` (Cultivate), `ramp.rock` (Sol Ring), `ramp.dork` (Llanowar Elves), `ramp.ritual`, `cost-reduction` |
| **Card advantage** | `draw.burst`, `draw.engine` (Rhystic Study), `impulse-draw`, `wheel`, `recursion`, `tutor.broad` (Demonic Tutor), `tutor.narrow` |
| **Interaction** | `removal.spot.creature`, `removal.spot.any`, `wipe.creature`, `wipe.artifact-enchantment`, `counterspell`, `graveyard-hate`, `stax`, `theft` |
| **Defense** | `protection.self` (hexproof granting, Lightning Greaves), `protection.board` (Teferi's Protection), `fog`, `pillow-fort` (Ghostly Prison), `deterrent`, `lifegain`, `blocker.value` |
| **Offense** | `wincon.combat`, `wincon.combo-piece`, `wincon.alt` (Thassa's Oracle, Approach), `evasion-granting`, `buff.anthem`, `extra-combat`, `burn` |
| **Engine parts** | `token-producer`, `sac-outlet`, `death-payoff` (aristocrats), `counters-matter`, `landfall-payoff`, `spellslinger-payoff`, `untapper`, `copy-effect`, `blink`, `cheat-into-play` |
| **Utility** | `haste-granting`, `flash-granting`, `taxing`, `land.utility`, `mana-fixing` |

### How tags are assigned (three passes, best signal wins)

1. **Rules-pattern pass** — regexes/parsers over Oracle text using MTGJSON's keyword
   and type vocabularies ("search your library for a basic land" → `ramp.land`;
   "destroy target creature" → `removal.spot.creature`). Catches ~80% cheaply and
   works automatically for brand-new sets.
2. **Statistical pass** — EDHREC theme/category membership as a prior (they already
   bucket cards into ramp/removal/draw per page).
3. **Curated overrides** — a human-editable YAML file for the cards heuristics get
   wrong (there are always some). Ships with the repo, grows over time, and is the
   escape hatch that keeps quality high.

Each tag stores a **quality weight** (Swords to Plowshares is a better
`removal.spot.creature` than Murder: cheaper, fewer restrictions) derived from mana
value, speed (instant > sorcery), restrictions, and play-rate.

## Layer 2: Mechanic Interaction Graph (how abilities play off each other)

A directed graph where nodes are **mechanics/patterns** and edges are **interactions**,
each grounded in a Comprehensive Rules citation. Examples:

- `deathtouch` + `trample` → assign 1 lethal damage, rest tramples over (CR 702.2c, 510.1d)
- `sacrifice-outlet` + `death-trigger` → repeatable value engine
- `untap-ability` + `tap-for-mana ≥ cost` → **infinite mana pattern**
- `doubling-effect` (Doubling Season) + `planeswalker` → ultimates on arrival (CR 616 replacement ordering)
- `lifelink` + `damage-doubler` → doubled lifegain
- `protection.board` vs `wipe.creature` → defensive counter-relationship

Edges are typed: `combos-with`, `amplifies`, `enables`, `protects-against`,
`nonbo` (anti-synergy — e.g. your own board wipes vs. your token strategy), and carry a
strength score. Built from three inputs: hand-curated seed graph (~200 highest-value
interactions), Commander Spellbook combo decomposition (combos are instances of these
patterns), and rules-text pattern mining.

**This graph is what lets Deck Weaver find synergies that aren't in any database** —
it reasons over patterns, so a brand-new card slots into existing interaction edges the
day its Oracle text is ingested.

## Layer 3: Strategy Archetypes & Defense Styles

Named strategy profiles that decks are matched against, each defining: required role
mix, key mechanics, typical curve, win path, weaknesses, and how it defends itself.

**Seed archetypes (v1):** Aristocrats, Token Swarm ("go wide"), Voltron ("go tall"),
Spellslinger, Landfall/Lands-matter, Reanimator/Graveyard, Blink/Flicker, +1/+1 Counters,
Artifacts-matter, Enchantress, Tribal/Typal, Group Hug/Politics, Stax/Control,
Combo-focused, Big Mana/Stompy, Wheels, Theft, Mill, Lifegain, Superfriends.

**Defense-style profiles** capture *how a deck survives*: Fortress (pillow-fort +
board wipes), Speed (win before they do), Resilience (recursion + protection stack),
Deterrence (punish attackers), Political (make attacking you a bad deal), Evasive
Refill (hold up counterspells + rebuild fast). Every deck analysis reports the deck's
dominant defense style and its blind spots ("nothing beats a resolved Craterhoof —
you have zero fog/flash blockers").

---

## The Numbers Layer (deck math)

Understanding also means math. The analysis engine computes:

- **Mana base correctness** — colored-source counts vs. pip requirements (Frank Karsten
  tables), land count vs. curve and draw density
- **Hypergeometric consistency** — P(playable opener), P(land drops through turn 4),
  P(finding a combo piece by turn N with your tutor/draw count)
- **Role coverage vs. benchmark** — compared against bracket-appropriate templates
  (e.g. bracket 3 baseline: ~10 ramp, ~10 draw, ~8 spot removal, ~3 wipes, ~35–38 lands,
  clear wincons) with archetype-specific adjustments
- **Curve & speed metrics** — average mana value, expected turn of first meaningful play,
  goldfish-win-turn estimate for combo lines
- **Bracket estimation** — Game Changer count, tutor density, fast-mana count, combo
  presence/earliness → estimated bracket 1–5, so "lethal" is tuned to the table you
  actually play at
