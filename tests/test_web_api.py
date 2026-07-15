"""Web API tests: exercise every endpoint through FastAPI's TestClient against
a small seeded database. No network; no running server needed."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from weaver.db.connection import connect  # noqa: E402
from weaver.db.schema import apply_schema  # noqa: E402
from weaver.knowledge.tagger import run_tagging  # noqa: E402
from weaver.web.app import create_app  # noqa: E402

CARDS = [
    ("c1", "Tovolar, Dire Overlord", "{1}{R}{G}", 3, "Legendary Creature — Human Werewolf",
     "Whenever a Wolf or Werewolf you control deals combat damage to a player, draw a card.", ["R", "G"]),
    ("c2", "Sol Ring", "{1}", 1, "Artifact", "{T}: Add {C}{C}.", []),
    ("c3", "Lightning Bolt", "{R}", 1, "Instant", "Lightning Bolt deals 3 damage to any target.", ["R"]),
    ("c4", "Cultivate", "{2}{G}", 3, "Sorcery",
     "Search your library for up to two basic land cards, reveal those cards, and put one onto the battlefield tapped and the other into your hand. Then shuffle.", ["G"]),
    ("c5", "Forest", "", 0, "Basic Land — Forest", "({T}: Add {G}.)", ["G"]),
    ("c6", "Mountain", "", 0, "Basic Land — Mountain", "({T}: Add {R}.)", ["R"]),
]


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "web.db"
    conn = connect(db_path)
    apply_schema(conn)
    for oid, name, mc, mv, tl, txt, ci in CARDS:
        conn.execute(
            "INSERT INTO cards(oracle_id,name,mana_cost,mana_value,type_line,oracle_text,"
            "color_identity,legal_commander,is_game_changer,edhrec_rank) VALUES(?,?,?,?,?,?,?,'legal',0,10)",
            (oid, name, mc, mv, tl, txt, json.dumps(ci)),
        )
    conn.commit()
    run_tagging(conn)
    conn.commit()
    conn.close()
    return TestClient(create_app(str(db_path)))


def test_stats(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.json()["counts"]["cards"] == len(CARDS)


def test_card_lookup(client):
    r = client.get("/api/card/Sol Ring")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Sol Ring"
    assert any(role["tag"] == "ramp.rock" for role in body["roles"])
    # card view includes a Scryfall image URL (loaded client-side)
    assert "image_url" in body and body["image_url"].startswith("https://api.scryfall.com/")
    assert "Sol%20Ring" in body["image_url"] or "format=image" in body["image_url"]


def test_card_fuzzy_and_404(client):
    assert client.get("/api/card/Cultiv").json()["name"] == "Cultivate"
    assert client.get("/api/card/Nonexistent Zzz").status_code == 404


def test_search(client):
    names = client.get("/api/search", params={"q": "o"}).json()
    assert "Sol Ring" in names or "Tovolar, Dire Overlord" in names


def test_search_commander_filter_excludes_noncreatures():
    """The commander search must only return commander-eligible cards —
    legendary creatures, not lands/enchantments/artifacts."""
    import json as _json
    from weaver.db.connection import connect
    from weaver.db.schema import apply_schema

    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "c.db"
    conn = connect(tmp)
    apply_schema(conn)
    rows = [
        ("k1", "Krenko, Mob Boss", "Legendary Creature — Goblin Warrior", []),
        ("k2", "Sol Ring", "Artifact", []),
        ("k3", "Rhystic Study", "Enchantment", ["U"]),
        ("k4", "Command Tower", "Land", []),
        ("k5", "Kytheon, Hero of Akros", "Legendary Creature — Human Soldier", ["W"]),
    ]
    for oid, name, tl, ci in rows:
        conn.execute(
            "INSERT INTO cards(oracle_id,name,type_line,mana_value,color_identity,"
            "legal_commander,is_game_changer) VALUES(?,?,?,0,?,'legal',0)",
            (oid, name, tl, _json.dumps(ci)),
        )
    conn.commit()
    conn.close()
    c = TestClient(create_app(str(tmp)))

    # generic search returns everything matching
    allk = c.get("/api/search", params={"q": "o"}).json()
    assert "Sol Ring" in allk and "Command Tower" in allk

    # commander search excludes the artifact/enchantment/land
    cmd = c.get("/api/search", params={"q": "o", "kind": "commander"}).json()
    assert "Krenko, Mob Boss" in cmd
    assert "Sol Ring" not in cmd
    assert "Rhystic Study" not in cmd
    assert "Command Tower" not in cmd


def test_analyze(client):
    decklist = "Commander\n1 Tovolar, Dire Overlord\nDeck\n1 Sol Ring\n1 Lightning Bolt\n30 Forest\n30 Mountain\n"
    r = client.post("/api/analyze", json={"decklist": decklist})
    assert r.status_code == 200
    body = r.json()
    titles = [s["title"] for s in body["sections"]]
    assert "Legality & Bracket" in titles and "Mana Base" in titles
    # markup was stripped
    assert all("[" not in f["message"] for s in body["sections"] for f in s["findings"])


def test_build(client):
    r = client.post("/api/build", json={"commander": "Tovolar, Dire Overlord", "bracket": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["commander"] == "Tovolar, Dire Overlord"
    assert "decklist" in body and body["decklist"].startswith("Commander")
    assert "validation" in body  # self-validated
    # groups + lands present
    assert isinstance(body["groups"], list)
    assert body["land_count"] > 0


def test_build_unknown_commander_404(client):
    r = client.post("/api/build", json={"commander": "Not A Commander", "bracket": 3})
    assert r.status_code == 404


def test_archetypes_endpoint(client):
    arch = client.get("/api/archetypes").json()
    assert any(a["key"] == "aristocrats" for a in arch)


def test_splash_routes(client):
    # both the landscape and mobile-portrait splash images are served
    assert client.get("/splash.png").status_code == 200
    assert client.get("/splash-portrait.png").status_code == 200
