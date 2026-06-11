# ADR 0003 — Pluggable database adapters

## Status

Accepted

## Context

The production benchmarking framework this repo demonstrates patterns from
ran the same evaluation flow against multiple data warehouses through an
adapter layer, because the agents under test targeted different engines.
This public demo needs none of that weight — but losing the *seam* would
make the demo architecturally dishonest: the judge would grow
SQLite-specific assumptions that never survive contact with a second
engine.

## Decision

All execution flows through a two-method surface:

```python
class Database(Protocol):
    def execute(self, sql: str) -> QueryResult: ...

@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
```

The only adapter shipped is `SQLiteDatabase` (stdlib `sqlite3`, read-only
by default so agent SQL cannot mutate the evaluation database). The judge,
runner, and bank validator depend exclusively on the protocol; adding a
warehouse adapter means implementing `execute` and mapping engine errors to
`QueryError`, nothing else.

SQLite keeps the demo free, dependency-less, and runnable in CI — the
Chinook database is a 1 MB download.

## Consequences

- The judge's normalization layer is engine-neutral by construction.
- Engine-specific SQL dialect differences are NOT abstracted — a bank is
  written for one dialect. That matched production reality and stays true
  here.
