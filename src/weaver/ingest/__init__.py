"""Ingest pipeline: pulls every data source into the local knowledge base."""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

from weaver.ingest.base import IngestResult, Progress

# Ingesters run in this order. Each is a module exposing NAME and ingest().
INGESTER_MODULES = [
    "weaver.ingest.scryfall",
    "weaver.ingest.mtgjson",
    "weaver.ingest.rules",
    "weaver.ingest.spellbook",
    "weaver.ingest.curated",
]


def run_all(
    conn: sqlite3.Connection,
    cache_dir: Path,
    *,
    only: set[str] | None = None,
    force: bool = False,
    progress: Progress = print,
) -> list[IngestResult]:
    """Run each ingester in its own transaction; a failure in one source is
    reported (and rolled back) without aborting the others."""
    results: list[IngestResult] = []
    for modname in INGESTER_MODULES:
        mod = importlib.import_module(modname)
        name = getattr(mod, "NAME", modname.rsplit(".", 1)[-1])
        if only and name not in only:
            continue
        progress(f"[{name}]")
        try:
            result = mod.ingest(conn, cache_dir, force=force, progress=progress)
            conn.commit()
        except Exception as exc:  # noqa: BLE001 — one bad source must not sink the rest
            conn.rollback()
            result = IngestResult(name=name, skipped=True, detail=f"FAILED: {exc}")
        results.append(result)
    return results
