"""Per-bracket build templates: the target SHAPE of a 100-card deck.

A template tells the builder how many slots to fill for each functional
role group (reusing the role_benchmarks.json group names), how many lands
to run, and how large the archetype-driven synergy_flex allotment is. The
loader is pure stdlib + json.
"""

from __future__ import annotations

import json
from pathlib import Path

from weaver.db.connection import repo_root

# Role-group keys shared with role_benchmarks.json. Kept here so callers can
# validate a template without re-reading the benchmarks file.
ROLE_GROUPS: tuple[str, ...] = (
    "ramp",
    "card_advantage",
    "spot_removal",
    "board_wipe",
    "targeted_disruption",
    "protection",
    "wincon",
)

MIN_BRACKET = 1
MAX_BRACKET = 5

_DEFAULT_RELATIVE_PATH = Path("data") / "curated" / "build_templates.json"


def _default_path() -> Path:
    return repo_root() / _DEFAULT_RELATIVE_PATH


def load_build_templates(path: Path | None = None) -> dict:
    """Load the build-templates JSON.

    When *path* is None the file is resolved relative to repo_root().
    """
    resolved = Path(path) if path is not None else _default_path()
    with open(resolved, encoding="utf-8") as fh:
        return json.load(fh)


def template_for_bracket(bracket: int, templates: dict | None = None) -> dict:
    """Return the resolved template dict for a bracket.

    Loads the data file when *templates* is None. The bracket is clamped to
    the valid 1-5 range. Raises ValueError on input that cannot be coerced to
    an integer bracket.
    """
    try:
        b = int(bracket)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid bracket: {bracket!r}") from exc

    b = max(MIN_BRACKET, min(MAX_BRACKET, b))

    if templates is None:
        templates = load_build_templates()

    table = templates.get("templates", templates)
    key = str(b)
    if key not in table:
        raise ValueError(f"no template for bracket {b}")
    return table[key]


def slots_sum_to_100(template: dict) -> bool:
    """True when 1 (commander) + role slots + synergy_flex + lands == 100."""
    roles = template.get("roles", {})
    total = (
        1
        + sum(roles.values())
        + template.get("synergy_flex", 0)
        + template.get("land_count", 0)
    )
    return total == 100
