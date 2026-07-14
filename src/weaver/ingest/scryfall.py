"""Scryfall bulk-data ingester: loads the oracle_cards bulk file into `cards`.

Scryfall publishes daily bulk exports (https://scryfall.com/docs/api/bulk-data).
We use the "oracle_cards" export: exactly one printing per oracle identity.
After July 20 2026 the exports are JSONL-only, so we prefer the
``jsonl_download_uri`` (gzipped, one JSON object per line) and fall back to
the legacy ``download_uri`` (a single JSON array) for robustness.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlsplit

from weaver.ingest.base import (
    IngestResult,
    Progress,
    download_file,
    http_get_json,
    set_meta,
    utcnow_iso,
)

NAME = "scryfall"

BULK_DATA_URL = "https://api.scryfall.com/bulk-data"
BULK_TYPE = "oracle_cards"

# Layouts that are not playable deck objects.
SKIP_LAYOUTS = frozenset(
    {
        "token",
        "double_faced_token",
        "emblem",
        "art_series",
        "vanguard",
        "scheme",
        "planar",
        "phenomenon",
    }
)

FACE_TEXT_SEPARATOR = "\n//\n"
COLOR_ORDER = {c: i for i, c in enumerate("WUBRG")}
BATCH_SIZE = 500

INSERT_SQL = """
INSERT INTO cards (
    oracle_id, name, layout, mana_cost, mana_value, type_line, oracle_text,
    colors, color_identity, keywords, produced_mana,
    power, toughness, loyalty, defense, card_faces,
    legal_commander, legalities, is_game_changer, reserved,
    rarity, set_code, collector_number, released_at, edhrec_rank,
    price_usd, price_usd_foil, price_eur, price_tix,
    scryfall_id, scryfall_uri
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _find_bulk_entry(payload: dict) -> dict:
    for entry in payload.get("data", []):
        if entry.get("type") == BULK_TYPE:
            return entry
    raise RuntimeError(f"Scryfall bulk-data listing has no '{BULK_TYPE}' entry")


def _iter_jsonl(fh) -> Iterator[dict]:
    for line in fh:
        line = line.strip()
        if line:
            yield json.loads(line)


def _iter_cards(path: Path) -> Iterator[dict]:
    """Yield card objects from a bulk file.

    Handles gzipped JSONL (streamed line by line) and plain JSON arrays.
    """
    suffixes = "".join(path.suffixes)
    gzipped = suffixes.endswith(".gz")
    jsonl = ".jsonl" in suffixes
    if gzipped:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            if jsonl:
                yield from _iter_jsonl(fh)
            else:
                yield from json.load(fh)
    else:
        with open(path, "rt", encoding="utf-8") as fh:
            if jsonl:
                yield from _iter_jsonl(fh)
            else:
                yield from json.load(fh)


def _json_or_none(value: Any) -> str | None:
    return json.dumps(value) if value is not None else None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _union_colors(faces: Iterable[dict]) -> list[str]:
    seen: set[str] = set()
    for face in faces:
        seen.update(face.get("colors") or [])
    return sorted(seen, key=lambda c: COLOR_ORDER.get(c, 99))


def _face_fallback(card: dict, faces: list[dict], key: str) -> Any:
    """Top-level value if present, else the first face that carries it
    (battles/planeswalker backs keep defense/loyalty on the face)."""
    value = card.get(key)
    if value is not None:
        return value
    for face in faces:
        if face.get(key) is not None:
            return face[key]
    return None


def _card_to_row(card: dict) -> tuple:
    faces = card.get("card_faces") or []

    oracle_text = card.get("oracle_text")
    if oracle_text is None and faces:
        oracle_text = FACE_TEXT_SEPARATOR.join(
            face.get("oracle_text") or "" for face in faces
        )

    colors = card.get("colors")
    if colors is None and faces:
        colors = _union_colors(faces)

    legalities = card.get("legalities") or {}
    prices = card.get("prices") or {}

    return (
        card["oracle_id"],
        card.get("name"),
        card.get("layout"),
        card.get("mana_cost"),
        card.get("cmc"),
        card.get("type_line"),
        oracle_text,
        _json_or_none(colors),
        _json_or_none(card.get("color_identity")),
        _json_or_none(card.get("keywords")),
        _json_or_none(card.get("produced_mana")),
        _face_fallback(card, faces, "power"),
        _face_fallback(card, faces, "toughness"),
        _face_fallback(card, faces, "loyalty"),
        _face_fallback(card, faces, "defense"),
        _json_or_none(faces or None),
        legalities.get("commander"),
        _json_or_none(legalities or None),
        1 if card.get("game_changer") else 0,
        1 if card.get("reserved") else 0,
        card.get("rarity"),
        card.get("set"),
        card.get("collector_number"),
        card.get("released_at"),
        card.get("edhrec_rank"),
        _float_or_none(prices.get("usd")),
        _float_or_none(prices.get("usd_foil")),
        _float_or_none(prices.get("eur")),
        _float_or_none(prices.get("tix")),
        card.get("id"),
        card.get("scryfall_uri"),
    )


def ingest(
    conn: sqlite3.Connection,
    cache_dir: Path,
    force: bool = False,
    progress: Progress = print,
) -> IngestResult:
    progress("  fetching bulk-data listing")
    entry = _find_bulk_entry(http_get_json(BULK_DATA_URL))

    uri = entry.get("jsonl_download_uri") or entry.get("download_uri")
    if not uri:
        raise RuntimeError("oracle_cards bulk entry has no download URI")

    bulk_updated_at = entry.get("updated_at")
    if bulk_updated_at:
        set_meta(conn, f"{NAME}.bulk_updated_at", bulk_updated_at)

    dest = cache_dir / Path(urlsplit(uri).path).name
    path = download_file(uri, dest, force=force, progress=progress)

    conn.execute("DELETE FROM cards")

    inserted = 0
    skipped_layout = 0
    missing_oracle_id = 0
    batch: list[tuple] = []

    def flush() -> None:
        nonlocal inserted
        if batch:
            conn.executemany(INSERT_SQL, batch)
            inserted += len(batch)
            batch.clear()

    for card in _iter_cards(path):
        if card.get("layout") in SKIP_LAYOUTS:
            skipped_layout += 1
            continue
        if not card.get("oracle_id"):
            missing_oracle_id += 1
            continue
        batch.append(_card_to_row(card))
        if len(batch) >= BATCH_SIZE:
            flush()
    flush()

    progress("  rebuilding cards_fts")
    conn.execute("INSERT INTO cards_fts(cards_fts) VALUES('rebuild')")
    set_meta(conn, f"{NAME}.updated_at", utcnow_iso())

    warnings: list[str] = []
    if missing_oracle_id:
        warnings.append(
            f"skipped {missing_oracle_id} entries without an oracle_id"
        )
    progress(
        f"  loaded {inserted} cards "
        f"({skipped_layout} non-playable layouts skipped)"
    )
    return IngestResult(
        name=NAME,
        rows=inserted,
        detail=f"{skipped_layout} non-playable layouts skipped",
        warnings=warnings,
    )
