"""Bank loading/validation and gold-answer re-derivation against Chinook."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from gavel.bank import (
    BankError,
    load_bank,
    render_answer,
    validate_bank,
)
from gavel.db import QueryResult, SQLiteDatabase
from tests.conftest import BANK_PATH, CHINOOK_PATH, requires_chinook


def write_bank(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


GOOD: dict[str, object] = {
    "id": "x1",
    "tier": "basic",
    "question": "q?",
    "gold_sql": "SELECT 1;",
    "gold_answer": "1",
}


class TestLoadBank:
    def test_loads_the_committed_bank(self) -> None:
        items = load_bank(BANK_PATH)
        assert len(items) == 24
        tiers = {item.tier for item in items}
        assert tiers == {"basic", "easy", "medium", "hard"}
        # 6 per tier
        for tier in tiers:
            assert sum(1 for i in items if i.tier == tier) == 6

    def test_rejects_bad_tier(self, tmp_path: Path) -> None:
        path = write_bank(tmp_path / "bank.jsonl", [{**GOOD, "tier": "nightmare"}])
        with pytest.raises(BankError, match="tier"):
            load_bank(path)

    def test_rejects_duplicate_ids(self, tmp_path: Path) -> None:
        path = write_bank(tmp_path / "bank.jsonl", [GOOD, GOOD])
        with pytest.raises(BankError, match="duplicate"):
            load_bank(path)

    def test_rejects_missing_field(self, tmp_path: Path) -> None:
        record = {k: v for k, v in GOOD.items() if k != "gold_sql"}
        path = write_bank(tmp_path / "bank.jsonl", [record])
        with pytest.raises(BankError, match="gold_sql"):
            load_bank(path)

    def test_rejects_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bank.jsonl"
        path.write_text("{broken\n", encoding="utf-8")
        with pytest.raises(BankError, match="invalid JSON"):
            load_bank(path)

    def test_rejects_empty_bank(self, tmp_path: Path) -> None:
        path = tmp_path / "bank.jsonl"
        path.write_text("\n", encoding="utf-8")
        with pytest.raises(BankError, match="empty"):
            load_bank(path)


class TestRenderAnswer:
    def test_single_cell(self) -> None:
        assert render_answer(QueryResult(("n",), ((275,),))) == "275"

    def test_float_formatting(self) -> None:
        assert render_answer(QueryResult(("v",), ((2328.6,),))) == "2328.6"
        assert render_answer(QueryResult(("v",), ((5.0,),))) == "5"

    def test_null(self) -> None:
        assert render_answer(QueryResult(("v",), ((None,),))) == "NULL"

    def test_empty(self) -> None:
        assert render_answer(QueryResult(("v",), ())) == "(no rows)"

    def test_multi_row_table(self) -> None:
        result = QueryResult(("name", "n"), (("Rock", 10), ("Jazz", 5)))
        assert render_answer(result) == "name | n\nRock | 10\nJazz | 5"


@requires_chinook
class TestGoldAnswersAgainstChinook:
    """Every gold SQL must execute against the real Chinook database and the
    stored gold answer must equal the re-derived answer. This is the test the
    bank can never drift past."""

    def test_every_gold_answer_rederives(self) -> None:
        items = load_bank(BANK_PATH)
        with SQLiteDatabase(CHINOOK_PATH) as db:
            problems = validate_bank(items, db)
        assert problems == []

    def test_validate_bank_reports_drift(self) -> None:
        items = load_bank(BANK_PATH)
        drifted = [dataclasses.replace(items[0], gold_answer="999999")]
        with SQLiteDatabase(CHINOOK_PATH) as db:
            problems = validate_bank(drifted, db)
        assert len(problems) == 1
        assert "does not match" in problems[0]
