"""SQLite schema for the Deck Weaver knowledge base.

Conventions:
- Multi-valued fields (colors, keywords, produces, ...) are stored as JSON text
  arrays; query with SQLite's json_each().
- Full-text search uses FTS5. The cards FTS index is contentless-delete-free
  (external content) and is rebuilt by the Scryfall ingester after each load.
- The `meta` table records ingest timestamps and upstream data versions.
"""

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------------------------------------------------------- cards ----
CREATE TABLE IF NOT EXISTS cards (
    oracle_id        TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    layout           TEXT,
    mana_cost        TEXT,
    mana_value       REAL,
    type_line        TEXT,
    oracle_text      TEXT,
    colors           TEXT,   -- JSON array, e.g. ["W","U"]
    color_identity   TEXT,   -- JSON array
    keywords         TEXT,   -- JSON array of keyword names on this card
    produced_mana    TEXT,   -- JSON array
    power            TEXT,
    toughness        TEXT,
    loyalty          TEXT,
    defense          TEXT,
    card_faces       TEXT,   -- JSON array of face objects for multi-face cards
    legal_commander  TEXT,   -- 'legal' | 'not_legal' | 'banned' | 'restricted'
    legalities       TEXT,   -- JSON object of all format legalities
    is_game_changer  INTEGER NOT NULL DEFAULT 0,
    reserved         INTEGER NOT NULL DEFAULT 0,
    rarity           TEXT,
    set_code         TEXT,
    collector_number TEXT,
    released_at      TEXT,
    edhrec_rank      INTEGER,
    price_usd        REAL,
    price_usd_foil   REAL,
    price_eur        REAL,
    price_tix        REAL,
    scryfall_id      TEXT,
    scryfall_uri     TEXT,
    games            TEXT   -- JSON array, e.g. ["paper","mtgo","arena"]
);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_edhrec_rank ON cards(edhrec_rank);

CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name, type_line, oracle_text,
    content='cards', content_rowid='rowid'
);

-- ----------------------------------------------------- game vocabulary ----
CREATE TABLE IF NOT EXISTS keywords (
    name     TEXT NOT NULL,   -- e.g. 'Deathtouch'
    category TEXT NOT NULL,   -- 'ability' | 'action' | 'word'
    PRIMARY KEY (name, category)
);

CREATE TABLE IF NOT EXISTS card_types (
    type       TEXT PRIMARY KEY,  -- e.g. 'creature'
    supertypes TEXT               -- JSON array, e.g. ["Basic","Legendary"]
);

CREATE TABLE IF NOT EXISTS card_subtypes (
    card_type TEXT NOT NULL,      -- e.g. 'creature'
    subtype   TEXT NOT NULL,      -- e.g. 'Elf'
    PRIMARY KEY (card_type, subtype)
);

-- ----------------------------------------------------------------- rules ----
CREATE TABLE IF NOT EXISTS rules (
    rule_number TEXT PRIMARY KEY,  -- '601', '601.2', '601.2a'
    text        TEXT NOT NULL,
    parent      TEXT               -- '601.2a' -> '601.2' -> '601' -> NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS rules_fts USING fts5(rule_number, text);

CREATE TABLE IF NOT EXISTS glossary (
    term       TEXT PRIMARY KEY,
    definition TEXT NOT NULL
);

-- ---------------------------------------------------------------- combos ----
CREATE TABLE IF NOT EXISTS combos (
    id              TEXT PRIMARY KEY,   -- Commander Spellbook variant id
    description     TEXT,               -- step-by-step description
    prerequisites   TEXT,
    produces        TEXT,               -- JSON array of result names
    color_identity  TEXT,               -- JSON array
    mana_needed     TEXT,
    popularity      INTEGER,
    legal_commander INTEGER NOT NULL DEFAULT 1,
    card_count      INTEGER,
    spellbook_uri   TEXT
);

CREATE TABLE IF NOT EXISTS combo_cards (
    combo_id           TEXT NOT NULL,
    card_name          TEXT NOT NULL,
    oracle_id          TEXT,
    quantity           INTEGER NOT NULL DEFAULT 1,
    must_be_commander  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (combo_id, card_name)
);
CREATE INDEX IF NOT EXISTS idx_combo_cards_name ON combo_cards(card_name);

-- ------------------------------------------------------------- knowledge ----
CREATE TABLE IF NOT EXISTS card_tags (
    oracle_id TEXT NOT NULL,
    tag       TEXT NOT NULL,       -- taxonomy.py role tag, e.g. 'ramp.rock'
    quality   REAL NOT NULL DEFAULT 0.5,
    source    TEXT NOT NULL DEFAULT 'pattern',  -- 'pattern' | 'override'
    why       TEXT,
    PRIMARY KEY (oracle_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_card_tags_tag ON card_tags(tag);

-- ---------------------------------------------------------- format data ----
CREATE TABLE IF NOT EXISTS game_changers (
    name   TEXT PRIMARY KEY,
    source TEXT                -- e.g. 'wotc-2026-02-09'
);

CREATE TABLE IF NOT EXISTS brackets (
    number              INTEGER PRIMARY KEY,  -- 1..5
    name                TEXT NOT NULL,
    game_changer_limit  INTEGER,              -- NULL = unlimited
    description         TEXT NOT NULL
);
"""


# Columns added after v1 that must be back-filled onto existing databases
# (CREATE TABLE IF NOT EXISTS won't add columns to a table that already exists).
_ADDED_COLUMNS = {
    "cards": [("games", "TEXT")],
}


def _migrate_columns(conn) -> None:
    for table, cols in _ADDED_COLUMNS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def apply_schema(conn) -> None:
    """Create all tables/indexes if missing, migrate new columns, stamp version."""
    conn.executescript(SCHEMA_SQL)
    _migrate_columns(conn)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
