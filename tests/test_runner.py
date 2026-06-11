"""Runner end-to-end on the synthetic mini database."""

from __future__ import annotations

import json
from pathlib import Path

from gavel.agents import Prediction, StaticAgent
from gavel.bank import BankItem
from gavel.db import SQLiteDatabase
from gavel.judge import DeterministicJudge
from gavel.runner import load_run, run_bank, save_run


def write_predictions(path: Path, records: list[dict[str, str]]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def test_end_to_end_on_mini_db(
    mini_db: SQLiteDatabase, mini_bank: list[BankItem], tmp_path: Path
) -> None:
    predictions = write_predictions(
        tmp_path / "preds.jsonl",
        [
            # q1: equivalent SQL -> pass
            {"id": "q1", "sql": "select count(band_id) from band", "answer_text": "3"},
            # q2: wrong filter -> fail
            {"id": "q2", "sql": "SELECT COUNT(*) FROM song WHERE price = 1.29", "answer_text": ""},
            # q3: matches incl. ORDER BY -> pass
            {
                "id": "q3",
                "sql": (
                    "SELECT COUNT(*) AS songs, b.name AS band FROM song s "
                    "JOIN record r ON s.record_id = r.record_id "
                    "JOIN band b ON r.band_id = b.band_id "
                    "GROUP BY b.band_id ORDER BY songs DESC, band"
                ),
                "answer_text": "Off By One leads with 3 songs.",
            },
            # q4 omitted -> empty prediction -> manual review (-1)
        ],
    )
    agent = StaticAgent.from_jsonl(predictions)
    run = run_bank(mini_bank, agent, DeterministicJudge(mini_db))

    assert len(run.results) == 4
    assert run.count(1) == 2
    assert run.count(0) == 1
    assert run.count(-1) == 1
    assert run.accuracy == 2 / 3
    assert run.strict_accuracy == 0.5

    by_tier = {s.tier: s for s in run.tier_stats()}
    assert by_tier["basic"].passed == 1
    assert by_tier["easy"].failed == 1
    assert by_tier["hard"].review == 1
    assert by_tier["easy"].accuracy == 0.0

    # round-trip through the results file
    out = tmp_path / "results.json"
    save_run(run, out)
    loaded = load_run(out)
    assert loaded == run


def test_agent_exception_becomes_manual_review(
    mini_db: SQLiteDatabase, mini_bank: list[BankItem]
) -> None:
    class ExplodingAgent:
        def answer(self, item: BankItem) -> Prediction:
            raise RuntimeError("kaboom")

    run = run_bank(mini_bank[:1], ExplodingAgent(), DeterministicJudge(mini_db))
    assert run.count(-1) == 1
    assert "kaboom" in run.results[0].verdict.rationale


def test_static_agent_missing_id_yields_empty_prediction(mini_bank: list[BankItem]) -> None:
    agent = StaticAgent({})
    prediction = agent.answer(mini_bank[0])
    assert prediction == Prediction(sql="", answer_text="")
