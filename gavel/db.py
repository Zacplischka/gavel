"""Pluggable database adapters.

The harness talks to databases through the :class:`Database` protocol so the
judge and runner never depend on a concrete engine. This repo ships a single
stdlib-``sqlite3`` adapter (the demo runs on the public Chinook database);
see ``docs/adr/0003-pluggable-db-adapters.md`` for why the seam exists.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol


class QueryError(Exception):
    """Raised when a query cannot be executed against the database."""


@dataclass(frozen=True)
class QueryResult:
    """A fully materialised result table: column names plus row tuples."""

    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)


class Database(Protocol):
    """Anything that can execute SQL and hand back a result table."""

    def execute(self, sql: str) -> QueryResult:
        """Execute ``sql`` and return the result table.

        Implementations must raise :class:`QueryError` for any execution
        failure so callers never need engine-specific exception types.
        """
        ...


class SQLiteDatabase:
    """:class:`Database` adapter over stdlib ``sqlite3``.

    Opens the file read-only by default so agent-supplied SQL cannot mutate
    the evaluation database.
    """

    def __init__(self, path: str | Path, *, readonly: bool = True) -> None:
        self._path = Path(path)
        self._readonly = readonly
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self._path.exists():
                raise QueryError(f"database file not found: {self._path}")
            if self._readonly:
                self._conn = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
            else:
                self._conn = sqlite3.connect(self._path)
        return self._conn

    def execute(self, sql: str) -> QueryResult:
        try:
            cursor = self._connection().execute(sql)
            rows = tuple(tuple(row) for row in cursor.fetchall())
            description = cursor.description or ()
            columns = tuple(str(d[0]) for d in description)
        except sqlite3.Error as exc:
            raise QueryError(str(exc)) from exc
        return QueryResult(columns=columns, rows=rows)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SQLiteDatabase:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def schema_dump(db: Database) -> str:
    """Return the CREATE TABLE statements of a SQLite database as one string.

    Used to build schema prompts for live agents.
    """
    result = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL ORDER BY name"
    )
    return "\n\n".join(str(row[0]) for row in result.rows)
