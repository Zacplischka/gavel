"""Judges: score an agent prediction against a gold answer.

Verdicts are three-valued (see ADR 0001):

* ``1``  — correct
* ``0``  — incorrect
* ``-1`` — cannot be scored automatically; goes to the manual-review queue

The offline default is :class:`DeterministicJudge` (ADR 0002): it executes
both the agent SQL and the gold SQL against the live local database and
compares the *result tables* under normalization. Returned table data is
authoritative over prose — if the tables match, divergent answer text cannot
fail the item, and if the tables differ, convincing answer text cannot pass
it.

:class:`LLMJudge` (ADR 0004) is optional, explicitly gated, and never used
by tests or default CLI flows.
"""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from gavel.agents import Prediction
from gavel.bank import BankItem
from gavel.db import Database, QueryError, QueryResult
from gavel.llm import call_anthropic_api, call_claude_cli, iter_json_objects

Score = Literal[1, 0, -1]

#: Text similarity below this is flagged as "prose diverges" in rationales.
LOW_SIMILARITY = 0.5
#: Text similarity above this is flagged as "prose looks right" on failures.
HIGH_SIMILARITY = 0.9


@dataclass(frozen=True)
class Verdict:
    """A judge's decision plus a structured rationale."""

    score: Score
    rationale: str
    table_match: bool | None = None
    text_similarity: float | None = None


class Judge(Protocol):
    def judge(self, item: BankItem, prediction: Prediction) -> Verdict: ...


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_DATETIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.\d+)?$")
_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def normalize_cell(value: object) -> object:
    """Normalize one result cell for comparison.

    * datetime strings with a midnight time collapse to their date part
      (``2009-01-01T00:00:00`` == ``2009-01-01``)
    * other datetime strings unify the ``T``/space separator and drop
      fractional seconds
    * numeric strings become numbers (``"42"`` == ``42``)
    * integral floats become ints (``5.0`` == ``5``)
    * surrounding whitespace on strings is ignored
    """
    if isinstance(value, str):
        s = value.strip()
        m = _DATETIME_RE.match(s)
        if m:
            date_part, time_part = m.group(1), m.group(2)
            return date_part if time_part == "00:00:00" else f"{date_part} {time_part}"
        if _NUMERIC_RE.match(s):
            try:
                as_float = float(s)
            except ValueError:  # pragma: no cover - regex guards this
                return s
            return normalize_cell(as_float)
        return s
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def cells_equal(a: object, b: object) -> bool:
    """Compare two cells after normalization, with float tolerance."""
    na, nb = normalize_cell(a), normalize_cell(b)
    if isinstance(na, int | float) and isinstance(nb, int | float):
        return math.isclose(float(na), float(nb), rel_tol=1e-6, abs_tol=1e-9)
    return na == nb


def _cell_sort_key(value: object) -> tuple[int, str]:
    """A stable, comparison-compatible sort key for a normalized cell."""
    v = normalize_cell(value)
    if v is None:
        return (0, "")
    if isinstance(v, int | float):
        return (1, f"{float(v):.9e}")
    return (2, str(v))


def order_matters(sql: str) -> bool:
    """True if ``sql`` has a top-level ORDER BY (presentation order is part
    of the contract); ORDER BY inside subqueries or window frames is ignored.
    """
    cleaned = _strip_strings_and_comments(sql)
    depth = 0
    lowered = cleaned.lower()
    for match in re.finditer(r"[()]|order\s+by", lowered):
        token = match.group(0)
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            return True
    return False


def _strip_strings_and_comments(sql: str) -> str:
    """Replace string literals/comments with spaces, preserving length."""
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and not (j + 1 < n and sql[j + 1] == "'"):
                    break
                j += 2 if sql[j] == "'" else 1
            out.append(" " * (min(j, n - 1) - i + 1))
            i = min(j, n - 1) + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(" " * (j - i))
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _canonical_rows(result: QueryResult) -> list[tuple[object, ...]]:
    """Reorder columns into a canonical permutation (sorted by the column's
    values) so that column order — and column *names* — don't affect
    comparison. Row order is preserved.
    """
    ncols = len(result.columns)
    if ncols == 0 or not result.rows:
        return list(result.rows)
    column_keys = [
        tuple(_cell_sort_key(row[i]) for row in result.rows) for i in range(ncols)
    ]
    perm = sorted(range(ncols), key=lambda i: column_keys[i])
    return [tuple(row[i] for i in perm) for row in result.rows]


def tables_match(gold: QueryResult, actual: QueryResult, *, ordered: bool) -> bool:
    """Compare two result tables under normalization.

    * column order and column names never matter (columns are matched by
      content, not by header)
    * row order matters only when ``ordered`` is True (gold SQL has a
      top-level ORDER BY)
    * floats compare with tolerance; dates and numeric strings normalize
    """
    if gold.row_count != actual.row_count:
        return False
    if len(gold.columns) != len(actual.columns):
        return False
    gold_rows = _canonical_rows(gold)
    actual_rows = _canonical_rows(actual)
    if not ordered:
        def row_key(row: tuple[object, ...]) -> tuple[tuple[int, str], ...]:
            return tuple(_cell_sort_key(cell) for cell in row)

        gold_rows = sorted(gold_rows, key=row_key)
        actual_rows = sorted(actual_rows, key=row_key)
    return all(
        cells_equal(g, a)
        for g_row, a_row in zip(gold_rows, actual_rows, strict=True)
        for g, a in zip(g_row, a_row, strict=True)
    )


def text_similarity(a: str, b: str) -> float:
    """Cheap prose similarity in [0, 1] — advisory only, never decisive.

    Uses a sequence ratio, boosted when one side is wholly contained in the
    other (a gold answer like ``2328.6`` quoted inside a prose sentence).
    """
    a_n, b_n = a.lower().strip(), b.lower().strip()
    ratio = difflib.SequenceMatcher(None, a_n, b_n).ratio()
    shorter, longer = sorted((a_n, b_n), key=len)
    if len(shorter) >= 2 and shorter in longer:
        ratio = max(ratio, 0.95)
    return ratio


# ---------------------------------------------------------------------------
# Deterministic judge (offline default)
# ---------------------------------------------------------------------------


class DeterministicJudge:
    """Executes agent SQL and gold SQL, compares result tables.

    Table data is authoritative over prose: the prose similarity score only
    ever annotates the rationale, it never changes the verdict.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def judge(self, item: BankItem, prediction: Prediction) -> Verdict:
        similarity: float | None = None
        if prediction.answer_text.strip() and item.gold_answer.strip():
            similarity = text_similarity(prediction.answer_text, item.gold_answer)

        if not prediction.sql.strip():
            return Verdict(
                score=-1,
                rationale=(
                    "no SQL provided; cannot verify against the database -> manual review"
                ),
                table_match=None,
                text_similarity=similarity,
            )

        try:
            gold_result = self._db.execute(item.gold_sql)
        except QueryError as exc:
            return Verdict(
                score=-1,
                rationale=(
                    f"gold SQL failed to execute ({exc}); ambiguous — the bank item "
                    "itself needs review -> manual review"
                ),
                table_match=None,
                text_similarity=similarity,
            )

        try:
            agent_result = self._db.execute(prediction.sql)
        except QueryError as exc:
            return Verdict(
                score=0,
                rationale=f"agent SQL failed to execute: {exc}",
                table_match=False,
                text_similarity=similarity,
            )

        ordered = order_matters(item.gold_sql)
        match = tables_match(gold_result, agent_result, ordered=ordered)

        if match:
            rationale = "result table matches gold" + (
                " (row order verified; gold has top-level ORDER BY)" if ordered else ""
            )
            if similarity is not None and similarity < LOW_SIMILARITY:
                rationale += (
                    f"; answer prose diverges (similarity={similarity:.2f}) but table "
                    "data is authoritative over prose -> pass"
                )
            return Verdict(1, rationale, table_match=True, text_similarity=similarity)

        rationale = "result table does not match gold"
        if ordered:
            rationale += " (row order enforced; gold has top-level ORDER BY)"
        if similarity is not None and similarity >= HIGH_SIMILARITY:
            rationale += (
                f"; answer prose looks right (similarity={similarity:.2f}) but table "
                "data is authoritative over prose -> fail"
            )
        return Verdict(0, rationale, table_match=False, text_similarity=similarity)


# ---------------------------------------------------------------------------
# Optional LLM judge
# ---------------------------------------------------------------------------

JUDGE_PROMPT_TEMPLATE = """\
You are an exacting SQL evaluation judge. Decide whether the agent's SQL and
answer are semantically equivalent to the gold SQL and answer for this
question. Be deterministic and conservative: identical inputs must always
produce identical verdicts. Do not give credit for confident prose.

Rubric — these differences are ACCEPTABLE (still a pass):
- formatting, whitespace, capitalisation of keywords
- table/column aliasing, quoting style, column order in SELECT
- equivalent join syntax (explicit JOIN vs WHERE-clause join)
- CURRENT_DATE / now() vs an equivalent hardcoded current date
- equivalent aggregate spellings (COUNT(*) vs COUNT(1) vs COUNT(pk))

These differences are FAILURES:
- wrong tables, wrong join keys, missing or extra joins
- wrong filters (WHERE/HAVING), wrong aggregation or grouping
- missing DISTINCT where duplicates change the result
- wrong sort direction or missing ORDER BY when the question requires order
- a result that answers a different question

If you cannot determine equivalence from the information given, use verdict -1.

Question: {question}

Gold SQL:
{gold_sql}

Gold answer:
{gold_answer}

Agent SQL:
{agent_sql}

Agent answer:
{agent_answer}

Respond with ONLY a JSON object on one line, no markdown, no commentary:
{{"verdict": 1 | 0 | -1, "rationale": "<one or two sentences>"}}
"""


def build_judge_prompt(item: BankItem, prediction: Prediction) -> str:
    return JUDGE_PROMPT_TEMPLATE.format(
        question=item.question,
        gold_sql=item.gold_sql,
        gold_answer=item.gold_answer,
        agent_sql=prediction.sql or "(none provided)",
        agent_answer=prediction.answer_text or "(none provided)",
    )


def _coerce_score(value: object) -> Score | None:
    if isinstance(value, bool):
        return None
    numeric: float | None = None
    if isinstance(value, int | float):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return None
    if numeric == 1.0:
        return 1
    if numeric == 0.0:
        return 0
    if numeric == -1.0:
        return -1
    return None


def parse_judge_response(raw: str) -> Verdict:
    """Extract a verdict from messy LLM output.

    Tolerates code fences, surrounding prose, and stringified scores. If no
    well-formed verdict can be found, returns ``-1`` (manual review) rather
    than guessing — an unparseable judge is an unusable judge.
    """
    obj: dict[str, Any]
    for obj in iter_json_objects(raw):
        if "verdict" in obj:
            score = _coerce_score(obj["verdict"])
            if score is not None:
                rationale = str(obj.get("rationale", "")).strip() or "(no rationale given)"
                return Verdict(score=score, rationale=rationale)
    snippet = " ".join(raw.split())[:200]
    return Verdict(
        score=-1,
        rationale=f"could not parse judge response -> manual review; raw output: {snippet!r}",
    )


class LLMJudge:
    """OPTIONAL semantic judge. Requires an explicit backend choice and never
    runs unless selected with ``--judge llm`` (see ADR 0004).

    Backends:
      * ``claude-cli``     — subprocess ``claude -p`` (local CLI session)
      * ``anthropic-api``  — stdlib-urllib call using ``ANTHROPIC_API_KEY``
    """

    def __init__(
        self,
        *,
        backend: Literal["claude-cli", "anthropic-api"] = "claude-cli",
        model: str | None = None,
        command: str = "claude",
        transport: Callable[[str], str] | None = None,
    ) -> None:
        if transport is None:
            if backend == "claude-cli":

                def transport(prompt: str) -> str:
                    return call_claude_cli(prompt, model=model, command=command)

            elif backend == "anthropic-api":

                def transport(prompt: str) -> str:
                    return call_anthropic_api(prompt, model=model)

            else:  # pragma: no cover - typing forbids it
                raise ValueError(f"unknown LLM judge backend: {backend!r}")
        self._transport = transport

    def judge(self, item: BankItem, prediction: Prediction) -> Verdict:
        raw = self._transport(build_judge_prompt(item, prediction))
        return parse_judge_response(raw)
