"""Verdict-normalization rules: cells, dates, floats, column/row order."""

from __future__ import annotations

from gavel.db import QueryResult
from gavel.judge import (
    cells_equal,
    normalize_cell,
    order_matters,
    tables_match,
    text_similarity,
)


def table(columns: tuple[str, ...], *rows: tuple[object, ...]) -> QueryResult:
    return QueryResult(columns=columns, rows=tuple(rows))


class TestNormalizeCell:
    def test_midnight_datetime_collapses_to_date(self) -> None:
        assert normalize_cell("2009-01-01 00:00:00") == "2009-01-01"
        assert normalize_cell("2009-01-01T00:00:00") == "2009-01-01"
        assert normalize_cell("2009-01-01T00:00:00.000") == "2009-01-01"

    def test_nonmidnight_datetime_unifies_separator(self) -> None:
        assert normalize_cell("2009-01-01T13:45:09") == "2009-01-01 13:45:09"
        assert normalize_cell("2009-01-01 13:45:09.123") == "2009-01-01 13:45:09"

    def test_numeric_strings_become_numbers(self) -> None:
        assert normalize_cell("42") == 42
        assert normalize_cell("-3.5") == -3.5
        assert normalize_cell(" 7 ") == 7

    def test_integral_floats_become_ints(self) -> None:
        assert normalize_cell(5.0) == 5
        assert isinstance(normalize_cell(5.0), int)

    def test_plain_strings_pass_through_stripped(self) -> None:
        assert normalize_cell("  Rock ") == "Rock"
        assert normalize_cell(None) is None


class TestCellsEqual:
    def test_float_tolerance(self) -> None:
        assert cells_equal(0.1 + 0.2, 0.3)
        assert cells_equal(2328.6, 2328.5999999999)
        assert not cells_equal(2328.6, 2328.7)

    def test_int_vs_float(self) -> None:
        assert cells_equal(5, 5.0)
        assert cells_equal("5", 5)

    def test_date_vs_datetime(self) -> None:
        assert cells_equal("2009-01-01", "2009-01-01 00:00:00")

    def test_strings_case_sensitive(self) -> None:
        assert not cells_equal("Rock", "rock")


class TestOrderMatters:
    def test_top_level_order_by(self) -> None:
        assert order_matters("SELECT a FROM t ORDER BY a")
        assert order_matters("select a from t order by a desc limit 5")

    def test_no_order_by(self) -> None:
        assert not order_matters("SELECT a FROM t WHERE a > 1")

    def test_order_by_in_subquery_only(self) -> None:
        assert not order_matters(
            "SELECT * FROM (SELECT a FROM t ORDER BY a LIMIT 3) sub"
        )

    def test_order_by_in_window_only(self) -> None:
        assert not order_matters(
            "SELECT a, RANK() OVER (ORDER BY a DESC) FROM t"
        )

    def test_order_by_inside_string_literal_ignored(self) -> None:
        assert not order_matters("SELECT a FROM t WHERE b = 'order by c'")


class TestTablesMatch:
    def test_identical(self) -> None:
        a = table(("x", "y"), (1, "a"), (2, "b"))
        assert tables_match(a, a, ordered=True)

    def test_column_order_insensitive(self) -> None:
        gold = table(("name", "n"), ("Rock", 10), ("Jazz", 5))
        swapped = table(("n", "name"), (10, "Rock"), (5, "Jazz"))
        assert tables_match(gold, swapped, ordered=True)

    def test_column_names_irrelevant(self) -> None:
        gold = table(("Customers",), (13,), (8,))
        renamed = table(("n_customers",), (13,), (8,))
        assert tables_match(gold, renamed, ordered=True)

    def test_row_order_insensitive_when_unordered(self) -> None:
        gold = table(("x",), (1,), (2,), (3,))
        shuffled = table(("x",), (3,), (1,), (2,))
        assert tables_match(gold, shuffled, ordered=False)

    def test_row_order_enforced_when_ordered(self) -> None:
        gold = table(("x",), (1,), (2,), (3,))
        shuffled = table(("x",), (3,), (1,), (2,))
        assert not tables_match(gold, shuffled, ordered=True)

    def test_float_tolerance_in_tables(self) -> None:
        gold = table(("v",), (0.3,))
        close = table(("v",), (0.1 + 0.2,))
        assert tables_match(gold, close, ordered=False)

    def test_date_normalization_in_tables(self) -> None:
        gold = table(("d",), ("2021-07-15",))
        verbose = table(("d",), ("2021-07-15 00:00:00",))
        assert tables_match(gold, verbose, ordered=False)

    def test_row_count_mismatch(self) -> None:
        assert not tables_match(table(("x",), (1,)), table(("x",), (1,), (2,)), ordered=False)

    def test_column_count_mismatch(self) -> None:
        assert not tables_match(
            table(("x",), (1,)), table(("x", "y"), (1, 2)), ordered=False
        )

    def test_empty_tables_match(self) -> None:
        assert tables_match(table(("x",)), table(("y",)), ordered=False)

    def test_different_values_fail(self) -> None:
        assert not tables_match(table(("x",), (1,)), table(("x",), (2,)), ordered=False)


class TestTextSimilarity:
    def test_identical(self) -> None:
        assert text_similarity("abc", "abc") == 1.0

    def test_containment_boost(self) -> None:
        assert text_similarity("2328.6", "total revenue is 2328.6 dollars") >= 0.95

    def test_unrelated(self) -> None:
        assert text_similarity("completely different", "2328.6") < 0.5
