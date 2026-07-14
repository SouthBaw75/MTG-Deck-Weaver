"""Commander Spellbook combo-database ingester.

Mirrors the /variants/ REST API at https://backend.commanderspellbook.com/
into the `combos` and `combo_cards` tables.

API shape note: direct requests to backend.commanderspellbook.com are blocked
from this build environment (HTTP 403), so the response shape below was
verified against the open-source backend instead
(https://github.com/SpaceCowMedia/commander-spellbook-backend):

- Django REST Framework LimitOffsetPagination envelope:
  {"count": int?, "next": url|null, "previous": url|null, "results": [...]}
  ("count" is only guaranteed when requested; we never rely on it and simply
  follow "next" until null.)
- The backend renders JSON with CamelCaseJSONRenderer, so per-variant fields
  are camelCase on the wire: id, status, uses[], requires[], produces[],
  identity, manaNeeded, manaValueNeeded, easyPrerequisites,
  notablePrerequisites, description, notes, popularity, spoiler, bracketTag,
  legalities{commander, ...}, prices, variantCount.
- uses[] items: {card: {id, name, oracleId, ...}, zoneLocations: ["B"|"H"|
  "C"|"G"|"L"|"E"], mustBeCommander, quantity, *CardState}.
- requires[] items: {template: {id, name, scryfallQuery, ...}, ...same}.
- produces[] items: {feature: {id, name, ...}, quantity}.
- Variant.Status public values are 'OK' and 'E' (example); example variants
  carry null description/prerequisites, so only 'OK' variants are stored.
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

from weaver.ingest.base import (
    IngestResult,
    Progress,
    http_get_json,
    set_meta,
    utcnow_iso,
)

NAME = "spellbook"

API_ROOT = "https://backend.commanderspellbook.com/variants/"
PAGE_LIMIT = 100
# 'created' is one of the view's allowed ordering fields and is effectively
# append-only, which keeps limit/offset pagination stable during a crawl.
START_URL = f"{API_ROOT}?limit={PAGE_LIMIT}&format=json&ordering=created"

COMBO_URI_TEMPLATE = "https://commanderspellbook.com/combo/{id}/"

# Wire-shape assumption warning (see module docstring): emitted once per run.
_SHAPE_WARNING = (
    "spellbook: live API unreachable at build time; response shape verified "
    "against the open-source backend (SpaceCowMedia/commander-spellbook-backend), "
    "not a live response"
)

_IDENTITY_LETTERS = ("W", "U", "B", "R", "G", "C")


def _normalize_identity(identity) -> list[str]:
    """Normalize the API's `identity` into a JSON-ready list of single letters.

    The live API sends a compact string like "WUB" or "C"; be tolerant of a
    list form (["W", "U"]) or comma-separated string as well.
    """
    if identity is None:
        return []
    parts = identity if isinstance(identity, (list, tuple)) else [identity]
    seen: list[str] = []
    for part in parts:
        for ch in str(part).upper():
            if ch in _IDENTITY_LETTERS and ch not in seen:
                seen.append(ch)
    # Present in canonical WUBRG(C) order regardless of input order.
    return [ch for ch in _IDENTITY_LETTERS if ch in seen]


def _prerequisites(variant: dict) -> str | None:
    """Join the notable/easy prerequisite fields and template-requirement notes."""
    parts: list[str] = []
    for key in ("notablePrerequisites", "easyPrerequisites", "otherPrerequisites"):
        text = variant.get(key)
        if text:
            parts.append(str(text).strip())
    # Generic template requirements ("A free sacrifice outlet", ...) have no
    # concrete card; keep the combo but note the requirement.
    for req in variant.get("requires") or []:
        template_name = (req.get("template") or {}).get("name")
        if template_name:
            parts.append(f"[requires: {template_name}]")
    return "\n".join(parts) or None


def _must_be_commander(use: dict) -> int:
    if use.get("mustBeCommander"):
        return 1
    # A card whose only legal zone is the command zone must be the commander.
    if use.get("zoneLocations") == ["C"]:
        return 1
    return 0


def ingest(
    conn: sqlite3.Connection,
    cache_dir: Path,
    force: bool = False,
    progress: Progress = print,
) -> IngestResult:
    result = IngestResult(name=NAME)
    result.warnings.append(_SHAPE_WARNING)

    combo_rows: list[tuple] = []
    card_rows: list[tuple] = []
    skipped = 0

    url: str | None = START_URL
    page = 0
    total_pages = "?"
    while url:
        page += 1
        data = http_get_json(url)
        if page == 1 and isinstance(data.get("count"), int):
            total_pages = str(max(1, math.ceil(data["count"] / PAGE_LIMIT)))
        if page == 1 or page % 25 == 0:
            progress(f"  spellbook: fetching page {page} / ~{total_pages}")

        for variant in data.get("results") or []:
            status = variant.get("status")
            if status is not None and status != "OK":
                skipped += 1
                continue

            variant_id = str(variant["id"])
            uses = variant.get("uses") or []
            produces = [
                feature["name"]
                for entry in variant.get("produces") or []
                if (feature := entry.get("feature") or {}).get("name")
            ]
            legalities = variant.get("legalities") or {}
            legal_commander = 1 if legalities.get("commander", True) else 0

            combo_rows.append(
                (
                    variant_id,
                    variant.get("description"),
                    _prerequisites(variant),
                    json.dumps(produces),
                    json.dumps(_normalize_identity(variant.get("identity"))),
                    variant.get("manaNeeded"),
                    variant.get("popularity"),
                    legal_commander,
                    len(uses),
                    COMBO_URI_TEMPLATE.format(id=variant_id),
                )
            )

            # Aggregate by card name: (combo_id, card_name) is the PK.
            per_card: dict[str, list] = {}
            for use in uses:
                card = use.get("card") or {}
                name = card.get("name")
                if not name:
                    continue
                quantity = use.get("quantity") or 1
                mbc = _must_be_commander(use)
                if name in per_card:
                    per_card[name][2] += quantity
                    per_card[name][3] = max(per_card[name][3], mbc)
                else:
                    per_card[name] = [variant_id, card.get("oracleId"), quantity, mbc]
            card_rows.extend(
                (combo_id, name, oracle_id, quantity, mbc)
                for name, (combo_id, oracle_id, quantity, mbc) in per_card.items()
            )

        next_url = data.get("next")
        if next_url == url:  # defensive: never loop on a broken cursor
            result.warnings.append(f"spellbook: 'next' did not advance at page {page}")
            break
        url = next_url

    # Idempotent full refresh: these tables are wholly owned by this ingester.
    conn.execute("DELETE FROM combo_cards")
    conn.execute("DELETE FROM combos")
    conn.executemany(
        "INSERT INTO combos(id, description, prerequisites, produces,"
        " color_identity, mana_needed, popularity, legal_commander,"
        " card_count, spellbook_uri) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        combo_rows,
    )
    conn.executemany(
        "INSERT INTO combo_cards(combo_id, card_name, oracle_id, quantity,"
        " must_be_commander) VALUES(?, ?, ?, ?, ?)",
        card_rows,
    )

    set_meta(conn, f"{NAME}.updated_at", utcnow_iso())
    set_meta(conn, f"{NAME}.count", str(len(combo_rows)))

    progress(
        f"  spellbook: {len(combo_rows)} combos ({len(card_rows)} card rows)"
        f" from {page} page(s); skipped {skipped} non-OK variant(s)"
    )
    result.rows = len(combo_rows)
    result.detail = (
        f"{len(combo_rows)} combos from {page} page(s), {skipped} skipped"
    )
    return result
