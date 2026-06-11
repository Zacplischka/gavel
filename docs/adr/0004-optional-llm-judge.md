# ADR 0004 — Optional LLM judge gated behind explicit flags

## Status

Accepted

## Context

A semantic LLM judge is genuinely useful for the cases result-table
comparison cannot decide — e.g. two queries that are *coincidentally*
equal on the current data snapshot, or rubric questions like "is
`CURRENT_DATE` acceptable where the gold hardcodes today's date". But every
LLM call costs money, adds latency, and injects non-determinism. A harness
that silently spends its user's API budget — or whose test suite needs a
paid key to go green — is broken by design.

## Decision

`LLMJudge` exists but is never on a default path:

- The CLI default is `--judge deterministic`. Choosing the LLM judge
  requires typing `--judge llm`, and the `--help` text says it costs money.
- The same applies to the live agent (`--agent claude-cli`).
- Two backends, both explicit: `claude-cli` (subprocess `claude -p`,
  rides an existing local CLI session) and `anthropic-api` (raw stdlib
  `urllib` against the Messages API; requires `ANTHROPIC_API_KEY`; no SDK
  dependency, keeping the package at zero runtime deps).
- The judge prompt demands a strict one-line JSON verdict and encodes the
  semantic-equivalence rubric (formatting/aliasing/date-function
  differences pass; wrong tables/filters/aggregations/joins fail).
- Robust parsing: JSON is extracted from messy output (code fences,
  surrounding prose); anything unparseable becomes verdict `-1`, never a
  guessed pass or fail (ADR 0001).
- The test suite makes **zero** live calls. LLM-judge behaviour is tested
  through injected transports and one recorded real response fixture
  (`tests/fixtures/llm_judge_response.txt`) with a parser regression test.

## Consequences

- `pytest`, CI, and the example run are fully offline and free.
- Users who want semantic judging opt in per-run, eyes open about cost.
- The recorded fixture pins the parser against real-world output shape,
  not an idealised mock.
