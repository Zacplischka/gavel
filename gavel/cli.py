"""The ``gavel`` command line interface (also ``python -m gavel``).

Subcommands:

* ``fetch``         — download the Chinook database (SHA-256 verified)
* ``validate-bank`` — check the question bank against the database
* ``run``           — evaluate an agent over the bank and emit a report
* ``report``        — re-render a saved results JSON as markdown
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gavel import __version__
from gavel.agents import AgentClient, ClaudeCLIAgent, StaticAgent
from gavel.bank import BankError, load_bank, rederive_answers, save_bank, validate_bank
from gavel.db import SQLiteDatabase, schema_dump
from gavel.fetch import DEFAULT_DEST, FetchError, fetch_chinook
from gavel.judge import DeterministicJudge, Judge, LLMJudge
from gavel.report import render_report
from gavel.runner import load_run, run_bank, save_run

DEFAULT_BANK = Path("data") / "chinook_bank.jsonl"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gavel",
        description="LLM-as-a-judge evaluation harness for text-to-SQL agents.",
    )
    parser.add_argument("--version", action="version", version=f"gavel {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="download the Chinook SQLite database")
    p_fetch.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    p_fetch.add_argument("--force", action="store_true", help="re-download even if present")

    p_validate = sub.add_parser(
        "validate-bank", help="verify every gold SQL executes and gold answers match"
    )
    p_validate.add_argument("--bank", type=Path, default=DEFAULT_BANK)
    p_validate.add_argument("--db", type=Path, default=DEFAULT_DEST)
    p_validate.add_argument(
        "--update-answers",
        action="store_true",
        help="re-derive gold answers from gold SQL and rewrite the bank file",
    )

    p_run = sub.add_parser("run", help="evaluate an agent over the bank")
    p_run.add_argument("--bank", type=Path, default=DEFAULT_BANK)
    p_run.add_argument("--db", type=Path, default=DEFAULT_DEST)
    p_run.add_argument(
        "--agent",
        choices=["static", "claude-cli"],
        default="static",
        help="'static' replays a predictions JSONL; 'claude-cli' calls a live model (costs!)",
    )
    p_run.add_argument(
        "--predictions", type=Path, help="predictions JSONL (required for --agent static)"
    )
    p_run.add_argument(
        "--judge",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="'deterministic' is the offline default; 'llm' calls a live model (costs!)",
    )
    p_run.add_argument(
        "--judge-backend",
        choices=["claude-cli", "anthropic-api"],
        default="claude-cli",
        help="transport for --judge llm",
    )
    p_run.add_argument("--model", help="model override for live agent/judge backends")
    p_run.add_argument("--out", type=Path, help="write results JSON here")
    p_run.add_argument("--report", type=Path, help="write the markdown report here")
    p_run.add_argument("--title", default="gavel evaluation report")

    p_report = sub.add_parser("report", help="re-render a saved results JSON")
    p_report.add_argument("--results", type=Path, required=True)
    p_report.add_argument("--out", type=Path, help="write markdown here (default: stdout)")
    p_report.add_argument("--title", default="gavel evaluation report")

    return parser


def _cmd_fetch(args: argparse.Namespace) -> int:
    try:
        path = fetch_chinook(args.dest, force=args.force)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {path}")
    return 0


def _cmd_validate_bank(args: argparse.Namespace) -> int:
    try:
        items = load_bank(args.bank)
    except (BankError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    with SQLiteDatabase(args.db) as db:
        if args.update_answers:
            updated = rederive_answers(items, db)
            save_bank(updated, args.bank)
            print(f"ok: re-derived {len(updated)} gold answers -> {args.bank}")
            return 0
        problems = validate_bank(items, db)
    if problems:
        for problem in problems:
            print(f"problem: {problem}", file=sys.stderr)
        return 1
    print(f"ok: {len(items)} items, every gold SQL executes and every gold answer matches")
    return 0


def _make_agent(args: argparse.Namespace, db: SQLiteDatabase) -> AgentClient | None:
    if args.agent == "static":
        if args.predictions is None:
            print("error: --agent static requires --predictions", file=sys.stderr)
            return None
        return StaticAgent.from_jsonl(args.predictions)
    return ClaudeCLIAgent(schema_dump(db), model=args.model)


def _make_judge(args: argparse.Namespace, db: SQLiteDatabase) -> Judge:
    if args.judge == "llm":
        return LLMJudge(backend=args.judge_backend, model=args.model)
    return DeterministicJudge(db)


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        items = load_bank(args.bank)
    except (BankError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    with SQLiteDatabase(args.db) as db:
        agent = _make_agent(args, db)
        if agent is None:
            return 2
        judge = _make_judge(args, db)
        run = run_bank(items, agent, judge)
    report = render_report(run, title=args.title)
    if args.out is not None:
        save_run(run, args.out)
        print(f"results -> {args.out}", file=sys.stderr)
    if args.report is not None:
        args.report.write_text(report + "\n", encoding="utf-8")
        print(f"report  -> {args.report}", file=sys.stderr)
    else:
        print(report)
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    try:
        run = load_run(args.results)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: cannot load {args.results}: {exc}", file=sys.stderr)
        return 1
    report = render_report(run, title=args.title)
    if args.out is not None:
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"report -> {args.out}", file=sys.stderr)
    else:
        print(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {
        "fetch": _cmd_fetch,
        "validate-bank": _cmd_validate_bank,
        "run": _cmd_run,
        "report": _cmd_report,
    }
    return handlers[str(args.command)](args)


if __name__ == "__main__":
    sys.exit(main())
