"""Tests for per-bracket build templates (offline, real data file)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from weaver.build.templates import (
    ROLE_GROUPS,
    load_build_templates,
    slots_sum_to_100,
    template_for_bracket,
)
from weaver.db.connection import repo_root

BRACKETS = ["1", "2", "3", "4", "5"]


def _role_benchmark_groups() -> set[str]:
    path = repo_root() / "data" / "curated" / "role_benchmarks.json"
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return set(data["role_groups"].keys())


def test_all_five_brackets_present():
    data = load_build_templates()
    templates = data["templates"]
    assert set(templates.keys()) == set(BRACKETS)


@pytest.mark.parametrize("bracket", BRACKETS)
def test_slots_sum_to_100(bracket):
    template = load_build_templates()["templates"][bracket]
    total = (
        1
        + sum(template["roles"].values())
        + template["synergy_flex"]
        + template["land_count"]
    )
    assert total == 100
    assert slots_sum_to_100(template)


@pytest.mark.parametrize("bracket", BRACKETS)
def test_role_keys_match_benchmarks(bracket):
    benchmark_groups = _role_benchmark_groups()
    template = load_build_templates()["templates"][bracket]
    for key in template["roles"]:
        assert key in benchmark_groups
        assert key in ROLE_GROUPS


@pytest.mark.parametrize("bracket", BRACKETS)
def test_land_count_in_sane_range(bracket):
    template = load_build_templates()["templates"][bracket]
    assert 33 <= template["land_count"] <= 42


def test_higher_brackets_trend_leaner_on_lands():
    templates = load_build_templates()["templates"]
    lands = {b: templates[b]["land_count"] for b in BRACKETS}
    # Bracket 5 runs no more lands than bracket 2.
    assert lands["5"] <= lands["2"]
    # Land count is monotonically non-increasing from bracket 1 to 5.
    ordered = [lands[b] for b in BRACKETS]
    assert ordered == sorted(ordered, reverse=True)


def test_template_for_bracket_clamps_out_of_range():
    low = template_for_bracket(0)
    assert low == template_for_bracket(1)
    high = template_for_bracket(99)
    assert high == template_for_bracket(5)


def test_template_for_bracket_accepts_preloaded_templates():
    data = load_build_templates()
    assert template_for_bracket(3, data) == data["templates"]["3"]


@pytest.mark.parametrize("garbage", ["not-a-number", None, "", "3.5x"])
def test_template_for_bracket_raises_on_garbage(garbage):
    with pytest.raises(ValueError):
        template_for_bracket(garbage)


def test_load_build_templates_accepts_explicit_path():
    path = repo_root() / "data" / "curated" / "build_templates.json"
    data = load_build_templates(Path(path))
    assert "templates" in data
