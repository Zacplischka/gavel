"""CLI smoke tests (in-process, plus one true `python -m gavel` subprocess)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gavel.bank import BankItem, save_bank
from gavel.cli import main


@pytest.fixture
def mini_bank_file(mini_bank: list[BankItem], tmp_path: Path) -> Path:
    path = tmp_path / "bank.jsonl"
    save_bank(mini_bank, path)
    return path


@pytest.fixture
def predictions_file(tmp_path: Path) -> Path:
    path = tmp_path / "preds.jsonl"
    records = [
        {"id": "q1", "sql": "SELECT COUNT(*) FROM band", "answer_text": "3"},
        {"id": "q2", "sql": "SELECT COUNT(*) FROM song WHERE price = 1.29", "answer_text": ""},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def test_module_help_via_subprocess() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "gavel", "--help"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0
    assert "validate-bank" in proc.stdout


def test_validate_bank_ok(mini_bank_file: Path, mini_db_path: Path) -> None:
    rc = main(["validate-bank", "--bank", str(mini_bank_file), "--db", str(mini_db_path)])
    assert rc == 0


def test_validate_bank_catches_drift(
    mini_bank: list[BankItem],
    mini_db_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    drifted = [
        BankItem(
            id=i.id, tier=i.tier, question=i.question, gold_sql=i.gold_sql, gold_answer="wrong"
        )
        for i in mini_bank
    ]
    bank_path = tmp_path / "drifted.jsonl"
    save_bank(drifted, bank_path)
    rc = main(["validate-bank", "--bank", str(bank_path), "--db", str(mini_db_path)])
    assert rc == 1
    assert "does not match" in capsys.readouterr().err


def test_run_writes_results_and_report(
    mini_bank_file: Path, mini_db_path: Path, predictions_file: Path, tmp_path: Path
) -> None:
    results = tmp_path / "results.json"
    report = tmp_path / "report.md"
    rc = main(
        [
            "run",
            "--bank", str(mini_bank_file),
            "--db", str(mini_db_path),
            "--agent", "static",
            "--predictions", str(predictions_file),
            "--out", str(results),
            "--report", str(report),
        ]
    )
    assert rc == 0
    text = report.read_text(encoding="utf-8")
    assert "## By tier" in text
    assert "Manual-review queue" in text  # q3/q4 missing from predictions -> -1
    data = json.loads(results.read_text(encoding="utf-8"))
    assert len(data["results"]) == 4


def test_run_requires_predictions_for_static_agent(
    mini_bank_file: Path, mini_db_path: Path
) -> None:
    rc = main(
        ["run", "--bank", str(mini_bank_file), "--db", str(mini_db_path), "--agent", "static"]
    )
    assert rc == 2


def test_report_rerenders_saved_results(
    mini_bank_file: Path,
    mini_db_path: Path,
    predictions_file: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = tmp_path / "results.json"
    rc = main(
        [
            "run",
            "--bank", str(mini_bank_file),
            "--db", str(mini_db_path),
            "--agent", "static",
            "--predictions", str(predictions_file),
            "--out", str(results),
            "--report", str(tmp_path / "ignored.md"),
        ]
    )
    assert rc == 0
    capsys.readouterr()
    rc = main(["report", "--results", str(results), "--title", "re-rendered"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("# re-rendered")


def test_report_missing_file_errors(tmp_path: Path) -> None:
    rc = main(["report", "--results", str(tmp_path / "nope.json")])
    assert rc == 1
