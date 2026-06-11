"""Report rendering."""

from __future__ import annotations

from gavel.agents import Prediction
from gavel.bank import BankItem
from gavel.judge import Score, Verdict
from gavel.report import render_report
from gavel.runner import ItemResult, RunResult


def make_result(item_id: str, tier: str, score: Score, rationale: str = "because") -> ItemResult:
    return ItemResult(
        item=BankItem(
            id=item_id,
            tier=tier,
            question=f"question {item_id}?",
            gold_sql="SELECT 1;",
            gold_answer="1",
        ),
        prediction=Prediction(sql="SELECT 1", answer_text="one"),
        verdict=Verdict(score=score, rationale=rationale),
    )


def test_report_sections_and_numbers() -> None:
    run = RunResult(
        results=(
            make_result("a", "basic", 1),
            make_result("b", "basic", 0, rationale="wrong join"),
            make_result("c", "hard", -1, rationale="no SQL provided"),
            make_result("d", "hard", 1),
        )
    )
    report = render_report(run, title="demo run")

    assert report.startswith("# demo run")
    assert "- **Items:** 4" in report
    assert "- **Pass:** 2" in report
    assert "- **Fail:** 1" in report
    assert "- **Manual review (verdict -1):** 1" in report
    assert "66.7%" in report  # accuracy over judged items (2 of 3)
    assert "50.0%" in report  # strict accuracy (2 of 4)

    # tier table rows
    assert "| basic | 2 | 1 | 1 | 0 | 50.0% |" in report
    assert "| hard | 2 | 1 | 0 | 1 | 100.0% |" in report

    # failure list carries the rationale
    assert "### `b` (basic)" in report
    assert "wrong join" in report

    # manual-review queue is its own section, not folded into pass/fail
    assert "## Manual-review queue" in report
    assert "`c` (hard)" in report
    assert "no SQL provided" in report


def test_report_with_no_failures_or_reviews() -> None:
    run = RunResult(results=(make_result("a", "easy", 1),))
    report = render_report(run)
    assert "No failures." in report
    assert "Empty — every item was scored automatically." in report
    assert "100.0%" in report


def test_report_all_review_has_na_accuracy() -> None:
    run = RunResult(results=(make_result("a", "easy", -1),))
    report = render_report(run)
    assert "n/a" in report
