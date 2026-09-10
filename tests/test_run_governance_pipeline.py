from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pandas as pd
import pytest

import scripts.run_governance_pipeline as runner
import scripts.run_publication_gate as publication_gate_cli
import src.run_platform_pipeline as platform_pipeline
from src.publication_gate import evaluate_operational_publication_gate
from src.publication_provenance import EvidenceSource, PipelineGovernanceContext
from src.publish_components.models import PrivacyCheck, PrivacyPreflightResult
from src.quality_components.models import QualityCheckResult
from src.run_platform_pipeline import PipelineRunMetadata


def _quality_results(
    *,
    pass_checks: int,
    warn_checks: int = 0,
    fail_checks: int = 0,
) -> list[QualityCheckResult]:
    results = [
        QualityCheckResult(
            check_name=(
                "record_volume_above_100k"
                if index == 0
                else f"pass_{index}"
            ),
            status="PASS",
            metric_value=112_650 if index == 0 else 0,
            threshold=100_000 if index == 0 else 0,
            severity="high",
            details="ok",
        )
        for index in range(pass_checks)
    ]
    results.extend(
        QualityCheckResult(
            f"warn_{index}", "WARN", 1, 0, "medium", "warning"
        )
        for index in range(warn_checks)
    )
    results.extend(
        QualityCheckResult(
            f"fail_{index}", "FAIL", 1, 0, "high", "failure"
        )
        for index in range(fail_checks)
    )
    return results


def _execute_isolated(
    monkeypatch: pytest.MonkeyPatch,
    results: list[QualityCheckResult],
    *,
    privacy_checks: list[PrivacyCheck] | None = None,
    postgres_run_id: int = 42,
    persisted_decisions: list[dict[str, object]] | None = None,
    operation_calls: list[str] | None = None,
) -> tuple[
    runner.GovernedPipelineExecution,
    list[str],
    list[object],
    PipelineGovernanceContext,
]:
    publish_calls: list[str] = []
    persisted: list[object] = []

    def publish(**_kwargs: object) -> None:
        publish_calls.append("publish")
        if operation_calls is not None:
            operation_calls.append("publish")

    def persist_decision(**kwargs: object) -> bool:
        if persisted_decisions is not None:
            persisted_decisions.append(dict(kwargs))
        if operation_calls is not None:
            operation_calls.append("decision")
        return True

    monkeypatch.setattr(platform_pipeline, "load_fact_table", lambda: object())
    monkeypatch.setattr(platform_pipeline, "run_quality_checks", lambda _df: results)
    monkeypatch.setattr(platform_pipeline, "save_quality_results", lambda _x: None)
    monkeypatch.setattr(
        platform_pipeline, "save_quality_report", lambda _df, _results: None
    )
    monkeypatch.setattr(
        platform_pipeline,
        "run_publish_dashboard",
        publish,
    )
    source = pd.DataFrame({"order_id": ["raw-order"]})
    candidate = pd.DataFrame({"order_id": ["order_id_token"]})
    current_privacy_checks = privacy_checks or [
        PrivacyCheck("forbidden_columns_absent", "PASS", "current"),
        PrivacyCheck("classification_leakage", "PASS", "current"),
        PrivacyCheck("pseudonymized__order_id", "PASS", "current"),
    ]
    monkeypatch.setattr(
        runner,
        "run_privacy_preflight",
        lambda: PrivacyPreflightResult(
            source_df=source,
            published_candidate=candidate,
            contract={},
            policy={},
            checks=current_privacy_checks,
        ),
    )

    def persist(
        postgres_run_id: int,
        quality_results: object,
    ) -> int:
        persisted.extend([postgres_run_id, quality_results])
        return len(quality_results)  # type: ignore[arg-type]

    monkeypatch.setattr(runner, "persist_quality_results_to_postgres", persist)
    monkeypatch.setattr(
        runner,
        "save_publication_decision",
        persist_decision,
    )
    context = PipelineGovernanceContext("run-current")
    outcome = runner.execute_governed_steps(
        selected_steps=["quality", "publish"],
        continue_on_error=False,
        postgres_run_id=postgres_run_id,
        governance_context=context,
    )
    assert context.quality_results == tuple(results)
    return outcome, publish_calls, persisted, context


def test_operational_gate_uses_the_documented_quality_policy() -> None:
    warning = evaluate_operational_publication_gate(
        total_checks=25,
        pass_checks=24,
        warn_checks=1,
        fail_checks=0,
        critical_failures=0,
    )
    approved = evaluate_operational_publication_gate(
        total_checks=25,
        pass_checks=25,
        warn_checks=0,
        fail_checks=0,
        critical_failures=0,
    )
    blocked = evaluate_operational_publication_gate(
        total_checks=1,
        pass_checks=0,
        warn_checks=0,
        fail_checks=1,
        critical_failures=1,
    )
    privacy_blocked = evaluate_operational_publication_gate(
        total_checks=25,
        pass_checks=25,
        warn_checks=0,
        fail_checks=0,
        critical_failures=0,
        privacy_failed_checks=1,
    )

    assert (warning.decision, warning.quality_score) == (
        "APPROVED_WITH_WARNINGS",
        96,
    )
    assert approved.decision == "APPROVED"
    assert blocked.decision == "BLOCKED"
    assert privacy_blocked.decision == "BLOCKED"


def test_quality_without_publish_does_not_produce_publication_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quality_results = _quality_results(pass_checks=25)
    calls: list[str] = []

    def run_steps(
        selected_steps: list[str],
        *,
        continue_on_error: bool,
    ) -> list[platform_pipeline.StepExecution]:
        assert continue_on_error is False
        calls.extend(selected_steps)
        context = platform_pipeline._ACTIVE_GOVERNANCE_CONTEXT.get()
        assert context is not None
        context.record_quality(quality_results)
        return []

    def unexpected_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("publication-only dependency was called")

    def persist_quality(
        run_id: int,
        results: tuple[QualityCheckResult, ...],
    ) -> int:
        calls.append(f"quality:{run_id}")
        return len(results)

    monkeypatch.setattr(runner, "run_selected_steps", run_steps)
    monkeypatch.setattr(
        runner,
        "persist_quality_results_to_postgres",
        persist_quality,
    )
    monkeypatch.setattr(runner, "run_privacy_preflight", unexpected_call)
    monkeypatch.setattr(
        runner,
        "evaluate_operational_publication_gate",
        unexpected_call,
    )
    monkeypatch.setattr(runner, "save_publication_decision", unexpected_call)

    outcome = runner.execute_governed_steps(
        selected_steps=["quality"],
        continue_on_error=False,
        postgres_run_id=123,
        governance_context=PipelineGovernanceContext("run-current"),
    )

    assert calls == ["quality", "quality:123"]
    assert outcome.quality_results_persisted == 25
    assert outcome.publication_gate is None


def test_warning_quality_authorizes_publish_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions: list[dict[str, object]] = []
    operations: list[str] = []
    outcome, publish_calls, persisted, context = _execute_isolated(
        monkeypatch,
        _quality_results(pass_checks=24, warn_checks=1),
        persisted_decisions=decisions,
        operation_calls=operations,
    )

    assert outcome.publication_gate is not None
    assert outcome.publication_gate.decision == "APPROVED_WITH_WARNINGS"
    assert outcome.publication_gate.quality_score == 96
    assert publish_calls == ["publish"]
    assert persisted[0] == 42
    assert len(persisted[1]) == 25  # type: ignore[arg-type]
    assert context.privacy_controls is not None
    assert context.inherent_privacy_risk_score is not None
    assert context.residual_privacy_risk_score is not None
    assert decisions == [
        {
            "postgres_run_id": 42,
            "governance_run_id": "run-current",
            "decision": "APPROVED_WITH_WARNINGS",
            "quality_score": 96,
            "pass_checks": 24,
            "warn_checks": 1,
            "fail_checks": 0,
            "critical_failures": 0,
            "privacy_failed_checks": 0,
        }
    ]
    assert operations == ["decision", "publish"]


def test_failed_quality_blocks_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome, publish_calls, persisted, _context = _execute_isolated(
        monkeypatch,
        _quality_results(pass_checks=24, fail_checks=1),
    )

    assert outcome.publication_gate is not None
    assert outcome.publication_gate.decision == "BLOCKED"
    assert publish_calls == []
    assert len(persisted[1]) == 25  # type: ignore[arg-type]


def test_missing_current_quality_blocks_even_when_stale_csv_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stale_csv = tmp_path / "fact_orders_enriched_quality_checks.csv"
    stale_csv.write_text(
        "check_name,status,metric_value,threshold,severity,details\n"
        "old,PASS,1,1,high,stale\n",
        encoding="utf-8",
    )

    outcome, publish_calls, persisted, _context = _execute_isolated(monkeypatch, [])

    assert stale_csv.exists()
    assert not hasattr(runner, "load_quality_results")
    assert outcome.publication_gate is not None
    assert outcome.publication_gate.decision == "BLOCKED"
    assert outcome.publication_gate.total_checks == 0
    assert publish_calls == []
    assert persisted == []


def test_current_context_has_authority_over_stale_quality_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_results = _quality_results(pass_checks=24, warn_checks=1)
    csv_reads: list[str] = []

    def read_stale_quality() -> list[QualityCheckResult]:
        csv_reads.append("read")
        return _quality_results(pass_checks=24, fail_checks=1)

    monkeypatch.setattr(
        runner,
        "load_quality_results",
        read_stale_quality,
        raising=False,
    )

    outcome, publish_calls, persisted, _context = _execute_isolated(
        monkeypatch,
        current_results,
    )

    assert csv_reads == []
    assert outcome.publication_gate is not None
    assert outcome.publication_gate.decision == "APPROVED_WITH_WARNINGS"
    assert outcome.publication_gate.quality_score == 96
    assert publish_calls == ["publish"]
    persisted_results: tuple[QualityCheckResult, ...] = tuple(
        cast(list[QualityCheckResult], persisted[1])
    )
    assert persisted_results == tuple(current_results)
    assert all(
        actual is expected
        for actual, expected in zip(persisted_results, current_results, strict=True)
    )


def test_privacy_failure_blocks_publish_before_publish_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions: list[dict[str, object]] = []
    operations: list[str] = []
    outcome, publish_calls, _persisted, context = _execute_isolated(
        monkeypatch,
        _quality_results(pass_checks=25),
        privacy_checks=[
            PrivacyCheck("forbidden_columns_absent", "FAIL", "current failure"),
            PrivacyCheck("classification_leakage", "PASS", "current"),
        ],
        persisted_decisions=decisions,
        operation_calls=operations,
    )

    assert outcome.publication_gate is not None
    assert outcome.publication_gate.decision == "BLOCKED"
    assert outcome.publication_gate.privacy_failed_checks == 1
    assert publish_calls == []
    assert context.privacy_controls is not None
    assert context.privacy_controls[0].details == "current failure"
    assert context.provenance[EvidenceSource.PRIVACY].run_id == "run-current"
    assert decisions[0]["decision"] == "BLOCKED"
    assert decisions[0]["privacy_failed_checks"] == 1
    assert operations == ["decision"]


def test_postgres_cli_cannot_diverge_from_privacy_blocked_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome, publish_calls, _persisted, _context = _execute_isolated(
        monkeypatch,
        _quality_results(pass_checks=25),
        privacy_checks=[
            PrivacyCheck("forbidden_columns_absent", "FAIL", "current failure"),
            PrivacyCheck("classification_leakage", "PASS", "current"),
        ],
    )
    monkeypatch.setattr(
        publication_gate_cli,
        "get_quality_summary",
        lambda _run_id: {
            "total_checks": 25,
            "pass_checks": 25,
            "warn_checks": 0,
            "fail_checks": 0,
            "critical_failures": 0,
        },
    )
    monkeypatch.setattr(
        publication_gate_cli,
        "calculate_quality_score",
        lambda _run_id: 100,
    )
    postgres_input = publication_gate_cli.build_input_from_postgres(
        postgres_run_id=42,
        dataset_name="fact_orders_enriched",
        lgpd_risk_score=0,
        approved_by="test",
    )

    assert outcome.publication_gate is not None
    assert outcome.publication_gate.decision == "BLOCKED"
    assert outcome.publication_gate.privacy_failed_checks == 1
    assert publish_calls == []
    with pytest.raises(RuntimeError, match="falta evidência current-run de privacy"):
        publication_gate_cli.build_decision(postgres_input)


def test_current_privacy_has_authority_over_stale_privacy_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    privacy_reads: list[str] = []

    def read_stale_privacy() -> list[PrivacyCheck]:
        privacy_reads.append("read")
        return [PrivacyCheck("forbidden_columns_absent", "PASS", "stale")]

    monkeypatch.setattr(
        runner,
        "load_privacy_results",
        read_stale_privacy,
        raising=False,
    )

    outcome, publish_calls, _persisted, context = _execute_isolated(
        monkeypatch,
        _quality_results(pass_checks=25),
        privacy_checks=[
            PrivacyCheck("forbidden_columns_absent", "FAIL", "current"),
            PrivacyCheck("classification_leakage", "PASS", "current"),
        ],
    )

    assert privacy_reads == []
    assert outcome.publication_gate is not None
    assert outcome.publication_gate.decision == "BLOCKED"
    assert publish_calls == []
    assert context.run_id == "run-current"
    assert context.privacy_controls is not None
    assert context.privacy_controls[0].details == "current"
    assert context.provenance[EvidenceSource.PRIVACY].run_id == "run-current"


def test_wrapper_associates_postgres_and_governance_run_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome, _publish_calls, persisted, context = _execute_isolated(
        monkeypatch,
        _quality_results(pass_checks=25),
        postgres_run_id=123,
    )

    assert outcome.postgres_run_id == 123
    assert isinstance(outcome.postgres_run_id, int)
    assert outcome.governance_run_id == "run-current"
    assert isinstance(outcome.governance_run_id, str)
    assert persisted[0] == outcome.postgres_run_id
    assert context.run_id == outcome.governance_run_id
    privacy_provenance = context.provenance[EvidenceSource.PRIVACY]
    classification_provenance = context.provenance[EvidenceSource.CLASSIFICATION]
    assert privacy_provenance.run_id == outcome.governance_run_id
    assert classification_provenance.run_id == outcome.governance_run_id
    assert privacy_provenance.execution_step == "privacy_preflight"
    assert classification_provenance.execution_step == "privacy_preflight"
    assert context.residual_privacy_risk_provenance is not None
    assert context.residual_privacy_risk_provenance.run_id == "run-current"
    assert (
        context.residual_privacy_risk_provenance.execution_step
        == "privacy_preflight"
    )


def test_all_pass_quality_authorizes_publish_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions: list[dict[str, object]] = []
    operations: list[str] = []
    outcome, publish_calls, _persisted, _context = _execute_isolated(
        monkeypatch,
        _quality_results(pass_checks=25),
        persisted_decisions=decisions,
        operation_calls=operations,
    )

    assert outcome.publication_gate is not None
    assert outcome.publication_gate.decision == "APPROVED"
    assert outcome.publication_gate.quality_score == 100
    assert publish_calls == ["publish"]
    assert decisions[0]["decision"] == "APPROVED"
    assert operations == ["decision", "publish"]


def test_blocked_decision_is_persisted_before_main_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    persisted_decisions: list[dict[str, object]] = []
    quality_results = _quality_results(pass_checks=25)
    source = pd.DataFrame({"order_id": ["raw-order"]})
    candidate = pd.DataFrame({"order_id": ["order_id_token"]})

    def run_steps(
        selected_steps: list[str],
        *,
        continue_on_error: bool,
    ) -> list[platform_pipeline.StepExecution]:
        del continue_on_error
        context = platform_pipeline._ACTIVE_GOVERNANCE_CONTEXT.get()
        assert context is not None
        if selected_steps == ["quality"]:
            context.record_quality(quality_results)
        if "publish" in selected_steps:
            events.append("publish")
        return []

    def persist_decision(**kwargs: object) -> bool:
        events.append("decision")
        persisted_decisions.append(dict(kwargs))
        return True

    monkeypatch.setattr(
        runner,
        "parse_args",
        lambda: argparse.Namespace(
            config="config.yml",
            steps=["quality", "publish"],
            continue_on_error=False,
        ),
    )
    monkeypatch.setattr(runner, "load_config", lambda _path: {})
    monkeypatch.setattr(runner, "configure_logging", lambda: None)
    monkeypatch.setattr(runner, "start_pipeline_run", lambda **_kwargs: 123)
    monkeypatch.setattr(runner, "build_pipeline_run_id", lambda _started: "run-current")
    monkeypatch.setattr(runner, "run_selected_steps", run_steps)
    monkeypatch.setattr(
        runner,
        "run_privacy_preflight",
        lambda: PrivacyPreflightResult(
            source_df=source,
            published_candidate=candidate,
            contract={},
            policy={},
            checks=[
                PrivacyCheck(
                    "forbidden_columns_absent",
                    "FAIL",
                    "current failure",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        runner,
        "persist_quality_results_to_postgres",
        lambda _run_id, results: len(results),
    )
    monkeypatch.setattr(runner, "save_publication_decision", persist_decision)
    monkeypatch.setattr(
        runner,
        "build_run_metadata",
        lambda _start, _end: PipelineRunMetadata(
            "run-current",
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
            "3.13",
            "test",
            "abc123",
        ),
    )
    monkeypatch.setattr(
        runner,
        "save_pipeline_execution_report",
        lambda *_args: (Path("results.json"), Path("report.md")),
    )
    monkeypatch.setattr(
        runner,
        "finish_pipeline_run",
        lambda **_kwargs: events.append("finish"),
    )

    with pytest.raises(RuntimeError, match="Publication Gate"):
        runner.main()

    assert events == ["decision", "finish"]
    assert persisted_decisions[0]["postgres_run_id"] == 123
    assert persisted_decisions[0]["governance_run_id"] == "run-current"
    assert persisted_decisions[0]["decision"] == "BLOCKED"
    assert persisted_decisions[0]["privacy_failed_checks"] == 1


def test_blocked_gate_finishes_wrapper_as_failed_and_keeps_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocked = evaluate_operational_publication_gate(
        total_checks=0,
        pass_checks=0,
        warn_checks=0,
        fail_checks=0,
        critical_failures=0,
    )
    outcome = runner.GovernedPipelineExecution(
        executions=(),
        publication_gate=blocked,
        quality_results_persisted=0,
        rows_processed=None,
        postgres_run_id=42,
        governance_run_id="run-current",
    )
    finished: dict[str, object] = {}
    monkeypatch.setattr(
        runner,
        "parse_args",
        lambda: argparse.Namespace(
            config="config.yml",
            steps=["quality", "publish"],
            continue_on_error=False,
        ),
    )
    monkeypatch.setattr(runner, "load_config", lambda _path: {})
    monkeypatch.setattr(runner, "configure_logging", lambda: None)
    monkeypatch.setattr(runner, "start_pipeline_run", lambda **_kwargs: 42)
    monkeypatch.setattr(runner, "execute_governed_steps", lambda **_kwargs: outcome)
    monkeypatch.setattr(
        runner,
        "build_run_metadata",
        lambda _start, _end: PipelineRunMetadata(
            "run-current",
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
            "3.13",
            "test",
            "abc123",
        ),
    )
    monkeypatch.setattr(
        runner,
        "save_pipeline_execution_report",
        lambda *_args: (Path("results.json"), Path("report.md")),
    )
    monkeypatch.setattr(
        runner,
        "finish_pipeline_run",
        lambda **kwargs: finished.update(kwargs),
    )

    with pytest.raises(RuntimeError, match="Publication Gate"):
        runner.main()

    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert finished["status"] == "FAILED"
    assert "Publication Gate" in str(finished["error_message"])
    assert payload["publication_gate"]["decision"] == "BLOCKED"
    assert payload["status"] == "failed"
