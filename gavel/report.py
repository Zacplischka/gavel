"""Tier-stratified markdown report rendering.

A single aggregate number hides where an agent actually breaks. The report
therefore leads with the per-tier table, lists every failure with the judge's
rationale, and keeps the manual-review queue visible instead of folding it
into either bucket.
"""

from __future__ import annotations

from gavel.runner import ItemResult, RunResult


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _failure_block(result: ItemResult) -> list[str]:
    lines = [
        f"### `{result.item.id}` ({result.item.tier})",
        "",
        f"**Question:** {result.item.question}",
        "",
        f"**Agent SQL:** `{result.prediction.sql.strip() or '(none)'}`",
        "",
        f"**Rationale:** {result.verdict.rationale}",
        "",
    ]
    return lines


def render_report(run: RunResult, *, title: str = "gavel evaluation report") -> str:
    """Render a run as markdown."""
    total = len(run.results)
    passed, failed, review = run.count(1), run.count(0), run.count(-1)

    lines: list[str] = [
        f"# {title}",
        "",
        "## Overall",
        "",
        f"- **Items:** {total}",
        f"- **Pass:** {passed}",
        f"- **Fail:** {failed}",
        f"- **Manual review (verdict -1):** {review}",
        f"- **Accuracy (judged items only):** {_pct(run.accuracy)}",
        f"- **Strict accuracy (review counts against):** {_pct(run.strict_accuracy)}",
        "",
        "## By tier",
        "",
        "| Tier | Items | Pass | Fail | Review | Accuracy |",
        "|------|------:|-----:|-----:|-------:|---------:|",
    ]
    for stats in run.tier_stats():
        lines.append(
            f"| {stats.tier} | {stats.total} | {stats.passed} | {stats.failed} "
            f"| {stats.review} | {_pct(stats.accuracy)} |"
        )

    failures = run.failures()
    lines += ["", "## Failures", ""]
    if failures:
        for result in failures:
            lines.extend(_failure_block(result))
    else:
        lines += ["No failures.", ""]

    queue = run.review_queue()
    lines += ["## Manual-review queue", ""]
    if queue:
        lines += [
            "These items could not be scored automatically (verdict -1). A human",
            "should look at each one — do not fold them into pass or fail.",
            "",
        ]
        for result in queue:
            lines += [
                f"- `{result.item.id}` ({result.item.tier}): {result.item.question}",
                f"  - {result.verdict.rationale}",
            ]
        lines.append("")
    else:
        lines += ["Empty — every item was scored automatically.", ""]

    return "\n".join(lines)
