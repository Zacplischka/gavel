"""Shared fixtures.

Unit tests run against a synthetic 3-table mini database built in-test via
stdlib ``sqlite3`` — no download required. Tests marked ``chinook`` need the
real Chinook database (``python -m gavel fetch``) and skip cleanly without it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from gavel.bank import BankItem, render_answer
from gavel.db import SQLiteDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
BANK_PATH = REPO_ROOT / "data" / "chinook_bank.jsonl"
CHINOOK_PATH = REPO_ROOT / "data" / "Chinook_Sqlite.sqlite"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

requires_chinook = pytest.mark.chinook


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if CHINOOK_PATH.exists():
        return
    skip = pytest.mark.skip(reason="Chinook database not fetched (run `python -m gavel fetch`)")
    for item in items:
        if "chinook" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def mini_db_path(tmp_path: Path) -> Path:
    """Build a tiny synthetic 3-table music database (band/record/song)."""
    path = tmp_path / "mini.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE band (band_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE record (
            record_id INTEGER PRIMARY KEY,
            band_id INTEGER NOT NULL REFERENCES band(band_id),
            title TEXT NOT NULL,
            released TEXT
        );
        CREATE TABLE song (
            song_id INTEGER PRIMARY KEY,
            record_id INTEGER NOT NULL REFERENCES record(record_id),
            title TEXT NOT NULL,
            seconds REAL NOT NULL,
            price REAL NOT NULL
        );

        INSERT INTO band VALUES (1, 'The Nulls'), (2, 'Sigma Quartet'), (3, 'Off By One');
        INSERT INTO record VALUES
            (1, 1, 'Empty Set',      '2020-03-01 00:00:00'),
            (2, 1, 'Null Island',    '2021-07-15 00:00:00'),
            (3, 2, 'Four Sigmas',    '2019-11-30 00:00:00'),
            (4, 3, 'Boundary Cases', '2022-01-01 00:00:00');
        INSERT INTO song VALUES
            (1, 1, 'Zero Rows',     181.5, 0.99),
            (2, 1, 'Vacuous Truth', 240.0, 0.99),
            (3, 2, 'No Mans Atoll', 199.25, 1.29),
            (4, 2, 'Latitude Zero', 320.75, 1.29),
            (5, 3, 'First Moment',  150.0, 0.99),
            (6, 3, 'Second Moment', 210.0, 0.99),
            (7, 3, 'Third Moment',  330.5, 1.29),
            (8, 4, 'Fencepost',     265.0, 0.99);
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def mini_db(mini_db_path: Path) -> Iterator[SQLiteDatabase]:
    with SQLiteDatabase(mini_db_path) as db:
        yield db


@pytest.fixture
def mini_bank(mini_db: SQLiteDatabase) -> list[BankItem]:
    """A small bank over the mini DB; gold answers derived by execution."""
    specs = [
        ("q1", "basic", "How many bands are there?", "SELECT COUNT(*) FROM band;"),
        (
            "q2",
            "easy",
            "How many songs cost 0.99?",
            "SELECT COUNT(*) FROM song WHERE price = 0.99;",
        ),
        (
            "q3",
            "medium",
            "How many songs does each band have? Most songs first.",
            "SELECT b.name, COUNT(*) AS n FROM song s "
            "JOIN record r ON s.record_id = r.record_id "
            "JOIN band b ON r.band_id = b.band_id "
            "GROUP BY b.band_id ORDER BY n DESC, b.name;",
        ),
        (
            "q4",
            "hard",
            "Which record has the highest total song runtime?",
            "SELECT r.title FROM song s JOIN record r ON s.record_id = r.record_id "
            "GROUP BY r.record_id ORDER BY SUM(s.seconds) DESC LIMIT 1;",
        ),
    ]
    return [
        BankItem(
            id=item_id,
            tier=tier,
            question=question,
            gold_sql=sql,
            gold_answer=render_answer(mini_db.execute(sql)),
        )
        for item_id, tier, question, sql in specs
    ]
