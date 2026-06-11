"""LLM-judge JSON parsing, including the recorded real-response fixture."""

from __future__ import annotations

from gavel.agents import Prediction
from gavel.bank import BankItem
from gavel.judge import LLMJudge, build_judge_prompt, parse_judge_response
from gavel.llm import iter_json_objects
from tests.conftest import FIXTURES

ITEM = BankItem(
    id="e4",
    tier="easy",
    question="How many distinct billing countries appear on invoices?",
    gold_sql="SELECT COUNT(DISTINCT BillingCountry) FROM Invoice;",
    gold_answer="24",
)
PREDICTION = Prediction(
    sql="SELECT COUNT(BillingCountry) FROM Invoice",
    answer_text="Invoices were billed to 412 countries.",
)


class TestRecordedFixture:
    """Regression test against one real `claude -p` judge response, recorded
    verbatim (code fence included) in tests/fixtures/llm_judge_response.txt."""

    def test_parses_recorded_response(self) -> None:
        raw = (FIXTURES / "llm_judge_response.txt").read_text(encoding="utf-8")
        verdict = parse_judge_response(raw)
        assert verdict.score == 0
        assert "DISTINCT" in verdict.rationale

    def test_llm_judge_with_recorded_transport(self) -> None:
        raw = (FIXTURES / "llm_judge_response.txt").read_text(encoding="utf-8")
        judge = LLMJudge(transport=lambda prompt: raw)
        verdict = judge.judge(ITEM, PREDICTION)
        assert verdict.score == 0


class TestParseJudgeResponse:
    def test_clean_json(self) -> None:
        verdict = parse_judge_response('{"verdict": 1, "rationale": "equivalent"}')
        assert verdict.score == 1
        assert verdict.rationale == "equivalent"

    def test_fenced_json(self) -> None:
        raw = 'Sure! Here is my verdict:\n```json\n{"verdict": -1, "rationale": "unclear"}\n```'
        assert parse_judge_response(raw).score == -1

    def test_prose_around_json(self) -> None:
        raw = 'Thinking... {"note": "ignore me"} final: {"verdict": 0, "rationale": "wrong join"}'
        verdict = parse_judge_response(raw)
        assert verdict.score == 0
        assert verdict.rationale == "wrong join"

    def test_stringified_verdict(self) -> None:
        assert parse_judge_response('{"verdict": "1", "rationale": "ok"}').score == 1

    def test_float_verdict(self) -> None:
        assert parse_judge_response('{"verdict": 1.0, "rationale": "ok"}').score == 1

    def test_invalid_score_value_goes_to_review(self) -> None:
        verdict = parse_judge_response('{"verdict": 2, "rationale": "??"}')
        assert verdict.score == -1
        assert "could not parse" in verdict.rationale

    def test_garbage_goes_to_review(self) -> None:
        verdict = parse_judge_response("I refuse to answer in JSON today.")
        assert verdict.score == -1
        assert "manual review" in verdict.rationale

    def test_missing_rationale_gets_placeholder(self) -> None:
        verdict = parse_judge_response('{"verdict": 1}')
        assert verdict.rationale == "(no rationale given)"


class TestIterJsonObjects:
    def test_braces_inside_strings(self) -> None:
        raw = '{"verdict": 1, "rationale": "the {weird} case"}'
        objs = list(iter_json_objects(raw))
        assert objs == [{"verdict": 1, "rationale": "the {weird} case"}]

    def test_multiple_objects(self) -> None:
        raw = '{"a": 1} text {"b": 2}'
        assert list(iter_json_objects(raw)) == [{"a": 1}, {"b": 2}]

    def test_unparseable_spans_skipped(self) -> None:
        raw = "{not json} {\"ok\": true}"
        assert list(iter_json_objects(raw)) == [{"ok": True}]


class TestPrompt:
    def test_prompt_contains_all_parts(self) -> None:
        prompt = build_judge_prompt(ITEM, PREDICTION)
        assert ITEM.question in prompt
        assert ITEM.gold_sql in prompt
        assert PREDICTION.sql in prompt
        assert "CURRENT_DATE" in prompt  # the rubric is embedded

    def test_empty_prediction_is_marked(self) -> None:
        prompt = build_judge_prompt(ITEM, Prediction(sql="", answer_text=""))
        assert "(none provided)" in prompt
