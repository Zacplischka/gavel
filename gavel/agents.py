"""Agent clients: things that turn a question into ``{sql, answer_text}``.

``StaticAgent`` is the workhorse — it replays predictions recorded in a JSONL
file, which is how you evaluate *any* external agent with gavel: dump its
outputs and point the runner at the file. ``ClaudeCLIAgent`` is an optional
live agent, gated exactly like the live judge (see ADR 0004).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gavel.bank import BankItem
from gavel.llm import call_claude_cli, iter_json_objects


@dataclass(frozen=True)
class Prediction:
    """One agent output for one question."""

    sql: str
    answer_text: str


class AgentClient(Protocol):
    """Maps a bank item's question to a prediction.

    Live agents should only look at ``item.question`` (plus whatever schema
    context they were constructed with); replay agents may key on ``item.id``.
    """

    def answer(self, item: BankItem) -> Prediction: ...


class PredictionsError(Exception):
    """Raised when a predictions JSONL file is malformed."""


def load_predictions(path: str | Path) -> dict[str, Prediction]:
    """Load a predictions JSONL file: ``{"id", "sql", "answer_text"}`` per line."""
    predictions: dict[str, Prediction] = {}
    text = Path(path).read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PredictionsError(f"line {line_no}: invalid JSON ({exc})") from exc
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise PredictionsError(f"line {line_no}: expected an object with a string 'id'")
        item_id = str(record["id"])
        if item_id in predictions:
            raise PredictionsError(f"line {line_no}: duplicate id {item_id!r}")
        predictions[item_id] = Prediction(
            sql=str(record.get("sql", "")),
            answer_text=str(record.get("answer_text", "")),
        )
    return predictions


class StaticAgent:
    """Replays recorded predictions keyed by bank-item id.

    Items missing from the file yield an empty prediction, which the
    deterministic judge scores ``-1`` (manual review) — absence of an answer
    is not the same as a wrong answer.
    """

    def __init__(self, predictions: dict[str, Prediction]) -> None:
        self._predictions = predictions

    @classmethod
    def from_jsonl(cls, path: str | Path) -> StaticAgent:
        return cls(load_predictions(path))

    def answer(self, item: BankItem) -> Prediction:
        return self._predictions.get(item.id, Prediction(sql="", answer_text=""))


AGENT_PROMPT_TEMPLATE = """\
You are a text-to-SQL agent for a SQLite database.

Database schema:
{schema}

Question: {question}

Write one SQLite query that answers the question, then answer in one short
sentence. Respond with ONLY a JSON object, no prose around it:
{{"sql": "<the query>", "answer_text": "<one-sentence answer>"}}
"""


class ClaudeCLIAgent:
    """OPTIONAL live agent: generates SQL with the local ``claude`` CLI.

    Never used by default; requires explicitly selecting ``--agent claude-cli``
    on the command line. Each question is one model call — cost is on you.
    """

    def __init__(
        self,
        schema: str,
        *,
        model: str | None = None,
        command: str = "claude",
        transport: Callable[[str], str] | None = None,
    ) -> None:
        self._schema = schema
        if transport is None:

            def transport(prompt: str) -> str:
                return call_claude_cli(prompt, model=model, command=command)

        self._transport = transport

    def build_prompt(self, item: BankItem) -> str:
        return AGENT_PROMPT_TEMPLATE.format(schema=self._schema, question=item.question)

    def answer(self, item: BankItem) -> Prediction:
        raw = self._transport(self.build_prompt(item))
        for obj in iter_json_objects(raw):
            if "sql" in obj:
                return Prediction(
                    sql=str(obj.get("sql", "")),
                    answer_text=str(obj.get("answer_text", "")),
                )
        # Unparseable output -> empty prediction -> judged -1 (manual review).
        return Prediction(sql="", answer_text=raw.strip())
