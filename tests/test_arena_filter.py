"""Arena-legal build filter + the games-column migration."""

from __future__ import annotations

import json

from weaver.build.builder import build_deck
from weaver.build.pool import build_pool
from weaver.build.types import BuildRequest
from weaver.db.connection import connect
from weaver.db.schema import apply_schema


def _seed(conn):
    apply_schema(conn)
    # commander (on arena) + two nonlands, one arena one not + basics
    rows = [
        ("cmd", "Test Commander", "Legendary Creature — Elf", ["G"], ["paper", "mtgo", "arena"], 3),
        ("a1", "Arena Ramp", "Artifact", [], ["paper", "arena"], 3),
        ("p1", "Paper Only Ramp", "Artifact", [], ["paper", "mtgo"], 3),
        ("fo", "Forest", "Basic Land — Forest", ["G"], ["paper", "mtgo", "arena"], 0),
    ]
    for oid, name, tl, ci, games, mv in rows:
        conn.execute(
            "INSERT INTO cards(oracle_id,name,mana_cost,mana_value,type_line,oracle_text,"
            "color_identity,legal_commander,is_game_changer,games) VALUES(?,?,'',?,?,'',?,'legal',0,?)",
            (oid, name, mv, tl, json.dumps(ci), json.dumps(games)),
        )
        if oid in ("a1", "p1"):
            conn.execute("INSERT INTO card_tags(oracle_id,tag,quality,source) VALUES(?,'ramp.rock',0.8,'pattern')", (oid,))
    conn.commit()


def test_migration_adds_games_column(tmp_path):
    # An existing cards table missing the games column gets it back-filled.
    from weaver.db.schema import _migrate_columns

    conn = connect(tmp_path / "old.db")
    conn.execute("CREATE TABLE cards (oracle_id TEXT PRIMARY KEY, name TEXT)")
    conn.commit()
    assert "games" not in {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
    _migrate_columns(conn)
    assert "games" in {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
    # idempotent: running again doesn't error
    _migrate_columns(conn)


def test_arena_filter_excludes_non_arena(tmp_path):
    conn = connect(tmp_path / "a.db")
    _seed(conn)
    # without the filter, both ramp pieces are in the pool
    _, _, pool = build_pool(conn, BuildRequest(commander="Test Commander"))
    names = {c.name for c in pool}
    assert "Arena Ramp" in names and "Paper Only Ramp" in names
    # with arena_only, the paper-only card is filtered out
    _, _, pool_a = build_pool(conn, BuildRequest(commander="Test Commander", arena_only=True))
    names_a = {c.name for c in pool_a}
    assert "Arena Ramp" in names_a
    assert "Paper Only Ramp" not in names_a


def test_arena_build_notes(tmp_path):
    conn = connect(tmp_path / "b.db")
    _seed(conn)
    result = build_deck(conn, BuildRequest(commander="Test Commander", arena_only=True, bracket=3))
    assert any("Arena-only" in n for n in result.notes)


def test_non_arena_commander_warns(tmp_path):
    conn = connect(tmp_path / "c.db")
    _seed(conn)
    # make a paper-only commander
    conn.execute(
        "INSERT INTO cards(oracle_id,name,mana_value,type_line,color_identity,legal_commander,is_game_changer,games)"
        " VALUES('pc','Paper Legend',3,'Legendary Creature — Elf','[\"G\"]','legal',0,?)",
        (json.dumps(["paper", "mtgo"]),),
    )
    conn.commit()
    result = build_deck(conn, BuildRequest(commander="Paper Legend", arena_only=True))
    assert any("isn't on MTG Arena" in n for n in result.notes)
