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
    download_file,
    http_get_json,
    set_meta,
    utcnow_iso,
)

NAME = "spellbook"

# Bulk static export (a single CDN file, not subject to the API's per-request
# rate limit). Preferred source; the paginated API is the fallback.
BULK_URL = "https://json.commanderspellbook.com/variants.json"
_MIN_BULK_OK = 500  # fewer than this from the bulk file -> treat as bad, fall back

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

# Polite pause between page requests (seconds). Tests monkeypatch http_get_json,
# but this keeps the real crawl under Commander Spellbook's rate limit.
PAGE_PAUSE = 0.2


def _pace() -> None:
    import time
    time.sleep(PAGE_PAUSE)


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


def _first(d: dict, *keys, default=None):
    """First present, non-None value among camelCase/snake_case key aliases."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _prerequisites(variant: dict) -> str | None:
    """Join the notable/easy prerequisite fields and template-requirement notes."""
    parts: list[str] = []
    for key in ("notablePrerequisites", "notable_prerequisites",
                "easyPrerequisites", "easy_prerequisites", "otherPrerequisites"):
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
    if _first(use, "mustBeCommander", "must_be_commander"):
        return 1
    # A card whose only legal zone is the command zone must be the commander.
    if _first(use, "zoneLocations", "zone_locations") == ["C"]:
        return 1
    return 0


def _variant_to_rows(variant: dict):
    """Map one variant dict to (combo_row | None, [card_rows]). Tolerant of both
    the API's camelCase and the bulk file's field names. Returns (None, []) for
    non-OK variants."""
    status = variant.get("status")
    if status is not None and status != "OK":
        return None, []
    vid = variant.get("id")
    if vid is None:
        return None, []
    variant_id = str(vid)
    uses = variant.get("uses") or []
    produces = [
        feat["name"]
        for entry in (variant.get("produces") or [])
        if (feat := (entry.get("feature") or entry)) and feat.get("name")
    ]
    legalities = variant.get("legalities") or {}
    legal_commander = 1 if legalities.get("commander", True) else 0

    combo_row = (
        variant_id,
        variant.get("description"),
        _prerequisites(variant),
        json.dumps(produces),
        json.dumps(_normalize_identity(variant.get("identity"))),
        _first(variant, "manaNeeded", "mana_needed"),
        variant.get("popularity"),
        legal_commander,
        len(uses),
        COMBO_URI_TEMPLATE.format(id=variant_id),
    )

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
            per_card[name] = [variant_id, _first(card, "oracleId", "oracle_id"), quantity, mbc]
    card_rows = [
        (cid, name, oid, qty, mbc)
        for name, (cid, oid, qty, mbc) in per_card.items()
    ]
    return combo_row, card_rows


def _load_bulk(cache_dir: Path, force: bool, progress: Progress) -> list | None:
    """Download and parse the bulk variants file. Returns the variant list, or
    None if the download/parse fails (caller falls back to the API)."""
    progress("  spellbook: downloading bulk combo data…")
    dest = download_file(BULK_URL, cache_dir / "spellbook-variants.json", force=force, progress=progress)
    with open(dest, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("variants") or data.get("results") or []
    return None


def _crawl_api(result: IngestResult, progress: Progress) -> tuple[list, list, int]:
    """Paginated fallback. Resilient: on a mid-crawl error (e.g. a persistent
    rate limit) it keeps whatever it fetched instead of losing everything."""
    result.warnings.append(_SHAPE_WARNING)
    combo_rows: list[tuple] = []
    card_rows: list[tuple] = []
    skipped = 0
    url: str | None = START_URL
    page = 0
    total_pages = "?"
    while url:
        page += 1
        if page > 1:
            _pace()
        try:
            data = http_get_json(url)
        except Exception as exc:  # noqa: BLE001 — keep partial progress
            result.warnings.append(f"spellbook: stopped at page {page} ({exc}); kept {len(combo_rows)} combos")
            break
        if page == 1 and isinstance(data.get("count"), int):
            total_pages = str(max(1, math.ceil(data["count"] / PAGE_LIMIT)))
        if page == 1 or page % 25 == 0:
            progress(f"  spellbook: fetching page {page} / ~{total_pages}")
        for variant in data.get("results") or []:
            combo_row, crows = _variant_to_rows(variant)
            if combo_row is None:
                skipped += 1
                continue
            combo_rows.append(combo_row)
            card_rows.extend(crows)
        next_url = data.get("next")
        if next_url == url:
            break
        url = next_url
    return combo_rows, card_rows, skipped


def ingest(
    conn: sqlite3.Connection,
    cache_dir: Path,
    force: bool = False,
    progress: Progress = print,
) -> IngestResult:
    result = IngestResult(name=NAME)

    combo_rows: list[tuple] = []
    card_rows: list[tuple] = []
    skipped = 0
    source = None

    # 1) Preferred: the bulk static file (one download, no per-request limit).
    try:
        variants = _load_bulk(cache_dir, force, progress)
    except Exception as exc:  # noqa: BLE001
        variants = None
        result.warnings.append(f"spellbook: bulk download unavailable ({exc}); falling back to the API")
    if variants is not None and len(variants) >= _MIN_BULK_OK:
        for variant in variants:
            combo_row, crows = _variant_to_rows(variant)
            if combo_row is None:
                skipped += 1
                continue
            combo_rows.append(combo_row)
            card_rows.extend(crows)
        source = "bulk"
        progress(f"  spellbook: loaded {len(combo_rows)} combos from bulk data")
    else:
        if variants is not None:
            result.warnings.append(f"spellbook: bulk file had only {len(variants)} variants; using the API")

    # 2) Fallback: paginated API (resilient — keeps partial progress).
    if source is None:
        combo_rows, card_rows, skipped = _crawl_api(result, progress)
        source = "api"

    # Idempotent full refresh, but ONLY if we actually got data — never wipe an
    # existing combo table down to nothing on a failed refresh.
    if combo_rows:
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
        f"  spellbook: {len(combo_rows)} combos ({len(card_rows)} card rows) "
        f"from {source}; skipped {skipped} non-OK variant(s)"
    )
    result.rows = len(combo_rows)
    result.detail = f"{len(combo_rows)} combos via {source}, {skipped} skipped"
    if not combo_rows:
        result.detail = "no combos loaded (bulk + API both failed)"
    return result
