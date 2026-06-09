"""Storage backends. Pluggable: SQLite for MVP, Postgres later."""

from gazelle.stores.sqlite import SQLiteStore

__all__ = ["SQLiteStore"]
