"""The tagging engine: runs all matchers over the cards table, applies
curated overrides, and writes the `card_tags` table.

Curated overrides (data/curated/tag_overrides.yaml) have the last word:

    - card: Ashnod's Altar
      add:
        - tag: sac-outlet
          quality: 0.95
          why: free repeatable outlet, ramps too
      remove:
        - removal.spot.creature      # pattern false positive
      quality:
        ramp.rock: 0.7               # adjust a pattern hit's weight
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from weaver.db.connection import repo_root
from weaver.ingest.base import Progress, set_meta, utcnow_iso
from weaver.knowledge.cardview import CardView, TagHit, clamp01
from weaver.knowledge.matchers import matcher_modules
from weaver.knowledge.taxonomy import is_valid_tag


@dataclass
class TagReport:
    cards_tagged: int = 0
    tag_rows: int = 0
    overrides_applied: int = 0
    invalid_tags: set[str] = field(default_factory=set)


def load_overrides(curated_dir: Path | None = None) -> dict[str, dict]:
    path = (curated_dir or repo_root() / "data" / "curated") / "tag_overrides.yaml"
    if not path.exists():
        return {}
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    overrides: dict[str, dict] = {}
    for entry in entries:
        overrides[entry["card"]] = entry
    return overrides


def _apply_overrides(name: str, hits: dict[str, TagHit], overrides: dict[str, dict]) -> bool:
    entry = overrides.get(name)
    if not entry:
        return False
    for tag in entry.get("remove") or []:
        hits.pop(tag, None)
    for tag, quality in (entry.get("quality") or {}).items():
        if tag in hits:
            hits[tag] = TagHit(tag, clamp01(float(quality)), hits[tag].why + " [curated quality]")
    for add in entry.get("add") or []:
        hits[add["tag"]] = TagHit(
            add["tag"],
            clamp01(float(add.get("quality", 0.7))),
            add.get("why", "curated"),
        )
    return True


def run_tagging(
    conn: sqlite3.Connection,
    *,
    curated_dir: Path | None = None,
    progress: Progress = print,
) -> TagReport:
    report = TagReport()
    mods = matcher_modules()
    overrides = load_overrides(curated_dir)
    progress(f"  tagger: {len(mods)} matcher module(s), {len(overrides)} curated override(s)")

    rows_out: list[tuple] = []
    for row in conn.execute("SELECT * FROM cards"):
        card = CardView.from_row(row)
        best: dict[str, TagHit] = {}
        for mod in mods:
            for hit in mod.match(card):
                if not is_valid_tag(hit.tag):
                    report.invalid_tags.add(hit.tag)
                    continue
                prev = best.get(hit.tag)
                if prev is None or hit.quality > prev.quality:
                    best[hit.tag] = TagHit(hit.tag, clamp01(hit.quality), hit.why)
        overridden = _apply_overrides(card.name, best, overrides)
        if overridden:
            report.overrides_applied += 1
            source = "override"
        else:
            source = "pattern"
        if best:
            report.cards_tagged += 1
        for hit in best.values():
            rows_out.append((row["oracle_id"], hit.tag, hit.quality, source, hit.why))

    conn.execute("DELETE FROM card_tags")
    conn.executemany(
        "INSERT INTO card_tags(oracle_id, tag, quality, source, why) VALUES(?, ?, ?, ?, ?)",
        rows_out,
    )
    set_meta(conn, "tagger.updated_at", utcnow_iso())
    report.tag_rows = len(rows_out)

    progress(f"  tagger: {report.tag_rows} tags on {report.cards_tagged} cards")
    if report.invalid_tags:
        progress(f"  tagger: WARNING — unregistered tags ignored: {sorted(report.invalid_tags)}")
    return report
