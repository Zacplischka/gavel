"""Agent clients: predictions loading and the (transport-stubbed) live agent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gavel.agents import (
    ClaudeCLIAgent,
    Prediction,
    PredictionsError,
    StaticAgent,
    load_predictions,
)
from gavel.bank import BankItem

ITEM = BankItem(
    id="q1", tier="basic", question="How many bands?", gold_sql="SELECT 1;", gold_answer="1"
)


class TestLoadPredictions:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "preds.jsonl"
        path.write_text(
            json.dumps({"id": "q1", "sql": "SELECT 1", "answer_text": "one"}) + "\n",
            encoding="utf-8",
        )
        predictions = load_predictions(path)
        assert predictions == {"q1": Prediction(sql="SELECT 1", answer_text="one")}

    def test_missing_fields_default_to_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "preds.jsonl"
        path.write_text(json.dumps({"id": "q1"}) + "\n", encoding="utf-8")
        assert load_predictions(path)["q1"] == Prediction(sql="", answer_text="")

    def test_duplicate_id_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "preds.jsonl"
        line = json.dumps({"id": "q1", "sql": "SELECT 1"})
        path.write_text(line + "\n" + line + "\n", encoding="utf-8")
        with pytest.raises(PredictionsError, match="duplicate"):
            load_predictions(path)

    def test_missing_id_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "preds.jsonl"
        path.write_text(json.dumps({"sql": "SELECT 1"}) + "\n", encoding="utf-8")
        with pytest.raises(PredictionsError, match="id"):
            load_predictions(path)


class TestStaticAgent:
    def test_replays_by_id(self) -> None:
        agent = StaticAgent({"q1": Prediction(sql="SELECT 1", answer_text="one")})
        assert agent.answer(ITEM).sql == "SELECT 1"

    def test_missing_id_is_empty_not_error(self) -> None:
        agent = StaticAgent({})
        assert agent.answer(ITEM) == Prediction(sql="", answer_text="")


class TestClaudeCLIAgent:
    def test_prompt_embeds_schema_and_question(self) -> None:
        agent = ClaudeCLIAgent("CREATE TABLE band (...)", transport=lambda p: "{}")
        prompt = agent.build_prompt(ITEM)
        assert "CREATE TABLE band" in prompt
        assert ITEM.question in prompt

    def test_parses_json_response(self) -> None:
        raw = 'Here you go:\n```json\n{"sql": "SELECT 1", "answer_text": "one"}\n```'
        agent = ClaudeCLIAgent("schema", transport=lambda p: raw)
        assert agent.answer(ITEM) == Prediction(sql="SELECT 1", answer_text="one")

    def test_unparseable_response_yields_empty_sql(self) -> None:
        agent = ClaudeCLIAgent("schema", transport=lambda p: "sorry, no JSON")
        prediction = agent.answer(ITEM)
        assert prediction.sql == ""  # judged -1 downstream, not a crash
