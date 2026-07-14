"""Runs the registered analyzers over a DeckView and collects their sections.

Like the matcher registry, analyzers are auto-discovered: any module in
weaver.analysis.analyzers exposing `analyze(deck) -> AnalysisSection` and a
module-level ORDER int participates. ORDER controls report sequence.
"""

from __future__ import annotations

import importlib
import pkgutil

from weaver.analysis.base import AnalysisSection


def _analyzer_modules():
    import weaver.analysis.analyzers as pkg

    mods = []
    for info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
        if callable(getattr(mod, "analyze", None)):
            mods.append(mod)
    mods.sort(key=lambda m: getattr(m, "ORDER", 100))
    return mods


def analyze_deck(deck) -> list[AnalysisSection]:
    return [mod.analyze(deck) for mod in _analyzer_modules()]
