"""Run a question bank through an agent and a judge."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gavel.agents import AgentClient, Prediction
from gavel.bank import TIERS, BankItem
from gavel.judge import Judge, Score, Verdict


@dataclass(frozen=True)
class ItemResult:
    item: BankItem
    prediction: Prediction
    verdict: Verdict


@dataclass(frozen=True)
class TierStats:
    tier: str
    total: int
    passed: int
    failed: int
    review: int

    @property
    def accuracy(self) -> float | None:
        """Pass rate among automatically judged items (excludes -1)."""
        judged = self.passed + self.failed
        return None if judged == 0 else self.passed / judged


@dataclass(frozen=True)
class RunResult:
    results: tuple[ItemResult, ...]

    def count(self, score: Score) -> int:
        return sum(1 for r in self.results if r.verdict.score == score)

    @property
    def accuracy(self) -> float | None:
        judged = self.count(1) + self.count(0)
        return None if judged == 0 else self.count(1) / judged

    @property
    def strict_accuracy(self) -> float | None:
        """Pass rate over ALL items — manual-review items count as not-passed."""
        return None if not self.results else self.count(1) / len(self.results)

    def tier_stats(self) -> list[TierStats]:
        stats: list[TierStats] = []
        for tier in TIERS:
            tier_results = [r for r in self.results if r.item.tier == tier]
            if not tier_results:
                continue
            stats.append(
                TierStats(
                    tier=tier,
                    total=len(tier_results),
                    passed=sum(1 for r in tier_results if r.verdict.score == 1),
                    failed=sum(1 for r in tier_results if r.verdict.score == 0),
                    review=sum(1 for r in tier_results if r.verdict.score == -1),
                )
            )
        return stats

    def failures(self) -> list[ItemResult]:
        return [r for r in self.results if r.verdict.score == 0]

    def review_queue(self) -> list[ItemResult]:
        return [r for r in self.results if r.verdict.score == -1]


def run_bank(items: list[BankItem], agent: AgentClient, judge: Judge) -> RunResult:
    """Evaluate every bank item: ask the agent, then score with the judge.

    An agent that *raises* yields a ``-1`` verdict (manual review) rather
    than aborting the run — one broken question should not cost the report.
    """
    results: list[ItemResult] = []
    for item in items:
        try:
            prediction = agent.answer(item)
        except Exception as exc:
            prediction = Prediction(sql="", answer_text="")
            verdict = Verdict(
                score=-1,
                rationale=f"agent raised {type(exc).__name__}: {exc} -> manual review",
            )
            results.append(ItemResult(item=item, prediction=prediction, verdict=verdict))
            continue
        results.append(
            ItemResult(item=item, prediction=prediction, verdict=judge.judge(item, prediction))
        )
    return RunResult(results=tuple(results))


# ---------------------------------------------------------------------------
# (De)serialization so `gavel report` can re-render saved runs
# ---------------------------------------------------------------------------


def run_result_to_dict(run: RunResult) -> dict[str, Any]:
    return {
        "results": [
            {
                "item": {
                    "id": r.item.id,
                    "tier": r.item.tier,
                    "question": r.item.question,
                    "gold_sql": r.item.gold_sql,
                    "gold_answer": r.item.gold_answer,
                },
                "prediction": {
                    "sql": r.prediction.sql,
                    "answer_text": r.prediction.answer_text,
                },
                "verdict": {
                    "score": r.verdict.score,
                    "rationale": r.verdict.rationale,
                    "table_match": r.verdict.table_match,
                    "text_similarity": r.verdict.text_similarity,
                },
            }
            for r in run.results
        ]
    }


def _score_from(value: object) -> Score:
    if value == 1:
        return 1
    if value == 0:
        return 0
    if value == -1:
        return -1
    raise ValueError(f"invalid verdict score in results file: {value!r}")


def run_result_from_dict(data: dict[str, Any]) -> RunResult:
    results: list[ItemResult] = []
    for entry in data["results"]:
        item = BankItem(**entry["item"])
        prediction = Prediction(**entry["prediction"])
        v = entry["verdict"]
        verdict = Verdict(
            score=_score_from(v["score"]),
            rationale=str(v["rationale"]),
            table_match=v.get("table_match"),
            text_similarity=v.get("text_similarity"),
        )
        results.append(ItemResult(item=item, prediction=prediction, verdict=verdict))
    return RunResult(results=tuple(results))


def save_run(run: RunResult, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(run_result_to_dict(run), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_run(path: str | Path) -> RunResult:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return run_result_from_dict(data)
