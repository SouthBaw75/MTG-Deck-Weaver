"""Analysis framework tests: loader resolution, engine discovery, report."""

from __future__ import annotations

import pytest

from weaver.analysis.base import AnalysisSection
from weaver.analysis.engine import analyze_deck
from deck_fixtures import basic_lands, make_card, make_deck


def test_analyze_deck_runs_registered_analyzers():
    deck = make_deck([make_card("Sol Ring", type_line="Artifact", tags={"ramp.rock": 1.0})])
    sections = analyze_deck(deck)
    assert sections, "no analyzers discovered"
    assert all(isinstance(s, AnalysisSection) for s in sections)
    # summary analyzer is ORDER 0, always first
    assert sections[0].title == "Overview"


def test_section_worst_severity():
    s = AnalysisSection(title="t")
    s.add("ok", "fine")
    s.add("warn", "hmm")
    s.add("problem", "bad")
    assert s.worst_severity == "problem"


def test_overview_flags_wrong_size():
    deck = make_deck(basic_lands({"Forest": 5}))
    overview = analyze_deck(deck)[0]
    problems = [f for f in overview.findings if f.severity == "problem"]
    assert any("100" in f.message for f in problems)


class TestLoaderResolution:
    """Loader tests against a real (fixture-built) DB, if available."""

    def test_resolves_and_attaches_tags(self, tmp_path):
        pytest.importorskip("sqlite3")
        from weaver.db.connection import connect
        from weaver.db.schema import apply_schema
        from weaver.analysis.loader import load_deck

        conn = connect(tmp_path / "t.db")
        apply_schema(conn)
        conn.execute(
            "INSERT INTO cards(oracle_id, name, type_line, mana_value, color_identity,"
            " legal_commander, is_game_changer) VALUES"
            " ('o1','Sol Ring','Artifact',1,'[]','legal',0),"
            " ('o2','Fire // Ice','Instant // Instant',2,'[\"U\",\"R\"]','legal',0)"
        )
        conn.execute("INSERT INTO card_tags(oracle_id, tag, quality, source) VALUES('o1','ramp.rock',1.0,'pattern')")
        conn.commit()

        deck = load_deck(conn, "1 Sol Ring\n1 Fire\n1 Ghost Card\n")
        by_name = {c.name: c for c in deck.cards}
        assert by_name["Sol Ring"].tags == {"ramp.rock": 1.0}
        # half-name resolves to the full split card
        assert "Fire // Ice" in by_name
        assert deck.unresolved == ["Ghost Card"]
