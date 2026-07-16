"""Offline tests for the Commander Spellbook combo ingester.

The module's http_get_json is monkeypatched to serve two fixture pages in the
real API shape (camelCase DRF limit/offset envelope); no network is touched.
"""

import json

import pytest

from weaver.ingest import spellbook
from weaver.ingest.base import get_meta


@pytest.fixture()
def pages(fixtures_dir):
    page1 = json.loads(
        (fixtures_dir / "spellbook_variants_page1.json").read_text(encoding="utf-8")
    )
    page2 = json.loads(
        (fixtures_dir / "spellbook_variants_page2.json").read_text(encoding="utf-8")
    )
    return page1, page2


def _no_bulk(*_a, **_k):
    raise RuntimeError("bulk download disabled in this test")


@pytest.fixture()
def fake_api(monkeypatch, pages):
    """Serve page1 then page2 (cycling, so re-runs work); record request URLs.
    Bulk download is disabled so the API-pagination fallback is exercised."""
    page1, page2 = pages
    calls = []

    def fake_get(url, *, params=None):
        calls.append(url)
        if len(calls) % 2 == 1:
            return page1
        assert url == page1["next"], "follow-up request must use the 'next' URL"
        return page2

    monkeypatch.setattr(spellbook, "http_get_json", fake_get)
    monkeypatch.setattr(spellbook, "download_file", _no_bulk)  # force API path
    monkeypatch.setattr(spellbook, "PAGE_PAUSE", 0)
    return calls


@pytest.fixture()
def ingested(db, cache_dir, fake_api):
    return spellbook.ingest(db, cache_dir, progress=lambda _msg: None)


def test_pagination_followed(db, cache_dir, fake_api, pages):
    spellbook.ingest(db, cache_dir, progress=lambda _msg: None)
    page1, _page2 = pages
    assert len(fake_api) == 2
    assert fake_api[0] == spellbook.START_URL
    assert "limit=100" in fake_api[0] and "format=json" in fake_api[0]
    assert fake_api[1] == page1["next"]


def test_combo_count_and_status_skip(db, ingested):
    # 5 fixture variants, one with status "E" (example) is skipped.
    ids = {row[0] for row in db.execute("SELECT id FROM combos")}
    assert ids == {"450-4131", "1478-2570", "2836-4529--190", "2069-2323"}
    assert ingested.rows == 4
    assert "902-3611" not in ids  # status "E" skipped
    # No orphaned combo_cards for the skipped variant either.
    assert not db.execute(
        "SELECT 1 FROM combo_cards WHERE combo_id = '902-3611'"
    ).fetchall()


def test_known_combo_cards(db, ingested):
    rows = db.execute(
        "SELECT card_name, oracle_id, quantity, must_be_commander"
        " FROM combo_cards WHERE combo_id = '450-4131' ORDER BY card_name"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("Basalt Monolith", "1d67d356-3d1a-4e35-9560-fa1c1b1e40b5", 1, 0),
        ("Rings of Brighthearth", "6a2b1a34-4a6f-4a45-9a5c-5a1e9e6b3f8d", 1, 0),
    ]
    card_count = db.execute(
        "SELECT card_count FROM combos WHERE id = '450-4131'"
    ).fetchone()[0]
    assert card_count == 2


def test_produces_and_identity_round_trip(db, ingested):
    row = db.execute(
        "SELECT produces, color_identity, mana_needed, popularity,"
        " legal_commander, spellbook_uri FROM combos WHERE id = '1478-2570'"
    ).fetchone()
    produces, identity, mana, popularity, legal_commander, uri = row
    assert json.loads(produces) == ["Win the game"]
    assert json.loads(identity) == ["U", "B"]  # normalized from "UB"
    assert mana == "{U}{U}{B}"
    assert popularity == 9968
    assert legal_commander == 1
    assert uri == "https://commanderspellbook.com/combo/1478-2570/"
    # Colorless identity normalizes to ["C"].
    colorless = db.execute(
        "SELECT color_identity FROM combos WHERE id = '450-4131'"
    ).fetchone()[0]
    assert json.loads(colorless) == ["C"]


def test_template_requirement_noted_in_prerequisites(db, ingested):
    prereqs, card_count = db.execute(
        "SELECT prerequisites, card_count FROM combos WHERE id = '2836-4529--190'"
    ).fetchone()
    assert "[requires: A free sacrifice outlet]" in prereqs
    assert "Reveillark is in your graveyard." in prereqs
    # Templates are not concrete cards: only the 2 `uses` count.
    assert card_count == 2
    names = {
        r[0]
        for r in db.execute(
            "SELECT card_name FROM combo_cards WHERE combo_id = '2836-4529--190'"
        )
    }
    assert names == {"Karmic Guide", "Reveillark"}


def test_must_be_commander_flag(db, ingested):
    rows = dict(
        db.execute(
            "SELECT card_name, must_be_commander FROM combo_cards"
            " WHERE combo_id = '2069-2323'"
        ).fetchall()
    )
    assert rows == {"Godo, Bandit Warlord": 1, "Helm of the Host": 0}


def test_rerun_is_idempotent(db, cache_dir, fake_api):
    first = spellbook.ingest(db, cache_dir, progress=lambda _msg: None)
    second = spellbook.ingest(db, cache_dir, progress=lambda _msg: None)
    assert len(fake_api) == 4  # two pages per run
    assert first.rows == second.rows == 4
    assert db.execute("SELECT COUNT(*) FROM combos").fetchone()[0] == 4
    assert db.execute("SELECT COUNT(*) FROM combo_cards").fetchone()[0] == 8
    # Still exactly one row per (combo, card).
    dupes = db.execute(
        "SELECT combo_id, card_name, COUNT(*) FROM combo_cards"
        " GROUP BY combo_id, card_name HAVING COUNT(*) > 1"
    ).fetchall()
    assert dupes == []


def test_meta_recorded(db, ingested):
    assert get_meta(db, "spellbook.count") == "4"
    updated_at = get_meta(db, "spellbook.updated_at")
    assert updated_at and updated_at.endswith("Z")


def test_bulk_path_loads_from_a_single_file(db, cache_dir, monkeypatch, pages):
    """When the bulk file is available, it's used instead of paging the API."""
    page1, page2 = pages
    variants = (page1["results"] or []) + (page2["results"] or [])

    def fake_download(url, dest, *, force=False, progress=print):
        # write the variants as a top-level JSON array (bulk-file shape)
        dest.write_text(json.dumps(variants), encoding="utf-8")
        return dest

    def boom(*_a, **_k):
        raise AssertionError("API must not be called when bulk data is present")

    monkeypatch.setattr(spellbook, "download_file", fake_download)
    monkeypatch.setattr(spellbook, "http_get_json", boom)
    monkeypatch.setattr(spellbook, "_MIN_BULK_OK", 1)  # tiny fixture

    result = spellbook.ingest(db, cache_dir, progress=lambda _m: None)
    assert "bulk" in result.detail
    assert result.rows == 4  # same 4 OK variants, one 'E' skipped
    assert db.execute("SELECT COUNT(*) FROM combos").fetchone()[0] == 4


def test_failed_refresh_preserves_existing_combos(db, cache_dir, monkeypatch):
    """If both bulk and API fail, don't wipe an existing combo table."""
    db.execute("INSERT INTO combos(id, description) VALUES('old-1','kept')")
    db.commit()
    monkeypatch.setattr(spellbook, "download_file", _no_bulk)
    monkeypatch.setattr(spellbook, "http_get_json", _no_bulk)
    monkeypatch.setattr(spellbook, "PAGE_PAUSE", 0)
    result = spellbook.ingest(db, cache_dir, progress=lambda _m: None)
    assert result.rows == 0
    # existing data survived the failed refresh
    assert db.execute("SELECT COUNT(*) FROM combos").fetchone()[0] == 1
