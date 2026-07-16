"""End-to-end Phase 0 exit test.

Builds a complete knowledge base by running the REAL ingest pipeline
(weaver.ingest.run_all) with only the network layer faked out to serve the
test fixtures, then exercises the CLI (`weaver card`, `weaver rule`,
`weaver stats`) against the resulting database.
"""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from weaver.cli.main import cli
from weaver.db.connection import connect
from weaver.db.schema import apply_schema
from weaver.ingest import run_all

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture()
def kb_path(tmp_path, monkeypatch):
    """A fully-populated knowledge base built through run_all() on fixtures."""
    import weaver.ingest.mtgjson as mtgjson
    import weaver.ingest.rules as rules
    import weaver.ingest.scryfall as scryfall
    import weaver.ingest.spellbook as spellbook

    # Scryfall: bulk listing points at a gzipped copy of the JSONL fixture.
    monkeypatch.setattr(
        scryfall,
        "http_get_json",
        lambda url, **kw: {
            "data": [
                {
                    "type": "oracle_cards",
                    "jsonl_download_uri": "https://fake/oracle-cards.jsonl.gz",
                    "updated_at": "2026-07-14T00:00:00Z",
                }
            ]
        },
    )

    def fake_scryfall_download(url, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(FIXTURES / "scryfall_oracle_sample.jsonl", "rb") as src:
            with gzip.open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        return dest

    monkeypatch.setattr(scryfall, "download_file", fake_scryfall_download)

    # MTGJSON: serve fixtures by URL basename.
    def fake_mtgjson_download(url, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / f"mtgjson_{Path(url).name.lower()}", dest)
        return dest

    monkeypatch.setattr(mtgjson, "download_file", fake_mtgjson_download)

    # Rules: skip discovery, serve the excerpt fixture.
    monkeypatch.setattr(rules, "_discover_rules_url", lambda: rules.FALLBACK_RULES_URL)

    def fake_rules_download(url, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / "comprules_excerpt.txt", dest)
        return dest

    monkeypatch.setattr(rules, "download_file", fake_rules_download)

    # Spellbook: two-page pagination from fixtures.
    def fake_spellbook_get(url, **kw):
        page = "page2" if "offset=100" in url else "page1"
        return json.loads((FIXTURES / f"spellbook_variants_{page}.json").read_text())

    monkeypatch.setattr(spellbook, "http_get_json", fake_spellbook_get)
    # Disable the bulk download so this test stays hermetic (uses the API path).
    def _no_bulk(*_a, **_k):
        raise RuntimeError("bulk disabled in test")
    monkeypatch.setattr(spellbook, "download_file", _no_bulk)
    monkeypatch.setattr(spellbook, "PAGE_PAUSE", 0)

    # Curated: read the real repo files regardless of cwd.
    monkeypatch.setenv("WEAVER_HOME", str(REPO_ROOT))

    db_path = tmp_path / "weaver.db"
    conn = connect(db_path)
    apply_schema(conn)
    results = run_all(conn, tmp_path / "cache", progress=lambda _msg: None)
    conn.close()

    assert [r.name for r in results] == [
        "scryfall", "mtgjson", "rules", "spellbook", "curated",
    ]
    failed = [r for r in results if r.detail.startswith("FAILED")]
    assert not failed, f"ingesters failed: {[(r.name, r.detail) for r in failed]}"
    assert all(r.rows > 0 for r in results)
    return db_path


def _run(kb_path, *args):
    result = CliRunner().invoke(cli, ["--db", str(kb_path), *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_update_populates_every_table(kb_path):
    conn = connect(kb_path)
    for table in ["cards", "keywords", "card_types", "card_subtypes", "rules",
                  "glossary", "combos", "combo_cards", "game_changers", "brackets"]:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0, table
    conn.close()


def test_cli_card_lookup(kb_path):
    out = _run(kb_path, "card", "Rhystic Study")
    assert "Rhystic Study" in out
    assert "GAME CHANGER" in out
    assert "commander: legal" in out


def test_cli_card_banned(kb_path):
    out = _run(kb_path, "card", "Black Lotus")
    assert "banned" in out


def test_cli_rule_lookup(kb_path):
    out = _run(kb_path, "rule", "702.2")
    assert "702.2" in out
    assert "eathtouch" in out  # Deathtouch/deathtouch
    assert "702.2a" in out  # subrules are listed


def test_cli_rule_fts_fallback(kb_path):
    out = _run(kb_path, "rule", "deathtouch")
    assert "702.2" in out


def test_cli_stats(kb_path):
    out = _run(kb_path, "stats")
    assert "cards" in out
    assert "game_changers" in out


def test_game_changer_reconciliation(kb_path):
    """Rhystic Study is flagged both by Scryfall and the curated list;
    the flag must survive the curated reconcile pass."""
    conn = connect(kb_path)
    row = conn.execute(
        "SELECT is_game_changer FROM cards WHERE name = 'Rhystic Study'"
    ).fetchone()
    assert row[0] == 1
    n = conn.execute("SELECT COUNT(*) FROM game_changers").fetchone()[0]
    assert n == 53
    conn.close()
