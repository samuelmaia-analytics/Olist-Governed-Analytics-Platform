"""Offline SQL contract tests; these do not execute or emulate PL/pgSQL."""

import re
from pathlib import Path
from typing import Any

import pytest

from src.infrastructure.postgres import pipeline_repository, quality_repository
from src.quality_components.models import QualityCheckResult

MIGRATIONS = Path(__file__).resolve().parents[1] / "sql" / "postgres"
SQL = (MIGRATIONS / "003_reconcile_governance_core.sql").read_text(encoding="utf-8")
CODE = re.sub(r"--[^\n]*", "", SQL)


def test_reconciliation_follows_existing_migrations() -> None:
    names = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
    assert names[:3] == [
        "001_governance_core.sql",
        "002_publication_decisions.sql",
        "003_reconcile_governance_core.sql",
    ]


def test_missing_tables_fail_before_locks_or_changes() -> None:
    assert "pipeline_table IS NULL OR quality_table IS NULL" in CODE
    assert "apply 001 first" in CODE
    assert CODE.index("apply 001 first") < CODE.index("LOCK TABLE")
    assert "CREATE TABLE" not in CODE.upper()


def test_status_check_uses_catalog_and_expression_not_only_name() -> None:
    for fragment in (
        "pg_get_expr(conbin, conrelid)",
        "status_attribute = ANY (conkey)",
        "conkey IS DISTINCT FROM ARRAY[status_attribute]",
        "count(DISTINCT token[1])",
        "state_count <> 3",
        "IF NOT equivalent_found THEN",
        "CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED'))",
        "conflicting or unsupported status CHECK",
        "AND NOT convalidated",
        "VALIDATE CONSTRAINT %I",
    ):
        assert fragment in CODE
    assert CODE.index("conflicting or unsupported") < CODE.index("ADD CONSTRAINT")


@pytest.mark.parametrize("column,flag", [("run_id", "run_required"), ("check_type", "type_required")])
def test_null_preflight_and_idempotent_guard(column: str, flag: str) -> None:
    assert f"SELECT attnotnull INTO {flag}" in CODE
    assert CODE.count(f"IF NOT {flag} THEN") == 2
    preflight = f"FROM governance.data_quality_results WHERE {column} IS NULL;"
    mutation = f"ALTER COLUMN {column} SET NOT NULL;"
    assert preflight in CODE
    assert f"cannot require data_quality_results.{column}" in CODE
    assert CODE.index(preflight) < CODE.index("ADD CONSTRAINT") < CODE.index(mutation)
    assert "IF null_count <> 0 THEN" in CODE


def test_only_authorized_alterations_and_no_transaction_control() -> None:
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE|INSERT|CREATE|COMMIT|ROLLBACK)\b", CODE, re.I)
    assert not re.search(r"\bBEGIN\s*;", CODE, re.I)
    assert CODE.count("ALTER TABLE") == 4  # CHECK, validation, two NOT NULLs.
    assert CODE.count("ALTER COLUMN") == 2
    assert CODE.count("ADD CONSTRAINT") == 1
    for forbidden in (
        "duration_seconds", "created_at", "executed_at", "sequence", "identity",
        "result_id", "pipeline_name", "git_commit", "TYPE text", "TYPE varchar",
        "RENAME", "SET DEFAULT", "PRIMARY KEY", "FOREIGN KEY", "CREATE INDEX",
    ):
        assert forbidden.lower() not in CODE.lower()


# Test the exact anchored grammar embedded in the SQL, not a second catalog engine.
PATTERNS = re.findall(r"normalized ~ '([^']+)'", SQL)


@pytest.mark.parametrize("expression", [
    "status=ANYARRAY[RUNNING,SUCCESS,FAILED]",
    "status=ANYARRAY[FAILED,RUNNING,SUCCESS]",
    "status=SUCCESSORstatus=FAILEDORstatus=RUNNING",
])
def test_equivalence_grammar_accepts_supported_forms(expression: str) -> None:
    assert len(PATTERNS) == 2
    assert any(re.fullmatch(pattern, expression) for pattern in PATTERNS)


@pytest.mark.parametrize("expression", [
    "status=ANYARRAY[RUNNING,SUCCESS]",
    "status=ANYARRAY[RUNNING,SUCCESS,FAILED,INVALID]",
    "NOTstatus=ANYARRAY[RUNNING,SUCCESS,FAILED]",
    "status=ANYARRAY[RUNNING,SUCCESS,FAILED]ORtrue",
    "status<>RUNNINGORstatus<>SUCCESSORstatus<>FAILED",
    "lowerstatus=ANYARRAY[RUNNING,SUCCESS,FAILED]",
    "status=ANYARRAY['RUN NING',SUCCESS,FAILED]",
])
def test_equivalence_grammar_rejects_unsafe_forms(expression: str) -> None:
    assert not any(re.fullmatch(pattern, expression) for pattern in PATTERNS)


class FakeConnection:
    """Capture repository SQL without a database or a SQL interpreter."""

    def __init__(self, row: tuple[int, ...]) -> None:
        self.row = row
        self.calls: list[tuple[str, Any]] = []
        self.commits = 0

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def cursor(self) -> "FakeConnection":
        return self

    def execute(self, query: str, parameters: Any) -> None:
        self.calls.append((query, parameters))

    def executemany(self, query: str, parameters: Any) -> None:
        self.calls.append((query, parameters))

    def fetchone(self) -> tuple[int, ...]:
        return self.row

    def commit(self) -> None:
        self.commits += 1


def test_pipeline_repository_uses_generated_id_and_explicit_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection((7,))
    monkeypatch.setattr(pipeline_repository, "get_postgres_connection", lambda: connection)
    assert pipeline_repository.start_pipeline_run("synthetic") == 7
    assert "RETURNING run_id" in connection.calls[0][0]
    assert connection.calls[0][1] == ("synthetic", "RUNNING", None)
    pipeline_repository.finish_pipeline_run(7, "SUCCESS", duration_seconds=3.217)
    query, parameters = connection.calls[1]
    assert "WHERE run_id = %s" in query
    assert parameters[1:] == ("SUCCESS", None, 3.217, None, 7)
    assert connection.commits == 2


def test_quality_repository_returns_id_and_supplies_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection((80,))
    monkeypatch.setattr(quality_repository, "get_postgres_connection", lambda: connection)
    assert quality_repository.save_quality_result(7, "synthetic", "synthetic", "DATA_QUALITY", "PASS") == 80
    query, parameters = connection.calls[0]
    assert "RETURNING result_id" in query
    assert parameters[:5] == (7, "synthetic", "synthetic", "DATA_QUALITY", "PASS")
    assert connection.commits == 1


def test_quality_batch_and_summary_use_run_id_without_identity_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection((0,))
    monkeypatch.setattr(quality_repository, "get_postgres_connection", lambda: connection)
    result = QualityCheckResult("synthetic", "PASS", 1, 1, "high", "synthetic")
    assert quality_repository.save_quality_results(run_id=7, dataset_name="synthetic", results=[result]) == 1
    assert connection.calls[0][1] == (7,)
    assert connection.calls[1][1][0][:5] == (7, "synthetic", "synthetic", "DATA_QUALITY", "PASS")
    connection.row = (1, 1, 0, 0, 0)
    assert quality_repository.get_quality_summary(7) == {
        "total_checks": 1, "pass_checks": 1, "warn_checks": 0,
        "fail_checks": 0, "critical_failures": 0,
    }
