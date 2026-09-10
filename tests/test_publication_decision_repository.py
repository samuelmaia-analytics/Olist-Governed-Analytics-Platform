from __future__ import annotations

from pathlib import Path
from typing import TypedDict, cast

import pytest

import src.infrastructure.postgres.publication_decision_repository as repository
from src.publication_gate import OperationalPublicationDecision

MIGRATION_DIRECTORY = Path("sql/postgres")
CORE_MIGRATION_PATH = MIGRATION_DIRECTORY / "001_governance_core.sql"
DECISION_MIGRATION_PATH = (
    MIGRATION_DIRECTORY / "002_publication_decisions.sql"
)


class DecisionValues(TypedDict):
    postgres_run_id: int
    governance_run_id: str
    decision: OperationalPublicationDecision
    quality_score: int
    pass_checks: int
    warn_checks: int
    fail_checks: int
    critical_failures: int
    privacy_failed_checks: int


class FakeCursor:
    def __init__(
        self,
        seen_keys: set[tuple[int, str]],
        *,
        fail: bool = False,
    ) -> None:
        self.seen_keys = seen_keys
        self.fail = fail
        self.rowcount = 0
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        if self.fail:
            raise RuntimeError("insert failed")
        self.executions.append((query, parameters))
        key = (
            cast(int, parameters[0]),
            cast(str, parameters[1]),
        )
        if key in self.seen_keys:
            self.rowcount = 0
            return
        self.seen_keys.add(key)
        self.rowcount = 1


class FakeConnection:
    def __init__(
        self,
        seen_keys: set[tuple[int, str]],
        *,
        fail: bool = False,
    ) -> None:
        self.cursor_instance = FakeCursor(seen_keys, fail=fail)
        self.commit_calls = 0
        self.rollback_calls = 0
        self.close_calls = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1


def _decision_values() -> DecisionValues:
    return {
        "postgres_run_id": 123,
        "governance_run_id": "run-current",
        "decision": "APPROVED_WITH_WARNINGS",
        "quality_score": 96,
        "pass_checks": 24,
        "warn_checks": 1,
        "fail_checks": 0,
        "critical_failures": 0,
        "privacy_failed_checks": 0,
    }


def test_repository_inserts_complete_decision_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(set())
    monkeypatch.setattr(
        repository,
        "get_postgres_connection",
        lambda: connection,
    )

    inserted = repository.save_publication_decision(
        **_decision_values(),
    )

    query, parameters = connection.cursor_instance.executions[0]
    assert inserted is True
    assert "INSERT INTO governance.publication_decisions" in query
    assert "ON CONFLICT (postgres_run_id, governance_run_id)" in query
    assert parameters == (
        123,
        "run-current",
        "APPROVED_WITH_WARNINGS",
        96,
        24,
        1,
        0,
        0,
        0,
    )
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0
    assert connection.close_calls == 1


def test_repository_is_idempotent_for_same_run_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_keys: set[tuple[int, str]] = set()
    connections: list[FakeConnection] = []

    def connect() -> FakeConnection:
        connection = FakeConnection(seen_keys)
        connections.append(connection)
        return connection

    monkeypatch.setattr(repository, "get_postgres_connection", connect)

    first = repository.save_publication_decision(
        **_decision_values(),
    )
    second = repository.save_publication_decision(
        **_decision_values(),
    )

    assert first is True
    assert second is False
    assert seen_keys == {(123, "run-current")}
    assert all(connection.commit_calls == 1 for connection in connections)
    assert all(connection.close_calls == 1 for connection in connections)


def test_repository_rolls_back_and_closes_on_insert_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(set(), fail=True)
    monkeypatch.setattr(
        repository,
        "get_postgres_connection",
        lambda: connection,
    )

    with pytest.raises(RuntimeError, match="insert failed"):
        repository.save_publication_decision(
            **_decision_values(),
        )

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    assert connection.close_calls == 1


def test_migrations_bootstrap_dependencies_before_publication_decisions() -> None:
    migration_names = [
        path.name for path in sorted(MIGRATION_DIRECTORY.glob("*.sql"))
    ]
    core_sql = CORE_MIGRATION_PATH.read_text(encoding="utf-8")
    decision_sql = DECISION_MIGRATION_PATH.read_text(encoding="utf-8")

    assert migration_names.index(CORE_MIGRATION_PATH.name) < migration_names.index(
        DECISION_MIGRATION_PATH.name
    )
    assert "CREATE SCHEMA IF NOT EXISTS governance" in core_sql
    assert "CREATE TABLE IF NOT EXISTS governance.pipeline_runs" in core_sql
    assert "CREATE TABLE IF NOT EXISTS governance.data_quality_results" in core_sql
    assert core_sql.index("governance.pipeline_runs") < core_sql.index(
        "governance.data_quality_results"
    )
    assert "REFERENCES governance.pipeline_runs (run_id)" in core_sql
    assert (
        "CREATE TABLE IF NOT EXISTS governance.publication_decisions"
        in decision_sql
    )
    assert "PRIMARY KEY" in decision_sql
    assert "REFERENCES governance.pipeline_runs (run_id)" in decision_sql
    assert "UNIQUE (postgres_run_id, governance_run_id)" in decision_sql
    assert "TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP" in decision_sql
    assert "'APPROVED'" in decision_sql
    assert "'APPROVED_WITH_WARNINGS'" in decision_sql
    assert "'BLOCKED'" in decision_sql
    combined_sql = core_sql.upper() + decision_sql.upper()
    assert "DROP " not in combined_sql
    assert "TRUNCATE " not in combined_sql
