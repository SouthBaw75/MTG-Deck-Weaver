"""Phase 1 exit test: combined accuracy over the full golden corpus.

Runs ALL matchers together (run_matchers) over every golden card from every
domain and enforces the exit criteria from docs/PLAN.md:

- recall of expected tags >= 95%
- zero forbidden-tag violations (false positives the goldens explicitly ban)
"""

from __future__ import annotations

from weaver.knowledge.matchers import run_matchers
from golden_utils import load_all_golden


def test_combined_golden_accuracy():
    golden = load_all_golden()
    assert len(golden) >= 300, f"golden corpus too small: {len(golden)}"

    expected_total = 0
    expected_hit = 0
    violations: list[str] = []
    misses: list[str] = []

    for g in golden:
        tags = {h.tag for h in run_matchers(g.card)}
        expected_total += len(g.expect)
        hit = g.expect & tags
        expected_hit += len(hit)
        for miss in sorted(g.expect - tags):
            misses.append(f"{g.card.name}: missing {miss}")
        for bad in sorted(tags & g.forbid):
            violations.append(f"{g.card.name}: forbidden {bad}")

    recall = expected_hit / expected_total if expected_total else 1.0
    detail = (
        f"\ncorpus: {len(golden)} cards, {expected_total} expected tags, "
        f"recall {recall:.1%}, {len(violations)} forbidden violations"
    )
    assert not violations, detail + "\n" + "\n".join(violations)
    assert recall >= 0.95, detail + "\n" + "\n".join(misses)
