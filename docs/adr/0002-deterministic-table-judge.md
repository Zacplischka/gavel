# ADR 0002 — Deterministic table-comparison judge as the offline default

## Status

Accepted

## Context

Text-to-SQL agents produce two artifacts per question: SQL (which yields a
result table) and prose. Prose is cheap to make convincing and expensive to
verify; result tables are the opposite. An LLM judge reading prose can be
talked into a pass by a confident sentence, and it costs money and
non-determinism on every item.

## Decision

The default judge (`DeterministicJudge`) executes BOTH the agent's SQL and
the gold SQL against the live local database and compares the **result
tables** under normalization:

- column order and column *names* never matter — columns are matched by
  content, not header (aliases are presentation, not semantics)
- row order matters only when the gold SQL has a top-level `ORDER BY`
  (then presentation order is part of the question's contract)
- floats compare with relative tolerance (`1e-6`)
- datetime strings at midnight collapse to their date; numeric strings
  compare as numbers; integral floats equal their ints

**Returned table data is authoritative over prose.** Prose similarity is
computed and recorded, but it can only ever annotate the rationale:
a matching table passes even if the prose is nonsense, and a mismatching
table fails even if the prose parrots the gold answer verbatim. This rule is
enforced by tests in both directions.

Execution failures split by ADR 0001: agent SQL failing is a clear `0`;
gold SQL failing, or missing agent SQL, is a `-1`.

## Consequences

- The default evaluation path is free, offline, and bit-for-bit
  reproducible — CI can run the full bank on every push.
- Semantic equivalence beyond result equality (e.g. two queries that
  coincidentally return the same table on this snapshot) is out of scope;
  the optional LLM judge (ADR 0004) exists for that.
- Tolerance-based float comparison after canonical sorting has a known
  edge: values inside tolerance of each other can sort differently. With
  curated gold data this does not occur; it is documented as a limitation.
