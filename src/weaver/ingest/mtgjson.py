"""MTGJSON vocabulary ingester: game keywords and the card type ontology.

Sources (https://mtgjson.com/api/v5/):
- Keywords.json  -> `keywords` table (name, category)
- CardTypes.json -> `card_types` (type, supertypes JSON) and
                    `card_subtypes` (card_type, subtype)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from weaver.ingest.base import (
    IngestResult,
    Progress,
    download_file,
    set_meta,
    utcnow_iso,
)

NAME = "mtgjson"

KEYWORDS_URL = "https://mtgjson.com/api/v5/Keywords.json"
CARDTYPES_URL = "https://mtgjson.com/api/v5/CardTypes.json"

# Keywords.json data keys -> our `keywords.category` values.
_CATEGORY_MAP = {
    "keywordAbilities": "ability",
    "keywordActions": "action",
    "abilityWords": "word",
}


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ingest(
    conn: sqlite3.Connection,
    cache_dir: Path,
    force: bool = False,
    progress: Progress = print,
) -> IngestResult:
    result = IngestResult(name=NAME)

    keywords_path = download_file(
        KEYWORDS_URL, cache_dir / "Keywords.json", force=force, progress=progress
    )
    cardtypes_path = download_file(
        CARDTYPES_URL, cache_dir / "CardTypes.json", force=force, progress=progress
    )

    keywords_doc = _load_json(keywords_path)
    cardtypes_doc = _load_json(cardtypes_path)

    # Full refresh: these tables are wholly owned by this ingester.
    conn.execute("DELETE FROM keywords")
    conn.execute("DELETE FROM card_types")
    conn.execute("DELETE FROM card_subtypes")

    rows = 0

    # ---- keywords -----------------------------------------------------
    kw_data = keywords_doc.get("data", {})
    for key, category in _CATEGORY_MAP.items():
        names = kw_data.get(key) or []
        conn.executemany(
            "INSERT OR IGNORE INTO keywords(name, category) VALUES(?, ?)",
            ((name, category) for name in names),
        )
        rows += len(names)
        progress(f"  keywords: {len(names)} {category}(s) from {key}")

    # ---- card types / subtypes ---------------------------------------
    ct_data = cardtypes_doc.get("data", {})
    for card_type, info in ct_data.items():
        supertypes = info.get("superTypes") or []
        subtypes = info.get("subTypes") or []
        conn.execute(
            "INSERT OR REPLACE INTO card_types(type, supertypes) VALUES(?, ?)",
            (card_type, json.dumps(supertypes)),
        )
        rows += 1
        conn.executemany(
            "INSERT OR IGNORE INTO card_subtypes(card_type, subtype) VALUES(?, ?)",
            ((card_type, subtype) for subtype in subtypes),
        )
        rows += len(subtypes)
    progress(f"  card types: {len(ct_data)} types loaded")

    # ---- meta ----------------------------------------------------------
    meta = keywords_doc.get("meta") or cardtypes_doc.get("meta") or {}
    version = meta.get("version")
    if version:
        set_meta(conn, f"{NAME}.version", str(version))
    set_meta(conn, f"{NAME}.updated_at", utcnow_iso())

    result.rows = rows
    result.detail = f"{rows} vocabulary rows (keywords + card types)"
    return result
