"""Offline tests for the Comprehensive Rules ingester.

All network access is monkeypatched out: URL discovery returns a canned URL
and download_file copies the fixture excerpt into the cache dir.
"""

from __future__ import annotations

import shutil

import pytest

import weaver.ingest.rules as rules_mod

# The fixture body contains 4 section headers (100, 601, 702, 903) and
# 18 numbered rules; the ToC copies must contribute nothing.
EXPECTED_RULE_COUNT = 22
EXPECTED_GLOSSARY_COUNT = 6

FAKE_URL = "https://media.wizards.com/test/MagicCompRules%20test.txt"


@pytest.fixture()
def offline(monkeypatch, fixtures_dir):
    """Make rules.ingest() fully offline, serving the fixture excerpt."""
    fixture = fixtures_dir / "comprules_excerpt.txt"

    def fake_download(url, dest, *, force=False, progress=print):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, dest)
        return dest

    monkeypatch.setattr(rules_mod, "download_file", fake_download)
    monkeypatch.setattr(rules_mod, "_discover_rules_url", lambda: FAKE_URL)


@pytest.fixture()
def ingested(db, cache_dir, offline):
    result = rules_mod.ingest(db, cache_dir, progress=lambda _msg: None)
    return db, result


def test_result_shape(ingested):
    _db, result = ingested
    assert result.name == "rules"
    assert not result.skipped
    assert result.rows == EXPECTED_RULE_COUNT + EXPECTED_GLOSSARY_COUNT


def test_rule_702_2_is_deathtouch(ingested):
    db, _ = ingested
    row = db.execute(
        "SELECT text, parent FROM rules WHERE rule_number = '702.2'"
    ).fetchone()
    assert row is not None
    assert "deathtouch" in row["text"].lower()
    assert row["parent"] == "702"


def test_parent_chain(ingested):
    db, _ = ingested
    parents = {
        r["rule_number"]: r["parent"]
        for r in db.execute("SELECT rule_number, parent FROM rules")
    }
    assert parents["702.2a"] == "702.2"
    assert parents["100.1a"] == "100.1"
    assert parents["100.1"] == "100"
    assert parents["100"] is None
    assert parents["903.5c"] == "903.5"


def test_example_line_appended_to_rule(ingested):
    db, _ = ingested
    row = db.execute(
        "SELECT text FROM rules WHERE rule_number = '702.2c'"
    ).fetchone()
    assert row is not None
    assert "\nExample:" in row["text"]
    assert row["text"].startswith("Any nonzero amount of combat damage")


def test_toc_produces_no_garbage(ingested):
    db, _ = ingested
    count = db.execute("SELECT COUNT(*) AS n FROM rules").fetchone()["n"]
    assert count == EXPECTED_RULE_COUNT
    # ToC-only sections (101, 602, 900, ...) must not appear.
    for toc_only in ("101", "102", "602", "701", "900"):
        assert (
            db.execute(
                "SELECT 1 FROM rules WHERE rule_number = ?", (toc_only,)
            ).fetchone()
            is None
        )
    # Section headers kept their body text, unpolluted by chapter lines.
    assert db.execute(
        "SELECT text FROM rules WHERE rule_number = '100'"
    ).fetchone()["text"] == "General"
    assert db.execute(
        "SELECT text FROM rules WHERE rule_number = '601'"
    ).fetchone()["text"] == "Casting Spells"
    # The "6. Spells, Abilities, and Effects" chapter header must not have
    # been appended to the rule preceding it.
    row = db.execute(
        "SELECT text FROM rules WHERE rule_number = '100.2a'"
    ).fetchone()
    assert "Spells, Abilities" not in row["text"]


def test_glossary(ingested):
    db, _ = ingested
    count = db.execute("SELECT COUNT(*) AS n FROM glossary").fetchone()["n"]
    assert count == EXPECTED_GLOSSARY_COUNT
    row = db.execute(
        "SELECT definition FROM glossary WHERE term = 'Deathtouch'"
    ).fetchone()
    assert row is not None
    assert "702.2" in row["definition"]
    assert db.execute(
        "SELECT 1 FROM glossary WHERE term = 'Trample'"
    ).fetchone() is not None
    # "Credits" content must not leak in as glossary terms.
    assert db.execute(
        "SELECT 1 FROM glossary WHERE term LIKE '%Richard Garfield%'"
    ).fetchone() is None


def test_fts_match(ingested):
    db, _ = ingested
    hits = {
        r["rule_number"]
        for r in db.execute(
            "SELECT rule_number FROM rules_fts WHERE rules_fts MATCH 'deathtouch'"
        )
    }
    assert hits
    assert "702.2a" in hits


def test_meta_recorded(ingested):
    db, _ = ingested
    updated_at = db.execute(
        "SELECT value FROM meta WHERE key = 'rules.updated_at'"
    ).fetchone()
    assert updated_at is not None and updated_at["value"]
    source_url = db.execute(
        "SELECT value FROM meta WHERE key = 'rules.source_url'"
    ).fetchone()
    assert source_url["value"] == FAKE_URL


def test_rerun_is_idempotent(ingested, cache_dir):
    db, first = ingested
    second = rules_mod.ingest(db, cache_dir, progress=lambda _msg: None)
    assert second.rows == first.rows
    assert (
        db.execute("SELECT COUNT(*) AS n FROM rules").fetchone()["n"]
        == EXPECTED_RULE_COUNT
    )
    assert (
        db.execute("SELECT COUNT(*) AS n FROM glossary").fetchone()["n"]
        == EXPECTED_GLOSSARY_COUNT
    )
    assert (
        db.execute("SELECT COUNT(*) AS n FROM rules_fts").fetchone()["n"]
        == EXPECTED_RULE_COUNT
    )


def test_fallback_url_on_discovery_failure(db, cache_dir, offline, monkeypatch):
    def boom():
        raise ConnectionError("network down")

    monkeypatch.setattr(rules_mod, "_discover_rules_url", boom)
    result = rules_mod.ingest(db, cache_dir, progress=lambda _msg: None)
    assert any("discovery failed" in w for w in result.warnings)
    source_url = db.execute(
        "SELECT value FROM meta WHERE key = 'rules.source_url'"
    ).fetchone()
    assert source_url["value"] == rules_mod.FALLBACK_RULES_URL


def test_decode_handles_cp1252_and_bom():
    # CP-1252 smart quotes are invalid UTF-8 and must not blow up.
    text = rules_mod._decode(b"\x93deathtouch\x94\r\nnext line\rend")
    assert "deathtouch" in text
    assert "\r" not in text
    assert text.count("\n") == 2
    # UTF-8 BOM is stripped.
    assert rules_mod._decode(b"\xef\xbb\xbf100. General") == "100. General"


def test_discovery_regex_stops_at_txt():
    html = (
        '<a href="https://media.wizards.com/2026/downloads/'
        'MagicCompRules%2020260227.txt?v=3">TXT</a>'
    )
    m = rules_mod._RULES_URL_RE.search(html)
    assert m is not None
    assert m.group(0).endswith(".txt")
    assert "?" not in m.group(0)
