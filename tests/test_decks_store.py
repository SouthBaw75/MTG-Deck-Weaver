"""Saved-deck store tests."""

from __future__ import annotations

import pytest

from weaver.decks.store import (
    connect_decks,
    delete_deck,
    get_deck,
    list_decks,
    rename_deck,
    save_deck,
)

DECKLIST = "Commander\n1 Meren of Clan Nel Toth\nDeck\n1 Sol Ring\n"


@pytest.fixture()
def db(tmp_path):
    return connect_decks(tmp_path / "decks.db")


def test_save_and_get(db):
    did = save_deck(db, name="My Meren", decklist=DECKLIST, commander="Meren of Clan Nel Toth", bracket=3)
    row = get_deck(db, did)
    assert row["name"] == "My Meren"
    assert row["commander"] == "Meren of Clan Nel Toth"
    assert row["bracket"] == 3
    assert row["decklist"] == DECKLIST
    assert row["created_at"] and row["updated_at"]


def test_list_orders_by_updated_desc(db):
    a = save_deck(db, name="A", decklist=DECKLIST)
    b = save_deck(db, name="B", decklist=DECKLIST)
    save_deck(db, name="A (edited)", decklist=DECKLIST, deck_id=a)  # touch A
    names = [r["name"] for r in list_decks(db)]
    assert names[0] == "A (edited)"  # most recently updated first
    assert set(names) == {"A (edited)", "B"}
    assert len(names) == 2


def test_update_existing(db):
    did = save_deck(db, name="v1", decklist=DECKLIST)
    save_deck(db, name="v2", decklist=DECKLIST + "1 Cultivate\n", deck_id=did)
    row = get_deck(db, did)
    assert row["name"] == "v2"
    assert "Cultivate" in row["decklist"]
    assert len(list_decks(db)) == 1  # updated, not duplicated


def test_rename(db):
    did = save_deck(db, name="old", decklist=DECKLIST)
    rename_deck(db, did, "new")
    assert get_deck(db, did)["name"] == "new"


def test_delete(db):
    did = save_deck(db, name="temp", decklist=DECKLIST)
    assert delete_deck(db, did) is True
    assert get_deck(db, did) is None
    assert delete_deck(db, did) is False  # already gone


def test_blank_name_defaults(db):
    did = save_deck(db, name="   ", decklist=DECKLIST)
    assert get_deck(db, did)["name"] == "Untitled deck"


def test_update_missing_raises(db):
    with pytest.raises(KeyError):
        save_deck(db, name="x", decklist=DECKLIST, deck_id=999)
