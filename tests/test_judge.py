"""DeterministicJudge behaviour, including the table-authoritative principle."""

from __future__ import annotations

from gavel.agents import Prediction
from gavel.bank import BankItem, render_answer
from gavel.db import SQLiteDatabase
from gavel.judge import DeterministicJudge


def make_item(gold_sql: str, db: SQLiteDatabase, *, question: str = "q?") -> BankItem:
    return BankItem(
        id="item",
        tier="basic",
        question=question,
        gold_sql=gold_sql,
        gold_answer=render_answer(db.execute(gold_sql)),
    )


class TestVerdicts:
    def test_equivalent_sql_passes(self, mini_db: SQLiteDatabase) -> None:
        item = make_item("SELECT COUNT(*) FROM band;", mini_db)
        verdict = DeterministicJudge(mini_db).judge(
            item, Prediction(sql="select count(band_id) as n from band", answer_text="3 bands")
        )
        assert verdict.score == 1
        assert verdict.table_match is True

    def test_wrong_filter_fails(self, mini_db: SQLiteDatabase) -> None:
        item = make_item("SELECT COUNT(*) FROM song WHERE price = 0.99;", mini_db)
        verdict = DeterministicJudge(mini_db).judge(
            item, Prediction(sql="SELECT COUNT(*) FROM song WHERE price = 1.29", answer_text="")
        )
        assert verdict.score == 0
        assert verdict.table_match is False

    def test_broken_agent_sql_is_a_clear_fail(self, mini_db: SQLiteDatabase) -> None:
        item = make_item("SELECT COUNT(*) FROM band;", mini_db)
        verdict = DeterministicJudge(mini_db).judge(
            item, Prediction(sql="SELEC COUNT(*) FROM band", answer_text="3")
        )
        assert verdict.score == 0
        assert "failed to execute" in verdict.rationale

    def test_missing_sql_goes_to_manual_review(self, mini_db: SQLiteDatabase) -> None:
        item = make_item("SELECT COUNT(*) FROM band;", mini_db)
        verdict = DeterministicJudge(mini_db).judge(item, Prediction(sql="", answer_text="3"))
        assert verdict.score == -1
        assert "manual review" in verdict.rationale

    def test_broken_gold_sql_goes_to_manual_review(self, mini_db: SQLiteDatabase) -> None:
        item = BankItem(
            id="bad-gold",
            tier="basic",
            question="q?",
            gold_sql="SELECT * FROM no_such_table",
            gold_answer="whatever",
        )
        verdict = DeterministicJudge(mini_db).judge(
            item, Prediction(sql="SELECT COUNT(*) FROM band", answer_text="3")
        )
        assert verdict.score == -1
        assert "gold SQL failed" in verdict.rationale

    def test_row_order_enforced_for_ordered_gold(self, mini_db: SQLiteDatabase) -> None:
        item = make_item(
            "SELECT name FROM band ORDER BY name;", mini_db, question="bands alphabetical"
        )
        verdict = DeterministicJudge(mini_db).judge(
            item, Prediction(sql="SELECT name FROM band ORDER BY name DESC", answer_text="")
        )
        assert verdict.score == 0

    def test_row_order_free_for_unordered_gold(self, mini_db: SQLiteDatabase) -> None:
        item = make_item("SELECT name FROM band;", mini_db, question="all bands")
        verdict = DeterministicJudge(mini_db).judge(
            item, Prediction(sql="SELECT name FROM band ORDER BY name DESC", answer_text="")
        )
        assert verdict.score == 1


class TestTableAuthoritative:
    """Returned table data is authoritative over prose, in both directions."""

    def test_matching_table_with_nonsense_prose_still_passes(
        self, mini_db: SQLiteDatabase
    ) -> None:
        item = make_item("SELECT COUNT(*) FROM band;", mini_db)
        verdict = DeterministicJudge(mini_db).judge(
            item,
            Prediction(
                sql="SELECT COUNT(*) FROM band",
                answer_text="I believe there might be hundreds of bands, hard to say.",
            ),
        )
        assert verdict.score == 1
        assert "authoritative" in verdict.rationale

    def test_wrong_table_with_perfect_prose_still_fails(
        self, mini_db: SQLiteDatabase
    ) -> None:
        item = make_item("SELECT COUNT(*) FROM band;", mini_db)  # gold answer: "3"
        verdict = DeterministicJudge(mini_db).judge(
            item,
            Prediction(
                sql="SELECT COUNT(*) FROM record",  # returns 4, not 3
                answer_text=item.gold_answer,  # prose parrots the gold answer exactly
            ),
        )
        assert verdict.score == 0
        assert "authoritative" in verdict.rationale

    def test_similarity_is_recorded_but_never_decisive(
        self, mini_db: SQLiteDatabase
    ) -> None:
        item = make_item("SELECT COUNT(*) FROM band;", mini_db)
        verdict = DeterministicJudge(mini_db).judge(
            item, Prediction(sql="SELECT COUNT(*) FROM band", answer_text="3")
        )
        assert verdict.score == 1
        assert verdict.text_similarity is not None
