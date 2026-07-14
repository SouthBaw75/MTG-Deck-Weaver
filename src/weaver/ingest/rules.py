"""Magic Comprehensive Rules ingester.

Downloads the official Comprehensive Rules text file from Wizards of the
Coast, parses the numbered rules and the glossary, and loads the `rules`,
`rules_fts`, and `glossary` tables.

The source file is quirky, so this module defends against three things:

- The download URL changes with every rules update. We discover the current
  .txt link by scraping https://magic.wizards.com/en/rules, falling back to
  a pinned URL (FALLBACK_RULES_URL) if discovery fails.
- The encoding is unreliable: sometimes UTF-8 (with BOM), sometimes CP-1252.
- The rules text appears TWICE: first as a table of contents, then as the
  full body, followed by a Glossary section and Credits. We anchor on the
  SECOND "1. Game Concepts" line (body start), the LAST "Glossary" line
  (body end / glossary start), and the LAST "Credits" line (glossary end).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import requests

from weaver.ingest.base import (
    DEFAULT_HEADERS,
    REQUEST_TIMEOUT,
    IngestResult,
    Progress,
    download_file,
    set_meta,
    utcnow_iso,
)

NAME = "rules"

# Page that links to the current Comprehensive Rules downloads.
RULES_PAGE_URL = "https://magic.wizards.com/en/rules"

# Pinned known-good URL used when discovery fails.
FALLBACK_RULES_URL = (
    "https://media.wizards.com/2026/downloads/MagicCompRules%2020260227.txt"
)

# The .txt link on the rules page. URLs may contain %20 escapes and query
# strings; capture (non-greedily) up to and including ".txt" only.
_RULES_URL_RE = re.compile(
    r"https?://media\.wizards\.com/[^\s\"'<>]*?MagicCompRules[^\s\"'<>]*?\.txt"
)

# "100.1. Text" / "702.2c Text" -> rules '100.1', '702.2c'.
_RULE_RE = re.compile(r"^(\d{3})\.(\d+)([a-z])?\.?\s+(.*\S)\s*$")
# "100. General" -> section rule '100'.
_SECTION_RE = re.compile(r"^(\d{3})\.\s+(.*\S)\s*$")
# "1. Game Concepts" chapter headers: structural markers, not stored.
_CHAPTER_RE = re.compile(r"^\d\.\s+\S")


def _decode(data: bytes) -> str:
    """Decode the rules file's unreliable encoding; normalize line endings."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _discover_rules_url() -> str:
    """Scrape the rules landing page for the current CompRules .txt URL."""
    resp = requests.get(RULES_PAGE_URL, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    match = _RULES_URL_RE.search(resp.text)
    if match is None:
        raise ValueError("no MagicCompRules .txt link found on rules page")
    return match.group(0)


def _rindex(items: list[str], value: str, before: int | None = None) -> int | None:
    """Index of the LAST element equal to `value` (optionally before an index)."""
    stop = len(items) if before is None else before
    for i in range(stop - 1, -1, -1):
        if items[i] == value:
            return i
    return None


def _add_rule(
    rules: dict[str, tuple[str, str | None]],
    number: str,
    text: str,
    parent: str | None,
    warnings: list[str],
) -> None:
    if number in rules:
        warnings.append(f"duplicate rule {number}; keeping the later occurrence")
    rules[number] = (text, parent)


def _parse(
    text: str,
) -> tuple[list[tuple[str, str, str | None]], list[tuple[str, str]], list[str]]:
    """Parse the decoded rules file.

    Returns (rule_rows, glossary_rows, warnings) where rule_rows are
    (rule_number, text, parent) and glossary_rows are (term, definition).
    """
    warnings: list[str] = []
    lines = text.split("\n")
    stripped = [line.strip() for line in lines]

    # Landmarks. The ToC also contains bare "Glossary" and "Credits" lines,
    # so we take the LAST occurrences.
    credits_idx = _rindex(stripped, "Credits")
    if credits_idx is None:
        credits_idx = len(lines)
        warnings.append('no "Credits" line found; parsing glossary to end of file')
    glossary_idx = _rindex(stripped, "Glossary", before=credits_idx)
    if glossary_idx is None:
        glossary_idx = credits_idx
        warnings.append('no "Glossary" line found; no glossary parsed')

    # The rules appear twice (ToC then full body): the body starts at the
    # SECOND "1. Game Concepts" line.
    concept_idxs = [
        i for i, s in enumerate(stripped[:glossary_idx]) if s == "1. Game Concepts"
    ]
    if len(concept_idxs) >= 2:
        body_start = concept_idxs[1]
    elif concept_idxs:
        body_start = concept_idxs[0]
        warnings.append(
            'only one "1. Game Concepts" line found; '
            "table of contents may leak into the rules"
        )
    else:
        body_start = 0
        warnings.append('no "1. Game Concepts" line found; parsing from top of file')

    # ---- numbered rules ------------------------------------------------
    rules: dict[str, tuple[str, str | None]] = {}  # number -> (text, parent)
    current: str | None = None
    for raw in lines[body_start:glossary_idx]:
        line = raw.strip()
        if not line:
            continue
        m = _RULE_RE.match(line)
        if m:
            major, minor, letter, body = m.group(1), m.group(2), m.group(3), m.group(4)
            if letter:
                number, parent = f"{major}.{minor}{letter}", f"{major}.{minor}"
            else:
                number, parent = f"{major}.{minor}", major
            _add_rule(rules, number, body, parent, warnings)
            current = number
            continue
        m = _SECTION_RE.match(line)
        if m:
            number, body = m.group(1), m.group(2)
            _add_rule(rules, number, body, None, warnings)
            current = number
            continue
        if _CHAPTER_RE.match(line):
            current = None
            continue
        # Continuation of the previous rule (wrapped text, "Example:" lines).
        if current is not None:
            prev_text, parent = rules[current]
            rules[current] = (prev_text + "\n" + line, parent)
        # else: stray prose before the first rule -- ignore.

    rule_rows = [(number, txt, parent) for number, (txt, parent) in rules.items()]

    # ---- glossary -------------------------------------------------------
    # Entries are blank-line-separated blocks: term line, then definition.
    glossary: list[tuple[str, str]] = []
    seen_terms: set[str] = set()
    block: list[str] = []
    for raw in [*lines[glossary_idx + 1 : credits_idx], ""]:
        line = raw.strip()
        if line:
            block.append(line)
            continue
        if block:
            term, definition = block[0], "\n".join(block[1:])
            if not definition:
                warnings.append(f"glossary term {term!r} has no definition; skipped")
            elif term in seen_terms:
                warnings.append(f"duplicate glossary term {term!r}; skipped")
            else:
                glossary.append((term, definition))
                seen_terms.add(term)
            block = []

    return rule_rows, glossary, warnings


def ingest(
    conn: sqlite3.Connection,
    cache_dir: Path,
    force: bool = False,
    progress: Progress = print,
) -> IngestResult:
    result = IngestResult(name=NAME)

    try:
        url = _discover_rules_url()
    except Exception as exc:  # noqa: BLE001 -- any discovery failure -> fallback
        url = FALLBACK_RULES_URL
        result.warnings.append(f"rules URL discovery failed ({exc}); using fallback URL")

    path = download_file(url, cache_dir / "MagicCompRules.txt", force=force, progress=progress)
    text = _decode(path.read_bytes())

    rule_rows, glossary_rows, parse_warnings = _parse(text)
    result.warnings.extend(parse_warnings)

    # Full refresh: these tables are wholly owned by this ingester.
    conn.execute("DELETE FROM rules")
    conn.execute("DELETE FROM glossary")
    conn.execute("DELETE FROM rules_fts")

    conn.executemany(
        "INSERT INTO rules(rule_number, text, parent) VALUES(?, ?, ?)", rule_rows
    )
    conn.executemany(
        "INSERT INTO rules_fts(rule_number, text) VALUES(?, ?)",
        ((number, txt) for number, txt, _parent in rule_rows),
    )
    conn.executemany(
        "INSERT INTO glossary(term, definition) VALUES(?, ?)", glossary_rows
    )
    progress(f"  rules: {len(rule_rows)} rules, {len(glossary_rows)} glossary entries")

    set_meta(conn, f"{NAME}.updated_at", utcnow_iso())
    set_meta(conn, f"{NAME}.source_url", url)

    result.rows = len(rule_rows) + len(glossary_rows)
    result.detail = f"{len(rule_rows)} rules + {len(glossary_rows)} glossary entries"
    return result
