"""Multi-face (DFC/split) card resolution: a combined "A // B" name resolves
whether the DB stores the full name or a single face, in both the deck loader
and the /api/card endpoint. Regression for "card data not available" on cards
like 'Bilbo, Luckwearer // Burglar's Plot'.
"""

from __future__ import annotations

import json

import pytest

from weaver.analysis.loader import _resolve_row, load_deck
from weaver.db.connection import connect
from weaver.db.schema import apply_schema

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from weaver.web.app import create_app  # noqa: E402


def _add(conn, name, games=("paper",)):
    conn.execute(
        "INSERT INTO cards(oracle_id,name,type_line,color_identity,games,"
        "legal_commander,is_game_changer,edhrec_rank,mana_value) VALUES"
        "(?,?,'Legendary Creature','[\"G\"]',?,'legal',0,100,3)",
        (name, name, json.dumps(list(games))),
    )


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "cards.db"
    conn = connect(p)
    apply_schema(conn)
    _add(conn, "Bilbo, Luckwearer // Burglar's Plot")  # stored as the full name
    _add(conn, "Front Only", games=("arena",))          # stored as a single face
    conn.commit()
    conn.close()
    return p


def test_resolve_full_and_each_face(db_path):
    conn = connect(db_path)
    full = "Bilbo, Luckwearer // Burglar's Plot"
    assert _resolve_row(conn, full)["name"] == full
    assert _resolve_row(conn, "Bilbo, Luckwearer")["name"] == full   # front half
    assert _resolve_row(conn, "Burglar's Plot")["name"] == full       # back half
    # A combined name whose card the DB stores under one face resolves to it.
    assert _resolve_row(conn, "Front Only // Imagined Back")["name"] == "Front Only"
    conn.close()


def test_loader_resolves_and_flags_arena(db_path):
    conn = connect(db_path)
    deck = load_deck(conn, "Deck\n1 Bilbo, Luckwearer // Burglar's Plot\n")
    card = deck.cards[0]
    assert card.resolved
    assert card.on_arena is False   # not on Arena -> off-Arena tools can flag it
    conn.close()


def test_unresolved_diagnostics(db_path):
    conn = connect(db_path)
    # Front Only exists -> a small typo should suggest it; a nonsense name won't.
    deck = load_deck(conn, "Deck\n1 Front Onlyx\n1 Totally Nonexistent Xyzzy\n")
    detail = {d["name"]: d for d in deck.unresolved_detail}
    assert detail["Front Onlyx"]["suggestion"] == "Front Only"       # first-word fallback
    assert "closest match" in detail["Front Onlyx"]["reason"]
    assert detail["Totally Nonexistent Xyzzy"]["suggestion"] is None
    assert "not in the card database" in detail["Totally Nonexistent Xyzzy"]["reason"]
    conn.close()


def test_unresolved_multiface_reason(db_path):
    conn = connect(db_path)
    deck = load_deck(conn, "Deck\n1 Made Up Front // Made Up Back\n")
    d = deck.unresolved_detail[0]
    assert d["suggestion"] is None
    assert "multi-face" in d["reason"]
    conn.close()


def test_payload_includes_unresolved_detail(db_path, tmp_path):
    client = TestClient(create_app(str(db_path), decks_db_path=str(tmp_path / "d.db")))
    r = client.post("/api/analyze", json={"decklist": "Deck\n1 Front Onlyx\n"})
    assert r.status_code == 200
    detail = r.json()["unresolved_detail"]
    assert detail and detail[0]["name"] == "Front Onlyx" and detail[0]["suggestion"] == "Front Only"


def test_api_card_resolves_combined_name(db_path, tmp_path):
    client = TestClient(create_app(str(db_path), decks_db_path=str(tmp_path / "d.db")))
    # Query-param form handles the "//" in the name (a path segment can't).
    r = client.get("/api/card", params={"name": "Bilbo, Luckwearer // Burglar's Plot"})
    assert r.status_code == 200
    assert r.json()["name"] == "Bilbo, Luckwearer // Burglar's Plot"
    # And by a single face.
    r2 = client.get("/api/card", params={"name": "Bilbo, Luckwearer"})
    assert r2.status_code == 200
    assert r2.json()["name"] == "Bilbo, Luckwearer // Burglar's Plot"
