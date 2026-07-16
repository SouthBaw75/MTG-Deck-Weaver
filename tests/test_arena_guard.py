"""Arena legality guards: the curated override (games-data can be overruled)
and the build-time verify/replace pass that keeps Arena builds importable.
"""

from __future__ import annotations

import json

import pytest

import weaver.knowledge.arena as arena
from weaver.build.builder import _enforce_arena
from weaver.build.pool import build_pool
from weaver.build.types import BuildRequest, BuildResult, Candidate, SlotAssignment
from weaver.db.connection import connect
from weaver.db.schema import apply_schema
from weaver.knowledge.arena import is_on_arena
from weaver.knowledge.cardview import CardView


# ---- curated override ------------------------------------------------------
def test_override_beats_games_data(monkeypatch):
    monkeypatch.setattr(arena, "_cache",
                        {"not": frozenset({"card x"}), "on": frozenset({"card y"})})
    assert is_on_arena("Card X", '["arena","paper"]') is False   # forced off
    assert is_on_arena("Card Y", '["paper"]') is True            # forced on
    assert is_on_arena("Card Z", '["arena"]') is True            # falls back to games
    assert is_on_arena("Card Z", '["paper"]') is False


def test_shipped_override_excludes_bilbo():
    arena.reload_overrides()
    assert is_on_arena("Bilbo, Luckwearer // Burglar's Plot", '["arena","paper"]') is False


# ---- pool excludes an override-illegal card even if games says Arena --------
def _add(conn, oid, name, games, ci=("B",), tl="Creature", txt="x"):
    conn.execute(
        "INSERT INTO cards(oracle_id,name,type_line,oracle_text,color_identity,games,"
        "legal_commander,is_game_changer,edhrec_rank,mana_value) VALUES(?,?,?,?,?,?,'legal',0,10,2)",
        (oid, name, tl, txt, json.dumps(list(ci)), json.dumps(list(games))),
    )


def test_pool_excludes_override_card(tmp_path):
    arena.reload_overrides()
    conn = connect(tmp_path / "p.db")
    apply_schema(conn)
    _add(conn, "cmd", "Cmdr", ["arena"], tl="Legendary Creature")
    _add(conn, "bilbo", "Bilbo, Luckwearer // Burglar's Plot", ["arena", "paper"])  # games lies
    _add(conn, "ok", "Legit Card", ["arena"])
    conn.commit()
    _c, _p, pool = build_pool(conn, BuildRequest(commander="Cmdr", arena_only=True))
    names = {c.name for c in pool}
    assert "Legit Card" in names
    assert "Bilbo, Luckwearer // Burglar's Plot" not in names   # override overrules games


# ---- build-time verify swaps a planted off-Arena card ----------------------
def _cand(name, games, tags=None):
    return Candidate(
        name=name, oracle_id=name,
        card=CardView.from_dict({"name": name, "type_line": "Creature"}),
        tags=tags or {}, color_identity=["B"], mana_value=2.0, type_line="Creature",
        price_usd=None, edhrec_rank=1, is_game_changer=False, legal_commander="legal",
    )


def test_enforce_arena_swaps_off_arena_pick(tmp_path):
    arena.reload_overrides()
    conn = connect(tmp_path / "e.db")
    apply_schema(conn)
    _add(conn, "off", "Off Card", ["paper"], txt="removal")       # not on Arena
    _add(conn, "spare", "Legal Spare", ["arena"], txt="removal")  # arena, same role
    conn.commit()

    off = _cand("Off Card", ["paper"], tags={"removal.spot.creature": 1.0})
    spare = _cand("Legal Spare", ["arena"], tags={"removal.spot.creature": 1.0})
    spare.score = 5.0
    result = BuildResult(
        request=BuildRequest(commander="Cmdr", bracket=4, arena_only=True),
        commander=_cand("Cmdr", ["arena"]), partner=None,
        assignments=[SlotAssignment(off, "spot_removal", 1.0, "x")],
        lands=[], unfilled={},
    )
    swaps = _enforce_arena(conn, result, pool=[spare])
    assert swaps == [("Off Card", "Legal Spare")]
    assert result.assignments[0].candidate.name == "Legal Spare"


def test_enforce_arena_noop_when_all_legal(tmp_path):
    arena.reload_overrides()
    conn = connect(tmp_path / "n.db")
    apply_schema(conn)
    _add(conn, "a", "All Good", ["arena"])
    conn.commit()
    result = BuildResult(
        request=BuildRequest(commander="Cmdr", arena_only=True),
        commander=_cand("Cmdr", ["arena"]), partner=None,
        assignments=[SlotAssignment(_cand("All Good", ["arena"]), "synergy", 1.0, "x")],
        lands=[], unfilled={},
    )
    assert _enforce_arena(conn, result, pool=[]) == []
