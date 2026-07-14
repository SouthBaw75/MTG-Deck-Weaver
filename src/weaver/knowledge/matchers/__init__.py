"""Pattern-matcher registry.

Matchers are auto-discovered: every module in this package that defines
`match(card: CardView) -> list[TagHit]` participates. Drop a new domain
module in this directory and it is picked up — no registry edits needed.
"""

from __future__ import annotations

import importlib
import pkgutil

from weaver.knowledge.cardview import CardView, TagHit


def matcher_modules() -> list:
    mods = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        if callable(getattr(mod, "match", None)):
            mods.append(mod)
    return mods


def run_matchers(card: CardView) -> list[TagHit]:
    """Run every discovered matcher; keep the best quality per tag."""
    best: dict[str, TagHit] = {}
    for mod in matcher_modules():
        for hit in mod.match(card):
            prev = best.get(hit.tag)
            if prev is None or hit.quality > prev.quality:
                best[hit.tag] = hit
    return sorted(best.values(), key=lambda h: (-h.quality, h.tag))
