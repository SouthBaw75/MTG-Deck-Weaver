"""Offline tests for the MTGJSON vocabulary ingester.

download_file is monkeypatched (as imported by weaver.ingest.mtgjson) to copy
fixture files into cache_dir instead of hitting the network.
"""

import json
import shutil

import pytest

from weaver.ingest import mtgjson

FIXTURE_BY_BASENAME = {
    "Keywords.json": "mtgjson_keywords.json",
    "CardTypes.json": "mtgjson_cardtypes.json",
}


@pytest.fixture()
def offline_download(monkeypatch, fixtures_dir):
    """Replace mtgjson's download_file with a fixture-copying fake."""

    def fake_download(url, dest, *, force=False, progress=print):
        basename = url.rsplit("/", 1)[-1]
        src = fixtures_dir / FIXTURE_BY_BASENAME[basename]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return dest

    monkeypatch.setattr(mtgjson, "download_file", fake_download)
    return fake_download


@pytest.fixture()
def keywords_fixture(fixtures_dir):
    return json.loads((fixtures_dir / "mtgjson_keywords.json").read_text())


@pytest.fixture()
def cardtypes_fixture(fixtures_dir):
    return json.loads((fixtures_dir / "mtgjson_cardtypes.json").read_text())


@pytest.fixture()
def ingested(db, cache_dir, offline_download):
    result = mtgjson.ingest(db, cache_dir, progress=lambda msg: None)
    return db, result


def test_keyword_counts_per_category(ingested, keywords_fixture):
    db, _ = ingested
    data = keywords_fixture["data"]
    expected = {
        "ability": len(data["keywordAbilities"]),
        "action": len(data["keywordActions"]),
        "word": len(data["abilityWords"]),
    }
    counts = dict(
        db.execute("SELECT category, COUNT(*) FROM keywords GROUP BY category")
    )
    assert counts == expected


def test_deathtouch_is_an_ability(ingested):
    db, _ = ingested
    row = db.execute(
        "SELECT 1 FROM keywords WHERE name = 'Deathtouch' AND category = 'ability'"
    ).fetchone()
    assert row is not None


def test_creature_subtypes_contain_elf(ingested):
    db, _ = ingested
    subtypes = [
        r[0]
        for r in db.execute(
            "SELECT subtype FROM card_subtypes WHERE card_type = 'creature'"
        )
    ]
    assert "Elf" in subtypes
    assert "Goblin" in subtypes


def test_land_supertypes_contain_basic(ingested):
    db, _ = ingested
    row = db.execute("SELECT supertypes FROM card_types WHERE type = 'land'").fetchone()
    assert row is not None
    supertypes = json.loads(row[0])
    assert "Basic" in supertypes


def test_rerun_is_idempotent(ingested, cache_dir):
    db, first = ingested

    def table_counts():
        return {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("keywords", "card_types", "card_subtypes")
        }

    before = table_counts()
    second = mtgjson.ingest(db, cache_dir, progress=lambda msg: None)
    assert table_counts() == before
    assert second.rows == first.rows


def test_result_rows_matches_inserted_total(ingested):
    db, result = ingested
    total = sum(
        db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("keywords", "card_types", "card_subtypes")
    )
    assert result.rows == total
    assert result.name == "mtgjson"
    assert not result.skipped


def test_meta_version_and_updated_at_set(ingested, keywords_fixture):
    db, _ = ingested
    version = db.execute(
        "SELECT value FROM meta WHERE key = 'mtgjson.version'"
    ).fetchone()
    assert version is not None
    assert version[0] == keywords_fixture["meta"]["version"]
    updated = db.execute(
        "SELECT value FROM meta WHERE key = 'mtgjson.updated_at'"
    ).fetchone()
    assert updated is not None and updated[0]
