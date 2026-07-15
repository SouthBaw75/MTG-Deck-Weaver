"""FastAPI application: the local web API + static frontend host.

Create with create_app(db_path). Endpoints under /api/*; everything else is
served from the bundled static frontend (src/weaver/web/static). The splash
art is served from the repo's assets/ directory.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from weaver.db import apply_schema, connect
from weaver.db.connection import repo_root
from weaver.web.serialize import (
    analysis_to_dict,
    build_result_to_dict,
    card_to_dict,
)

STATIC_DIR = Path(__file__).parent / "static"


class AnalyzeBody(BaseModel):
    decklist: str


class BuildBody(BaseModel):
    commander: str
    partner: str | None = None
    bracket: int = 3
    budget: float | None = None
    theme: str | None = None
    owned: list[str] | None = None


class DeckSaveBody(BaseModel):
    name: str
    decklist: str
    commander: str | None = None
    bracket: int | None = None
    notes: str | None = None
    id: int | None = None  # present -> update that deck


class DeckRenameBody(BaseModel):
    name: str


def create_app(db_path: str | None = None, decks_db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="MTG Deck Weaver", version="0.1.0")

    def db():
        conn = connect(db_path)
        apply_schema(conn)
        return conn

    def decks_db():
        from weaver.decks.store import connect_decks
        return connect_decks(decks_db_path)

    def _require_cards(conn):
        if conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0:
            raise HTTPException(503, "Knowledge base is empty — run `weaver update` first.")

    # ---- API ---------------------------------------------------------------
    @app.get("/api/stats")
    def stats():
        conn = db()
        tables = ["cards", "keywords", "rules", "combos", "game_changers", "card_tags"]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        meta = {
            r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM meta WHERE key LIKE '%.updated_at'")
        }
        return {"counts": counts, "updated": meta}

    @app.get("/api/archetypes")
    def archetypes():
        try:
            from weaver.build.archetypes import load_archetypes
            return [{"key": a["key"], "name": a["name"], "description": a.get("description", "")}
                    for a in load_archetypes()]
        except Exception:
            return []

    @app.get("/api/card/{name}")
    def card(name: str):
        conn = db()
        _require_cards(conn)
        row = conn.execute("SELECT * FROM cards WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM cards WHERE name LIKE ? COLLATE NOCASE ORDER BY edhrec_rank LIMIT 1",
                (f"%{name}%",),
            ).fetchone()
        if row is None:
            raise HTTPException(404, f"No card matching {name!r}")
        return card_to_dict(conn, row)

    @app.get("/api/search")
    def search(q: str, limit: int = 15, kind: str = "any"):
        """Name search. kind='commander' restricts to commander-eligible cards
        (legendary creatures or cards that say they can be your commander);
        kind='partner' additionally allows Backgrounds."""
        conn = db()
        _require_cards(conn)
        where = ["name LIKE ? COLLATE NOCASE"]
        params: list = [f"%{q}%"]
        if kind in ("commander", "partner"):
            # CR 903.3: a legendary creature, or a card that can be your commander.
            clause = (
                "((type_line LIKE '%Legendary%' AND type_line LIKE '%Creature%')"
                " OR oracle_text LIKE '%can be your commander%'"
            )
            if kind == "partner":
                clause += " OR type_line LIKE '%Background%'"
            clause += ")"
            where.append(clause)
        rows = conn.execute(
            f"SELECT name FROM cards WHERE {' AND '.join(where)} "
            "ORDER BY (edhrec_rank IS NULL), edhrec_rank LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [r["name"] for r in rows]

    @app.post("/api/analyze")
    def analyze(body: AnalyzeBody):
        from weaver.analysis.engine import analyze_deck
        from weaver.analysis.loader import load_deck

        conn = db()
        _require_cards(conn)
        deck = load_deck(conn, body.decklist)
        return analysis_to_dict(deck, analyze_deck(deck))

    @app.post("/api/build")
    def build(body: BuildBody):
        from weaver.analysis.engine import analyze_deck
        from weaver.analysis.loader import load_deck
        from weaver.build.builder import build_deck
        from weaver.build.types import BuildRequest

        conn = db()
        _require_cards(conn)
        request = BuildRequest(
            commander=body.commander, partner=body.partner, bracket=body.bracket,
            budget=body.budget, theme=body.theme,
            owned=set(body.owned) if body.owned else None,
        )
        try:
            result = build_deck(conn, request)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        payload = build_result_to_dict(result)
        deck = load_deck(conn, payload["decklist"])
        payload["validation"] = analysis_to_dict(deck, analyze_deck(deck))
        return payload

    # ---- saved decks -------------------------------------------------------
    def _deck_row(row) -> dict:
        from weaver.analysis.deck import parse_decklist
        entries = parse_decklist(row["decklist"])
        return {
            "id": row["id"],
            "name": row["name"],
            "commander": row["commander"],
            "bracket": row["bracket"],
            "notes": row["notes"] if "notes" in row.keys() else None,
            "card_count": sum(e.quantity for e in entries),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @app.get("/api/decks")
    def decks_list():
        from weaver.decks.store import list_decks
        return [_deck_row(r) for r in list_decks(decks_db())]

    @app.post("/api/decks")
    def decks_save(body: DeckSaveBody):
        from weaver.decks.store import save_deck
        try:
            did = save_deck(
                decks_db(), name=body.name, decklist=body.decklist,
                commander=body.commander, bracket=body.bracket, notes=body.notes,
                deck_id=body.id,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {"id": did}

    @app.get("/api/decks/{deck_id}")
    def decks_get(deck_id: int):
        from weaver.decks.store import get_deck
        row = get_deck(decks_db(), deck_id)
        if row is None:
            raise HTTPException(404, f"no deck with id {deck_id}")
        d = _deck_row(row)
        d["decklist"] = row["decklist"]
        return d

    @app.put("/api/decks/{deck_id}")
    def decks_rename(deck_id: int, body: DeckRenameBody):
        from weaver.decks.store import rename_deck
        try:
            rename_deck(decks_db(), deck_id, body.name)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {"id": deck_id, "name": body.name}

    @app.delete("/api/decks/{deck_id}")
    def decks_delete(deck_id: int):
        from weaver.decks.store import delete_deck
        if not delete_deck(decks_db(), deck_id):
            raise HTTPException(404, f"no deck with id {deck_id}")
        return {"deleted": deck_id}

    # ---- static frontend ---------------------------------------------------
    @app.get("/splash.png")
    def splash():
        p = repo_root() / "assets" / "splash.png"
        if not p.exists():
            raise HTTPException(404, "splash not found")
        return FileResponse(p)

    @app.get("/splash-portrait.png")
    def splash_portrait():
        p = repo_root() / "assets" / "splash-portrait.png"
        if not p.exists():
            # Fall back to the landscape art if the portrait isn't present.
            p = repo_root() / "assets" / "splash.png"
        if not p.exists():
            raise HTTPException(404, "splash not found")
        return FileResponse(p)

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app
