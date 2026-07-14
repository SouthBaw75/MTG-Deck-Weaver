"""Analyzer contract and shared result types.

Each analyzer is a callable taking a DeckView and returning an AnalysisSection.
Analyzers are pure (no DB, no network): everything they need is on the
DeckView, so they can be unit-tested with hand-built fixtures.

Severity drives report ordering and coloring:
    ok       — meets expectations
    info     — neutral fact worth surfacing
    warn     — a weakness the player should consider
    problem  — a rule violation or serious deficiency
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

Severity = str  # "ok" | "info" | "warn" | "problem"

_SEVERITY_RANK = {"problem": 0, "warn": 1, "info": 2, "ok": 3}


@dataclass
class Finding:
    severity: Severity
    message: str


@dataclass
class AnalysisSection:
    title: str
    findings: list[Finding] = field(default_factory=list)
    # Free-form structured data for downstream consumers (report tables, the
    # future deck builder). Not rendered directly unless the renderer knows it.
    data: dict = field(default_factory=dict)

    def add(self, severity: Severity, message: str) -> None:
        self.findings.append(Finding(severity, message))

    @property
    def worst_severity(self) -> Severity:
        if not self.findings:
            return "ok"
        return min((f.severity for f in self.findings), key=lambda s: _SEVERITY_RANK[s])


class Analyzer(Protocol):
    name: str

    def analyze(self, deck) -> AnalysisSection: ...
