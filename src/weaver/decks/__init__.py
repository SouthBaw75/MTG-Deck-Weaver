"""Saved-deck storage — the user's personal deck library.

Kept in a database file separate from the card knowledge base so decks are never
touched when the card data is rebuilt by `weaver update`.
"""

from weaver.decks.store import (
    connect_decks,
    default_decks_path,
    delete_deck,
    get_deck,
    list_decks,
    rename_deck,
    save_deck,
)

__all__ = [
    "connect_decks",
    "default_decks_path",
    "delete_deck",
    "get_deck",
    "list_decks",
    "rename_deck",
    "save_deck",
]
