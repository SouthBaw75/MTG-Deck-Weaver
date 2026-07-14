"""Offline tests for the role-coverage analyzer (no DB, no network)."""

from __future__ import annotations

import json
from pathlib import Path

from weaver.analysis.analyzers import roles
from weaver.db.connection import repo_root
from weaver.knowledge import taxonomy

from tests.deck_fixtures import make_card, make_deck

# A deterministic benchmark used by most tests so results don't drift when the
# curated file is tuned. Mirrors the shape of role_benchmarks.json.
BENCH = {
    "source": "test",
    "role_groups": {
        "ramp": {"tags": ["ramp.rock", "ramp.land", "ramp.dork", "ramp.ritual"], "min": 10, "ideal": 12},
        "card_advantage": {"tags": ["draw.burst", "draw.engine", "impulse-draw", "wheel"], "min": 8, "ideal": 12},
        "spot_removal": {"tags": ["removal.spot.creature", "removal.spot.any", "removal.spot.artifact-enchantment"], "min": 6, "ideal": 10},
        "board_wipe": {"tags": ["wipe.creature", "wipe.any", "wipe.artifact-enchantment"], "min": 2, "ideal": 4},
        "protection": {"tags": ["protection.self", "protection.board"], "min": 1, "ideal": 3},
        "wincon": {"tags": ["wincon.combat", "wincon.alt", "extra-combat", "buff.anthem"], "min": 1, "ideal": 3},
    },
}


def _cards_with_tag(tag: str, n: int):
    return [make_card(f"{tag}-{i}", tags={tag: 1.0}) for i in range(n)]


def _well_rounded_deck():
    cards = []
    cards += _cards_with_tag("ramp.rock", 12)          # 12 ramp -> ideal
    cards += _cards_with_tag("draw.engine", 10)         # 10 draw -> >= min, < ideal
    cards += _cards_with_tag("removal.spot.creature", 8)  # 8 spot -> < ideal(10), >= min(6)
    cards += _cards_with_tag("wipe.creature", 4)        # 4 wipes -> ideal
    cards += _cards_with_tag("protection.self", 3)      # 3 protection -> ideal
    cards += _cards_with_tag("wincon.combat", 3)        # 3 wincon -> ideal
    return make_deck(cards)


def test_well_rounded_deck_no_problems():
    section = roles.analyze(_well_rounded_deck(), benchmark=BENCH)
    assert section.title == "Role Coverage"
    severities = {f.severity for f in section.findings}
    assert "problem" not in severities
    # Headline should be the all-clear ok when every min is met.
    assert section.findings[0].severity == "ok"
    assert section.data["roles_meeting_min"] == section.data["total_groups"]


def test_starved_deck_flags_named_groups():
    cards = []
    cards += _cards_with_tag("ramp.rock", 2)   # 2 ramp: 2 < 0.6*10 -> problem
    cards += _cards_with_tag("draw.engine", 8) # meets min
    # zero spot removal, zero wipes, zero protection, zero wincon
    section = roles.analyze(make_deck(cards), benchmark=BENCH)

    problems = [f.message for f in section.findings if f.severity == "problem"]
    joined = " ".join(problems).lower()
    assert "ramp" in joined  # severe ramp shortfall named
    # board wipes (min 2) at 0 is below 0.6*2 -> severe as well
    assert "board wipe" in joined

    # Headline is the biggest gap. Ramp shortfall (10-2=8) vs spot (6-0=6) ->
    # ramp is the biggest gap.
    assert "ramp" in section.findings[0].message.lower()
    assert section.findings[0].severity == "problem"


def test_multi_tag_dedup_counts_card_once():
    # One card carrying two spot-removal tags must count once, not twice.
    dual = make_card(
        "Assassin's Trophy",
        tags={"removal.spot.creature": 1.0, "removal.spot.any": 1.0},
    )
    section = roles.analyze(make_deck([dual]), benchmark=BENCH)
    assert section.data["roles"]["spot_removal"]["count"] == 1


def test_dedup_respects_quantity():
    dual = make_card(
        "Beast Within",
        qty=3,
        tags={"removal.spot.any": 1.0, "removal.spot.creature": 1.0},
    )
    section = roles.analyze(make_deck([dual]), benchmark=BENCH)
    # Quantity-weighted but de-duplicated across the group: 3, not 6.
    assert section.data["roles"]["spot_removal"]["count"] == 3


def test_section_data_structure():
    section = roles.analyze(_well_rounded_deck(), benchmark=BENCH)
    roles_data = section.data["roles"]
    for group, spec in BENCH["role_groups"].items():
        assert group in roles_data
        entry = roles_data[group]
        assert set(entry) == {"count", "min", "ideal"}
        assert entry["min"] == spec["min"]
        assert entry["ideal"] == spec["ideal"]
    assert "roles_meeting_min" in section.data
    assert "total_groups" in section.data


def test_missing_benchmark_degrades_gracefully(monkeypatch):
    # Empty benchmark -> single info finding, no crash.
    section = roles.analyze(make_deck([]), benchmark={})
    assert len(section.findings) == 1
    assert section.findings[0].severity == "info"


def test_default_loads_real_benchmark(monkeypatch):
    # With no explicit benchmark, the analyzer loads the curated JSON.
    section = roles.analyze(make_deck(_cards_with_tag("ramp.rock", 12)))
    assert "roles" in section.data
    assert "ramp" in section.data["roles"]
    assert section.data["roles"]["ramp"]["count"] == 12


def test_real_benchmark_file_is_valid():
    path = repo_root() / "data" / "curated" / "role_benchmarks.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert "role_groups" in doc and doc["role_groups"]
    for group, spec in doc["role_groups"].items():
        assert spec["tags"], f"{group} has no tags"
        for tag in spec["tags"]:
            assert taxonomy.is_valid_tag(tag), f"invalid tag {tag} in {group}"
        assert spec["min"] <= spec["ideal"], f"{group}: min > ideal"

    # Bracket modifiers, if present, must also reference known groups and be sane.
    for bracket, mods in doc.get("bracket_modifiers", {}).items():
        for group, spec in mods.items():
            assert group in doc["role_groups"], f"bracket {bracket}: unknown group {group}"
            if "min" in spec and "ideal" in spec:
                assert spec["min"] <= spec["ideal"]
