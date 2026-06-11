# gavel

An LLM-as-a-judge evaluation harness for text-to-SQL agents, scoring agent
answers against curated gold answers on the public
[Chinook](https://github.com/lerocha/chinook-database) sample database
(MIT licensed).

> **What this is, honestly:** This is a standalone demonstration on a public
> dataset of evaluation patterns from a production agent-benchmarking
> framework I built. It is not that system and contains none of its code or
> data. There are no third-party benchmark results, no client names, and no
> claims about other products anywhere in this repo.

## Why the evaluation design is the product

A single aggregate accuracy number lies about a text-to-SQL agent in three
distinct ways, and each design choice here closes one of them:

1. **It hides *where* the agent breaks.** An agent at "75%" that aces
   lookups and fails every multi-join aggregation is a very different tool
   from one failing uniformly. Every bank question carries a difficulty
   tier (`basic` / `easy` / `medium` / `hard`) and the report is
   stratified by tier.
2. **It can be talked into a pass by confident prose.** The default judge
   executes both the agent's SQL and the gold SQL against the live database
   and compares **result tables** under normalization. Returned table data
   is authoritative over prose — a matching table passes despite nonsense
   prose, and a mismatching table fails even when the prose parrots the
   gold answer verbatim. (ADR 0002)
3. **It forces a guess on unscorable items.** Verdicts are three-valued:
   `1` (pass), `0` (fail), `-1` (cannot be scored automatically — manual
   review). The `-1` queue is its own report section, never silently folded
   into pass or fail. (ADR 0001)

## Architecture

```
                 data/chinook_bank.jsonl
                 (24 questions: gold SQL + gold answer + tier)
                          |
                          v
   +-----------+     +---------+     +----------------------+
   | AgentClient| --> | runner  | --> | Judge                |
   |  protocol  |     |         |     |  protocol            |
   +-----------+     +---------+     +----------------------+
    |                                  |
    |- StaticAgent (JSONL replay,      |- DeterministicJudge (default:
    |   evaluate ANY agent offline)    |    executes agent SQL + gold SQL,
    |- ClaudeCLIAgent (optional,       |    compares result tables;
    |   live, explicitly gated)        |    table authoritative over prose)
    |                                  |- LLMJudge (optional, gated:
    v                                  |    claude-cli | anthropic-api)
   +------------------------------+    v
   | Database protocol            |   verdicts 1 / 0 / -1 + rationale
   |  SQLiteDatabase (stdlib,     |        |
   |  read-only; production used  |        v
   |  a multi-warehouse adapter   |   report.py: tier-stratified markdown
   |  layer — see ADR 0003)       |   (overall, per-tier table, failures
   +------------------------------+    with rationales, manual-review queue)
```

Zero runtime dependencies — stdlib only. Dev deps: `pytest`, `mypy`, `ruff`.

## Quickstart

```bash
pip install -e '.[dev]'

# 1. Download Chinook (1 MB, SHA-256 verified)
python -m gavel fetch

# 2. Prove the bank is sound: every gold SQL executes, every gold answer matches
python -m gavel validate-bank

# 3. Evaluate the bundled (deliberately imperfect) baseline agent — fully offline
python -m gavel run --agent static --predictions examples/baseline_predictions.jsonl
```

The third command prints a tier-stratified markdown report; the committed
copy is at [`examples/report.md`](examples/report.md). The baseline agent is
intentionally flawed — cosmetic SQL differences that should pass (aliasing,
column order, `COUNT(1)`, implicit joins), subtle bugs that should fail
(missing `DISTINCT`, `>=` vs `>`, wrong sort direction, case-sensitive
filter), one syntax error, and one missing answer that lands in the
manual-review queue.

```bash
# run the test suite (offline, no API calls, no network)
pytest
```

## Evaluating your own agent

Dump your agent's outputs to JSONL — one object per bank question:

```jsonl
{"id": "m2", "sql": "SELECT g.Name, COUNT(*) ...", "answer_text": "Rock has the most tracks."}
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | bank item id this prediction answers |
| `sql` | no | the SQL your agent produced (empty/missing ⇒ verdict `-1`) |
| `answer_text` | no | your agent's prose answer (advisory only — tables decide) |

Then:

```bash
python -m gavel run --agent static --predictions your_predictions.jsonl \
    --out results.json --report report.md
```

Items absent from your file are judged `-1` (manual review), not `0` — a
missing answer is not the same as a wrong one.

## Optional live LLM judging (off by default, costs money)

The deterministic judge is the default and the only thing CI runs. If you
want semantic judging (e.g. to catch coincidental table equality), opt in
explicitly:

```bash
# via a local claude CLI session
python -m gavel run --agent static --predictions ... --judge llm --judge-backend claude-cli

# via the Anthropic API (stdlib urllib, no SDK; needs ANTHROPIC_API_KEY)
python -m gavel run --agent static --predictions ... --judge llm --judge-backend anthropic-api
```

The judge prompt enforces a semantic-equivalence rubric (formatting /
aliasing / `CURRENT_DATE`-vs-hardcoded-date differences pass; wrong tables,
filters, aggregations or joins fail) and demands one-line JSON. Unparseable
judge output becomes `-1`, never a guessed verdict. The test suite touches
none of this live — LLM parsing is covered by a recorded real response
fixture (`tests/fixtures/llm_judge_response.txt`).

There is also an optional live agent (`--agent claude-cli`) that generates
SQL from the schema, gated the same way.

## The question bank

`data/chinook_bank.jsonl` — 24 curated questions, 6 per tier:

- **basic** — single-table lookups and counts
- **easy** — aggregates and simple filters/joins
- **medium** — GROUP BY, multi-joins, ordered top-N
- **hard** — multi-join revenue rollups, HAVING with subqueries, window
  functions, nested aggregates

Gold answers are not hand-typed: they are derived by executing the gold SQL
(`python -m gavel validate-bank --update-answers`) and CI re-verifies the
derivation on every push. Top-N questions are tie-checked against the data
so the cut line is never ambiguous.

## Limitations

- **Result-table equality is necessary, not sufficient.** Two different
  queries can coincidentally agree on one data snapshot. The deterministic
  judge cannot see that; the optional LLM judge is the escape hatch.
- **One dialect per bank.** The bank is written in SQLite SQL; the adapter
  seam (ADR 0003) abstracts execution, not dialect.
- **Ordered comparison is all-or-nothing.** If the gold SQL has a top-level
  `ORDER BY`, full row order is enforced — including any tie-break the gold
  query had to impose. The committed bank avoids ties at LIMIT boundaries.
- **Float tolerance after canonical sorting** has a theoretical edge where
  near-equal values sort differently; curated gold data avoids it.
- **Prose similarity is a heuristic** (sequence ratio + containment). It is
  deliberately advisory-only, so its weakness cannot affect verdicts.

## Development

```bash
ruff check .   # lint
mypy           # strict type-check (gavel, scripts, tests)
pytest         # 88 offline tests; chinook-marked tests skip if not fetched
```

## License

MIT — see [LICENSE](LICENSE). Author: Zac Plischka <zacplischka@gmail.com>.
Chinook database © Luis Rocha, MIT licensed, fetched from the
[official releases](https://github.com/lerocha/chinook-database/releases).
