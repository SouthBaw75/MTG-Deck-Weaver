"""Offline tests for the Scryfall bulk-data ingester."""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest

import weaver.ingest.scryfall as scryfall

FIXTURE_NAME = "scryfall_oracle_sample.jsonl"
BULK_UPDATED_AT = "2026-07-10T09:01:30.123Z"
JSONL_URI = "https://data.scryfall.io/oracle-cards/oracle-cards-20260710.jsonl.gz"

FAKE_BULK_LISTING = {
    "object": "list",
    "data": [
        {
            "object": "bulk_data",
            "type": "default_cards",
            "updated_at": "2026-07-10T09:30:00.000Z",
            "download_uri": "https://data.scryfall.io/default-cards/default-cards-20260710.json",
            "jsonl_download_uri": "https://data.scryfall.io/default-cards/default-cards-20260710.jsonl.gz",
        },
        {
            "object": "bulk_data",
            "type": "oracle_cards",
            "updated_at": BULK_UPDATED_AT,
            "download_uri": "https://data.scryfall.io/oracle-cards/oracle-cards-20260710.json",
            "jsonl_download_uri": JSONL_URI,
        },
    ],
}

# Layouts in the fixture that the ingester must skip.
SKIPPED_FIXTURE_LAYOUTS = {"token", "art_series"}


def _fixture_cards(fixtures_dir: Path) -> list[dict]:
    with open(fixtures_dir / FIXTURE_NAME, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture()
def patched_network(monkeypatch, fixtures_dir, cache_dir):
    """Route the ingester's network I/O to the local gzipped fixture."""
    calls = {"json": [], "download": []}

    def fake_http_get_json(url, *, params=None):
        calls["json"].append(url)
        assert url == scryfall.BULK_DATA_URL
        return FAKE_BULK_LISTING

    def fake_download_file(url, dest, *, force=False, progress=print):
        calls["download"].append(url)
        assert url == JSONL_URI
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(fixtures_dir / FIXTURE_NAME, "rb") as src, gzip.open(dest, "wb") as gz:
            shutil.copyfileobj(src, gz)
        return dest

    monkeypatch.setattr(scryfall, "http_get_json", fake_http_get_json)
    monkeypatch.setattr(scryfall, "download_file", fake_download_file)
    return calls


def _run(db, cache_dir):
    return scryfall.ingest(db, cache_dir, progress=lambda _msg: None)


def test_row_count_and_skipped_layouts(db, cache_dir, fixtures_dir, patched_network):
    cards = _fixture_cards(fixtures_dir)
    expected = [c for c in cards if c["layout"] not in SKIPPED_FIXTURE_LAYOUTS]
    assert len(cards) > len(expected), "fixture must contain skippable layouts"

    result = _run(db, cache_dir)

    assert result.name == "scryfall"
    assert result.rows == len(expected)
    count = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    assert count == len(expected)

    layouts = {r[0] for r in db.execute("SELECT DISTINCT layout FROM cards")}
    assert layouts.isdisjoint(SKIPPED_FIXTURE_LAYOUTS)
    absent = db.execute(
        "SELECT COUNT(*) FROM cards WHERE name IN (?, ?)",
        ("Soldier", "Llanowar Elves // Llanowar Elves"),
    ).fetchone()[0]
    assert absent == 0


def test_banned_and_game_changer_flags(db, cache_dir, patched_network):
    _run(db, cache_dir)

    lotus = db.execute(
        "SELECT legal_commander, reserved FROM cards WHERE name = ?",
        ("Black Lotus",),
    ).fetchone()
    assert lotus["legal_commander"] == "banned"
    assert lotus["reserved"] == 1

    rhystic = db.execute(
        "SELECT is_game_changer FROM cards WHERE name = ?", ("Rhystic Study",)
    ).fetchone()
    assert rhystic["is_game_changer"] == 1

    elves = db.execute(
        "SELECT is_game_changer, legal_commander FROM cards WHERE name = ?",
        ("Llanowar Elves",),
    ).fetchone()
    assert elves["is_game_changer"] == 0
    assert elves["legal_commander"] == "legal"


def test_mdfc_faces_text_and_color_union(db, cache_dir, patched_network):
    _run(db, cache_dir)

    row = db.execute(
        "SELECT oracle_text, card_faces, colors, mana_value FROM cards WHERE name = ?",
        ("Valki, God of Lies // Tibalt, Cosmic Impostor",),
    ).fetchone()

    assert "\n//\n" in row["oracle_text"]
    faces = json.loads(row["card_faces"])
    assert len(faces) == 2
    assert faces[0]["name"] == "Valki, God of Lies"
    assert faces[1]["loyalty"] == "5"
    # Union of face colors (["B"] and ["B","R"]) since top-level colors is absent.
    assert json.loads(row["colors"]) == ["B", "R"]
    assert row["mana_value"] == 2.0


def test_color_identity_round_trips(db, cache_dir, patched_network):
    _run(db, cache_dir)

    atraxa = db.execute(
        "SELECT color_identity, keywords FROM cards WHERE name = ?",
        ("Atraxa, Praetors' Voice",),
    ).fetchone()
    assert json.loads(atraxa["color_identity"]) == ["W", "U", "B", "G"]
    assert "Proliferate" in json.loads(atraxa["keywords"])

    forest = db.execute(
        "SELECT color_identity, produced_mana FROM cards WHERE name = ?",
        ("Forest",),
    ).fetchone()
    assert json.loads(forest["color_identity"]) == ["G"]
    assert json.loads(forest["produced_mana"]) == ["G"]


def test_fts_matches_oracle_text(db, cache_dir, patched_network):
    _run(db, cache_dir)

    names = {
        r[0]
        for r in db.execute(
            "SELECT name FROM cards_fts WHERE cards_fts MATCH 'proliferate'"
        )
    }
    assert "Atraxa, Praetors' Voice" in names

    names = {
        r[0]
        for r in db.execute(
            "SELECT name FROM cards_fts WHERE cards_fts MATCH 'rhystic'"
        )
    }
    assert "Rhystic Study" in names


def test_ingest_is_idempotent(db, cache_dir, patched_network):
    first = _run(db, cache_dir)
    second = _run(db, cache_dir)

    assert first.rows == second.rows
    count = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    assert count == first.rows

    dupes = db.execute(
        "SELECT name FROM cards GROUP BY oracle_id HAVING COUNT(*) > 1"
    ).fetchall()
    assert dupes == []

    # FTS index stays in sync after the second rebuild.
    fts_count = db.execute("SELECT COUNT(*) FROM cards_fts").fetchone()[0]
    assert fts_count == count


def test_meta_and_misc_columns(db, cache_dir, patched_network):
    _run(db, cache_dir)

    bulk = db.execute(
        "SELECT value FROM meta WHERE key = 'scryfall.bulk_updated_at'"
    ).fetchone()
    assert bulk[0] == BULK_UPDATED_AT
    updated = db.execute(
        "SELECT value FROM meta WHERE key = 'scryfall.updated_at'"
    ).fetchone()
    assert updated is not None and updated[0]

    liliana = db.execute(
        "SELECT loyalty FROM cards WHERE name = ?", ("Liliana of the Veil",)
    ).fetchone()
    assert liliana["loyalty"] == "3"

    battle = db.execute(
        "SELECT defense FROM cards WHERE name = ?",
        ("Invasion of Gobakhan // Lightshield Array",),
    ).fetchone()
    assert battle["defense"] == "3"

    split = db.execute(
        "SELECT oracle_text, colors FROM cards WHERE name = ?", ("Fire // Ice",)
    ).fetchone()
    assert "\n//\n" in split["oracle_text"]
    assert json.loads(split["colors"]) == ["U", "R"]  # top-level colors kept as-is

    rhystic = db.execute(
        "SELECT price_usd, price_usd_foil FROM cards WHERE name = ?",
        ("Rhystic Study",),
    ).fetchone()
    assert rhystic["price_usd"] == pytest.approx(32.50)
    assert rhystic["price_usd_foil"] is None
