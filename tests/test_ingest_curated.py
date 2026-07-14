"""Offline tests for the curated ingester (brackets + Game Changers).

Uses the real repo data/curated/*.json files via the curated_dir override,
so tests pass regardless of the working directory pytest runs from.
"""

import json
import shutil
from pathlib import Path

import pytest

from weaver.ingest import curated

REPO_CURATED = Path(__file__).resolve().parent.parent / "data" / "curated"


def _quiet(_msg: str) -> None:
    pass


def _run(db, cache_dir, curated_dir=REPO_CURATED):
    return curated.ingest(db, cache_dir, progress=_quiet, curated_dir=curated_dir)


def _gc_json():
    with open(REPO_CURATED / "game_changers.json", encoding="utf-8") as fh:
        return json.load(fh)


def test_brackets_loaded(db, cache_dir):
    _run(db, cache_dir)
    rows = db.execute(
        "SELECT number, name, game_changer_limit FROM brackets ORDER BY number"
    ).fetchall()
    assert len(rows) == 5
    assert [r["number"] for r in rows] == [1, 2, 3, 4, 5]
    assert [r["game_changer_limit"] for r in rows] == [0, 0, 3, None, None]
    assert all(r["name"] for r in rows)


def test_game_changers_match_json_count(db, cache_dir):
    doc = _gc_json()
    assert doc["count"] == 53
    result = _run(db, cache_dir)
    n = db.execute("SELECT COUNT(*) FROM game_changers").fetchone()[0]
    assert n == doc["count"] == 53
    assert result.rows == 5 + 53
    # cards table is empty, so no unmatched-names warning
    assert result.warnings == []


@pytest.mark.parametrize(
    "name", ["Rhystic Study", "Demonic Tutor", "Farewell", "Biorhythm"]
)
def test_spot_check_cards_present(db, cache_dir, name):
    _run(db, cache_dir)
    row = db.execute(
        "SELECT source FROM game_changers WHERE name = ?", (name,)
    ).fetchone()
    assert row is not None
    assert row["source"] == "wotc-2026-02-09"


def test_reconciles_cards_flag(db, cache_dir):
    db.execute(
        "INSERT INTO cards(oracle_id, name, is_game_changer) VALUES(?, ?, 0)",
        ("00000000-0000-0000-0000-000000000001", "Farewell"),
    )
    db.execute(
        "INSERT INTO cards(oracle_id, name, is_game_changer) VALUES(?, ?, 0)",
        ("00000000-0000-0000-0000-000000000002", "Grizzly Bears"),
    )
    result = _run(db, cache_dir)
    flag = db.execute(
        "SELECT is_game_changer FROM cards WHERE name = 'Farewell'"
    ).fetchone()[0]
    assert flag == 1
    # Non-Game-Changer card is left alone.
    other = db.execute(
        "SELECT is_game_changer FROM cards WHERE name = 'Grizzly Bears'"
    ).fetchone()[0]
    assert other == 0
    # cards table is non-empty and 52 curated names have no cards row.
    assert len(result.warnings) == 1
    assert "52" in result.warnings[0]


def test_rerun_does_not_duplicate(db, cache_dir):
    _run(db, cache_dir)
    _run(db, cache_dir)
    assert db.execute("SELECT COUNT(*) FROM game_changers").fetchone()[0] == 53
    assert db.execute("SELECT COUNT(*) FROM brackets").fetchone()[0] == 5


def test_count_mismatch_raises(db, cache_dir, tmp_path):
    doctored = tmp_path / "curated"
    doctored.mkdir()
    shutil.copy(REPO_CURATED / "brackets.json", doctored / "brackets.json")
    doc = _gc_json()
    doc["count"] = doc["count"] + 1  # now inconsistent with len(cards)
    (doctored / "game_changers.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        _run(db, cache_dir, curated_dir=doctored)
