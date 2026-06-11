# ADR 0001 — Three-valued verdicts with a manual-review escape hatch

## Status

Accepted

## Context

Binary pass/fail judges are forced to guess on items they cannot actually
score: the agent returned no SQL, the gold query itself failed, the judge's
own output was unparseable. Whichever way the guess goes, it silently
corrupts the headline metric — either inflating accuracy (unscorable
items dropped) or deflating it (unscorable items counted as failures), and
in both cases hiding the items most worth a human's attention.

## Decision

Every judge in gavel returns one of three scores:

| Score | Meaning |
|------:|---------|
| `1`   | correct |
| `0`   | incorrect |
| `-1`  | cannot be scored automatically — goes to the manual-review queue |

`-1` is reserved for *ambiguity about the scoring itself*, not for agent
mistakes. An agent whose SQL throws a syntax error is wrong (`0`); a bank
item whose gold SQL throws is unscorable (`-1`); an agent that produced no
SQL at all is unscorable (`-1`) because absence of evidence is not evidence
of a wrong answer.

Reports surface two numbers: accuracy over judged items (`1` vs `0`) and
strict accuracy over all items (where `-1` counts against). The
manual-review queue is its own report section and is never folded into
either bucket.

## Consequences

- The headline number is honest: nothing unscorable is hidden inside it.
- Humans review a short queue instead of auditing the whole run.
- Downstream tooling must handle three states, not two — a deliberate cost.
