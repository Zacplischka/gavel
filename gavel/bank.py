"""Question bank: curated questions with gold SQL and gold answers.

The bank is a JSONL file; each line is one :class:`BankItem`. Gold answers
are *derived* from gold SQL — ``validate_bank`` re-executes every gold query
and checks the stored answer still matches, so the bank can never silently
drift from the database it claims to describe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from gavel.db import Database, QueryError, QueryResult

TIERS: tuple[str, ...] = ("basic", "easy", "medium", "hard")


class BankError(Exception):
    """Raised when the question bank file is malformed."""


@dataclass(frozen=True)
class BankItem:
    id: str
    question: str
    gold_sql: str
    gold_answer: str
    tier: str


def format_cell(value: object) -> str:
    """Canonical human-readable rendering of a single result cell."""
    if value is None:
        return "NULL"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def render_answer(result: QueryResult) -> str:
    """Canonical rendering of a result table as an answer string.

    Single-cell results render as the bare value; anything larger renders as
    a header line plus one ``a | b | c`` line per row. ``validate_bank`` and
    the gold-answer re-derivation test both rely on this being deterministic.
    """
    if not result.rows:
        return "(no rows)"
    if len(result.rows) == 1 and len(result.columns) == 1:
        return format_cell(result.rows[0][0])
    lines = [" | ".join(result.columns)]
    lines.extend(" | ".join(format_cell(cell) for cell in row) for row in result.rows)
    return "\n".join(lines)


def _require_str(record: dict[str, object], key: str, line_no: int) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BankError(f"line {line_no}: field {key!r} must be a non-empty string")
    return value


def load_bank(path: str | Path) -> list[BankItem]:
    """Load and structurally validate a bank JSONL file."""
    items: list[BankItem] = []
    seen_ids: set[str] = set()
    text = Path(path).read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BankError(f"line {line_no}: invalid JSON ({exc})") from exc
        if not isinstance(record, dict):
            raise BankError(f"line {line_no}: expected a JSON object")
        item = BankItem(
            id=_require_str(record, "id", line_no),
            question=_require_str(record, "question", line_no),
            gold_sql=_require_str(record, "gold_sql", line_no),
            gold_answer=_require_str(record, "gold_answer", line_no),
            tier=_require_str(record, "tier", line_no),
        )
        if item.tier not in TIERS:
            raise BankError(f"line {line_no}: tier {item.tier!r} not in {TIERS}")
        if item.id in seen_ids:
            raise BankError(f"line {line_no}: duplicate id {item.id!r}")
        seen_ids.add(item.id)
        items.append(item)
    if not items:
        raise BankError(f"{path}: bank is empty")
    return items


def validate_bank(items: list[BankItem], db: Database) -> list[str]:
    """Execute every gold SQL and verify the stored gold answer matches.

    Returns a list of human-readable problems (empty list = bank is sound).
    """
    problems: list[str] = []
    for item in items:
        try:
            result = db.execute(item.gold_sql)
        except QueryError as exc:
            problems.append(f"{item.id}: gold SQL failed to execute: {exc}")
            continue
        derived = render_answer(result)
        if derived != item.gold_answer:
            problems.append(
                f"{item.id}: stored gold answer does not match re-derived answer "
                f"(stored={item.gold_answer!r}, derived={derived!r})"
            )
    return problems


def rederive_answers(items: list[BankItem], db: Database) -> list[BankItem]:
    """Return a copy of the bank with gold answers re-derived from gold SQL."""
    updated: list[BankItem] = []
    for item in items:
        result = db.execute(item.gold_sql)
        updated.append(
            BankItem(
                id=item.id,
                question=item.question,
                gold_sql=item.gold_sql,
                gold_answer=render_answer(result),
                tier=item.tier,
            )
        )
    return updated


def save_bank(items: list[BankItem], path: str | Path) -> None:
    """Write a bank back to JSONL (used by ``validate-bank --update-answers``)."""
    lines = [
        json.dumps(
            {
                "id": item.id,
                "tier": item.tier,
                "question": item.question,
                "gold_sql": item.gold_sql,
                "gold_answer": item.gold_answer,
            },
            ensure_ascii=False,
        )
        for item in items
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
