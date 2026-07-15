#!/usr/bin/env python3
"""Seed a small DEMO knowledge base so the app can be tried without a network
download. Produces data/demo/weaver-demo.db from a curated set of iconic
Commander staples (real names + Oracle text), then runs the role tagger and adds
a couple of known combos.

Usage:
    python scripts/seed_demo.py
    weaver --db data/demo/weaver-demo.db serve      # then open http://127.0.0.1:8000

This is a *demo*, not the full card pool. For all ~30,000 cards (and a deck
builder with a real pool), run `weaver update` instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weaver.db.connection import connect            # noqa: E402
from weaver.db.schema import apply_schema            # noqa: E402
from weaver.knowledge.tagger import run_tagging      # noqa: E402

# (name, mana_cost, mv, type_line, oracle_text, color_identity, edhrec_rank, price, game_changer)
CARDS = [
    # --- mana ---
    ("Sol Ring", "{1}", 1, "Artifact", "{T}: Add {C}{C}.", [], 1, 1.35, 0),
    ("Arcane Signet", "{2}", 2, "Artifact", "{T}: Add one mana of any color in your commander's color identity.", [], 2, 1.0, 0),
    ("Command Tower", "", 0, "Land", "{T}: Add one mana of any color in your commander's color identity.", [], 3, 0.3, 0),
    ("Cultivate", "{2}{G}", 3, "Sorcery", "Search your library for up to two basic land cards, reveal those cards, and put one onto the battlefield tapped and the other into your hand. Then shuffle.", ["G"], 40, 0.25, 0),
    ("Kodama's Reach", "{2}{G}", 3, "Sorcery", "Search your library for up to two basic land cards, reveal them, put one onto the battlefield tapped and the other into your hand, then shuffle.", ["G"], 60, 0.5, 0),
    ("Rampant Growth", "{1}{G}", 2, "Sorcery", "Search your library for a basic land card, put it onto the battlefield tapped, then shuffle.", ["G"], 120, 0.4, 0),
    ("Llanowar Elves", "{G}", 1, "Creature — Elf Druid", "{T}: Add {G}.", ["G"], 90, 0.25, 0),
    ("Birds of Paradise", "{G}", 1, "Creature — Bird", "Flying\n{T}: Add one mana of any color.", ["G"], 55, 6.0, 0),
    ("Golgari Signet", "{2}", 2, "Artifact", "{1}, {T}: Add {B}{G}.", ["B", "G"], 80, 1.0, 0),
    ("Mind Stone", "{2}", 2, "Artifact", "{T}: Add {C}.\n{1}, {T}, Sacrifice Mind Stone: Draw a card.", [], 70, 0.5, 0),
    # --- card advantage ---
    ("Rhystic Study", "{2}{U}", 3, "Enchantment", "Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.", ["U"], 28, 32.5, 1),
    ("Phyrexian Arena", "{1}{B}{B}", 3, "Enchantment", "At the beginning of your upkeep, you draw a card and you lose 1 life.", ["B"], 45, 4.0, 0),
    ("Night's Whisper", "{1}{B}", 2, "Sorcery", "You draw two cards and you lose 2 life.", ["B"], 65, 1.5, 0),
    ("Sign in Blood", "{B}{B}", 2, "Sorcery", "Target player draws two cards and loses 2 life.", ["B"], 110, 0.3, 0),
    ("Harmonize", "{2}{G}{G}", 4, "Sorcery", "Draw three cards.", ["G"], 150, 0.5, 0),
    ("Guardian Project", "{3}{G}", 4, "Enchantment", "Whenever a nontoken creature enters the battlefield under your control, if it doesn't have the same name as another creature you control or in your graveyard, draw a card.", ["G"], 130, 2.0, 0),
    # --- removal ---
    ("Swords to Plowshares", "{W}", 1, "Instant", "Exile target creature. Its controller gains life equal to its power.", ["W"], 15, 3.0, 0),
    ("Path to Exile", "{W}", 1, "Instant", "Exile target creature. Its controller may search their library for a basic land card, put it onto the battlefield tapped, then shuffle.", ["W"], 22, 4.0, 0),
    ("Beast Within", "{2}{G}", 3, "Instant", "Destroy target permanent. Its controller creates a 3/3 green Beast creature token.", ["G"], 35, 1.5, 0),
    ("Chaos Warp", "{2}{R}", 3, "Instant", "The owner of target permanent shuffles it into their library, then reveals the top card of their library. If it's a permanent card, they put it onto the battlefield.", ["R"], 30, 1.5, 0),
    ("Go for the Throat", "{1}{B}", 2, "Instant", "Destroy target nonartifact creature.", ["B"], 25, 2.0, 0),
    ("Assassin's Trophy", "{B}{G}", 2, "Instant", "Destroy target permanent an opponent controls. Its controller may search their library for a basic land card, put it onto the battlefield, then shuffle.", ["B", "G"], 33, 3.0, 0),
    ("Putrefy", "{1}{B}{G}", 3, "Instant", "Destroy target artifact or creature. It can't be regenerated.", ["B", "G"], 90, 1.0, 0),
    ("Generous Gift", "{2}{W}", 3, "Instant", "Destroy target permanent. Its controller creates a 3/3 green Elephant creature token.", ["W"], 26, 3.0, 0),
    # --- wipes ---
    ("Wrath of God", "{2}{W}{W}", 4, "Sorcery", "Destroy all creatures. They can't be regenerated.", ["W"], 50, 6.0, 0),
    ("Damnation", "{2}{B}{B}", 4, "Sorcery", "Destroy all creatures. They can't be regenerated.", ["B"], 75, 15.0, 0),
    ("Blasphemous Act", "{8}{R}", 9, "Sorcery", "This spell costs {1} less to cast for each creature on the battlefield.\nBlasphemous Act deals 13 damage to each creature.", ["R"], 40, 2.0, 0),
    ("Toxic Deluge", "{2}{B}", 3, "Sorcery", "As an additional cost to cast this spell, pay X life. All creatures get -X/-X until end of turn.", ["B"], 44, 25.0, 1),
    # --- counters ---
    ("Counterspell", "{U}{U}", 2, "Instant", "Counter target spell.", ["U"], 20, 2.0, 0),
    ("Swan Song", "{U}", 1, "Instant", "Counter target enchantment, instant, or sorcery spell. Its controller creates a 2/2 blue Bird creature token.", ["U"], 24, 3.0, 0),
    ("Negate", "{1}{U}", 2, "Instant", "Counter target noncreature spell.", ["U"], 95, 0.25, 0),
    # --- aristocrats ---
    ("Blood Artist", "{1}{B}", 2, "Creature — Vampire", "Whenever Blood Artist or another creature dies, target player loses 1 life and you gain 1 life.", ["B"], 85, 2.0, 0),
    ("Zulaport Cutthroat", "{1}{B}", 2, "Creature — Human Rogue Ally", "Whenever Zulaport Cutthroat or another creature you control dies, each opponent loses 1 life and you gain 1 life.", ["B"], 100, 3.0, 0),
    ("Viscera Seer", "{B}", 1, "Creature — Vampire Wizard", "Sacrifice a creature: Scry 1.", ["B"], 140, 0.25, 0),
    ("Ashnod's Altar", "{3}", 3, "Artifact", "Sacrifice a creature: Add {C}{C}.", [], 88, 6.0, 0),
    ("Grave Pact", "{2}{B}{B}", 4, "Enchantment", "Whenever a creature you control dies, each other player sacrifices a creature.", ["B"], 105, 5.0, 0),
    ("Dictate of Erebos", "{3}{B}{B}", 5, "Enchantment", "Flash\nWhenever a creature you control dies, each opponent sacrifices a creature.", ["B"], 115, 4.0, 0),
    ("Midnight Reaper", "{2}{B}", 3, "Creature — Zombie Knight", "Whenever a nontoken creature you control dies, Midnight Reaper deals 1 damage to you and you draw a card.", ["B"], 95, 3.0, 0),
    # --- tokens / go wide ---
    ("Bitterblossom", "{1}{B}", 2, "Enchantment", "At the beginning of your upkeep, you lose 1 life and create a 1/1 black Faerie Rogue creature token with flying.", ["B"], 120, 12.0, 0),
    ("Grave Titan", "{4}{B}{B}", 6, "Creature — Giant", "Deathtouch\nWhenever Grave Titan enters the battlefield or attacks, create two 2/2 black Zombie creature tokens.", ["B"], 70, 8.0, 0),
    ("Cathars' Crusade", "{3}{W}{W}", 5, "Enchantment", "Whenever a creature enters the battlefield under your control, put a +1/+1 counter on each creature you control.", ["W"], 200, 6.0, 0),
    # --- recursion / graveyard ---
    ("Eternal Witness", "{1}{G}{G}", 3, "Creature — Human Shaman", "When Eternal Witness enters the battlefield, return target card from your graveyard to your hand.", ["G"], 48, 1.0, 0),
    ("Reanimate", "{B}", 1, "Sorcery", "Put target creature card from a graveyard onto the battlefield under your control. You lose life equal to its mana value.", ["B"], 42, 12.0, 0),
    ("Regrowth", "{1}{G}", 2, "Sorcery", "Return target card from your graveyard to your hand.", ["G"], 160, 1.0, 0),
    ("Buried Alive", "{1}{B}", 2, "Sorcery", "Search your library for up to three creature cards and put them into your graveyard, then shuffle.", ["B"], 220, 2.0, 0),
    # --- protection ---
    ("Heroic Intervention", "{1}{G}", 2, "Instant", "Permanents you control gain hexproof and indestructible until end of turn.", ["G"], 38, 4.0, 0),
    ("Teferi's Protection", "{2}{W}", 3, "Instant", "Until your next turn, your life total can't change, you gain protection from everything, and all permanents you control phase out.", ["W"], 32, 20.0, 1),
    ("Lightning Greaves", "{2}", 2, "Artifact — Equipment", "Equipped creature has haste and shroud.\nEquip {0}", [], 18, 3.0, 0),
    ("Swiftfoot Boots", "{2}", 2, "Artifact — Equipment", "Equipped creature has hexproof and haste.\nEquip {1}", [], 21, 1.0, 0),
    # --- wincons ---
    ("Craterhoof Behemoth", "{5}{G}{G}{G}", 8, "Creature — Beast", "Haste\nWhen Craterhoof Behemoth enters the battlefield, creatures you control gain trample and get +X/+X until end of turn, where X is the number of creatures you control.", ["G"], 60, 30.0, 0),
    ("Overwhelming Stampede", "{3}{G}{G}", 5, "Sorcery", "Until end of turn, creatures you control gain trample and get +X/+X, where X is the greatest power among creatures you control.", ["G"], 300, 1.0, 0),
    ("Torment of Hailfire", "{X}{B}{B}{B}", 3, "Sorcery", "Repeat the following process X times. Each opponent loses 3 life unless that player sacrifices a nonland permanent or discards a card.", ["B"], 80, 5.0, 0),
    # --- tutors ---
    ("Demonic Tutor", "{1}{B}", 2, "Sorcery", "Search your library for a card, put that card into your hand, then shuffle.", ["B"], 12, 30.0, 1),
    ("Vampiric Tutor", "{B}", 1, "Instant", "Search your library for a card, then shuffle and put that card on top. You lose 2 life.", ["B"], 14, 35.0, 1),
    ("Worldly Tutor", "{G}", 1, "Instant", "Search your library for a creature card, reveal it, then shuffle and put that card on top.", ["G"], 130, 8.0, 0),
    # --- combo pieces (for the combo demo) ---
    ("Mikaeus, the Unhallowed", "{3}{B}{B}{B}", 6, "Legendary Creature — Zombie Cleric", "Intimidate\nOther non-Human creatures you control get +1/+1 and have undying.\nHuman creatures you control get -1/-1.", ["B"], 150, 20.0, 0),
    ("Walking Ballista", "{X}{X}", 0, "Artifact Creature — Construct", "Walking Ballista enters the battlefield with X +1/+1 counters on it.\n{4}: Put a +1/+1 counter on Walking Ballista.\nRemove a +1/+1 counter from Walking Ballista: It deals 1 damage to any target.", [], 25, 8.0, 0),
    # --- commanders ---
    ("Meren of Clan Nel Toth", "{2}{B}{G}", 4, "Legendary Creature — Human Shaman", "Whenever another creature you control dies, you get an experience counter. At the beginning of your end step, return target creature card with mana value X or less from your graveyard to the battlefield, where X is the number of experience counters you have.", ["B", "G"], 120, 4.0, 0),
    ("Atraxa, Praetors' Voice", "{G}{W}{U}{B}", 4, "Legendary Creature — Phyrexian Angel Horror", "Flying, vigilance, deathtouch, lifelink\nAt the beginning of your end step, proliferate.", ["G", "W", "U", "B"], 34, 18.0, 0),
    ("Prossh, Skyraider of Kher", "{4}{B}{R}{G}", 7, "Legendary Creature — Dragon", "When you cast Prossh, create X 0/1 red Kobold creature tokens, where X is the amount of mana spent to cast it.\nFlying\nSacrifice another creature: Prossh gets +1/+1 until end of turn.", ["B", "R", "G"], 210, 3.0, 0),
    # --- lands ---
    ("Overgrown Tomb", "", 0, "Land — Swamp Forest", "({T}: Add {B} or {G}.) As Overgrown Tomb enters the battlefield, you may pay 2 life. If you don't, it enters tapped.", ["B", "G"], 300, 12.0, 0),
    ("Bojuka Bog", "", 0, "Land", "Bojuka Bog enters the battlefield tapped. When Bojuka Bog enters, exile target player's graveyard.", ["B"], 320, 0.5, 0),
    ("Rogue's Passage", "", 0, "Land", "{T}: Add {C}.\n{4}, {T}: Target creature can't be blocked this turn.", [], 250, 1.0, 0),
]

BASICS = [("Plains", "W"), ("Island", "U"), ("Swamp", "B"), ("Mountain", "R"), ("Forest", "G")]

# (id, [card names], produces, color_identity)
COMBOS = [
    ("demo-mike-ballista", ["Mikaeus, the Unhallowed", "Walking Ballista"],
     ["Infinite damage"], ["B"]),
]


def main() -> None:
    out = ROOT / "data" / "demo" / "weaver-demo.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    conn = connect(out)
    apply_schema(conn)

    for i, (name, mc, mv, tl, txt, ci, rank, price, gc) in enumerate(CARDS):
        conn.execute(
            "INSERT INTO cards(oracle_id,name,mana_cost,mana_value,type_line,oracle_text,"
            "color_identity,legal_commander,is_game_changer,edhrec_rank,price_usd)"
            " VALUES(?,?,?,?,?,?,?,'legal',?,?,?)",
            (f"demo-{i}", name, mc, mv, tl, txt, json.dumps(ci), gc, rank, price),
        )
    for b, c in BASICS:
        conn.execute(
            "INSERT INTO cards(oracle_id,name,mana_cost,mana_value,type_line,oracle_text,"
            "color_identity,legal_commander,is_game_changer) VALUES(?,?,'',0,?,?,?,'legal',0)",
            (f"basic-{b}", b, f"Basic Land — {b}", f"({{T}}: Add {{{c}}}.)", json.dumps([c])),
        )

    for cid, names, produces, ci in COMBOS:
        conn.execute(
            "INSERT INTO combos(id,description,produces,color_identity,spellbook_uri) VALUES(?,?,?,?,?)",
            (cid, " + ".join(names), json.dumps(produces), json.dumps(ci),
             f"https://commanderspellbook.com/combo/{cid}/"),
        )
        for n in names:
            conn.execute(
                "INSERT INTO combo_cards(combo_id,card_name,quantity,must_be_commander) VALUES(?,?,1,0)",
                (cid, n),
            )

    conn.commit()
    run_tagging(conn)
    conn.commit()

    cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    tags = conn.execute("SELECT COUNT(*) FROM card_tags").fetchone()[0]
    print(f"seeded {out.relative_to(ROOT)}: {cards} cards, {tags} role tags, {len(COMBOS)} combo(s)")
    print("try it:  weaver --db data/demo/weaver-demo.db serve")


if __name__ == "__main__":
    main()
