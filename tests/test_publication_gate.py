from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import pytest

import scripts.run_publication_gate as publication_gate_cli
from scripts.run_publication_gate import evaluate_publication_gate
from src.publication_gate import evaluate_publication_readiness


def test_approved_dataset() -> None:
    result = evaluate_publication_readiness(
        data_quality_score=95,
        privacy_risk_score=20,
        critical_rule_failures=0,
        freshness_status="fresh",
        schema_contract_status="passed",
        has_sensitive_data_without_protection=False,
    )
    assert result.decision == "Approved"
    assert result.severity == "Low"
    assert result.reasons
    assert result.required_actions


def test_blocked_by_critical_rule_failures() -> None:
    result = evaluate_publication_readiness(
        data_quality_score=95,
        privacy_risk_score=20,
        critical_rule_failures=2,
        freshness_status="fresh",
        schema_contract_status="passed",
        has_sensitive_data_without_protection=False,
    )
    assert result.decision == "Blocked"
    assert result.severity == "Critical"
    assert any("Critical rule failures" in reason for reason in result.reasons)


def test_blocked_by_unprotected_sensitive_data() -> None:
    result = evaluate_publication_readiness(
        data_quality_score=95,
        privacy_risk_score=20,
        critical_rule_failures=0,
        freshness_status="fresh",
        schema_contract_status="passed",
        has_sensitive_data_without_protection=True,
    )
    assert result.decision == "Blocked"
    assert result.severity == "Critical"
    assert any(
        "Sensitive data found without masking/anonymization" in reason
        for reason in result.reasons
    )


def test_blocked_by_failed_schema_contract() -> None:
    result = evaluate_publication_readiness(
        data_quality_score=95,
        privacy_risk_score=20,
        critical_rule_failures=0,
        freshness_status="fresh",
        schema_contract_status="failed",
        has_sensitive_data_without_protection=False,
    )
    assert result.decision == "Blocked"
    assert result.severity == "Critical"
    assert any(
        "Schema contract validation failed" in reason for reason in result.reasons
    )


def test_needs_review_low_data_quality_score() -> None:
    result = evaluate_publication_readiness(
        data_quality_score=70,
        privacy_risk_score=20,
        critical_rule_failures=0,
        freshness_status="fresh",
        schema_contract_status="passed",
        has_sensitive_data_without_protection=False,
    )
    assert result.decision == "Needs Review"
    assert result.severity == "Medium"
    assert any(
        "Data quality score below recommended threshold" in reason
        for reason in result.reasons
    )


def test_needs_review_elevated_privacy_risk_score() -> None:
    result = evaluate_publication_readiness(
        data_quality_score=95,
        privacy_risk_score=65,
        critical_rule_failures=0,
        freshness_status="fresh",
        schema_contract_status="passed",
        has_sensitive_data_without_protection=False,
    )
    assert result.decision == "Needs Review"
    assert result.severity == "Medium"
    assert any("Privacy risk score is elevated" in reason for reason in result.reasons)


def test_needs_review_warning_or_stale_freshness_status() -> None:
    warning_result = evaluate_publication_readiness(
        data_quality_score=95,
        privacy_risk_score=20,
        critical_rule_failures=0,
        freshness_status="warning",
        schema_contract_status="passed",
        has_sensitive_data_without_protection=False,
    )
    stale_result = evaluate_publication_readiness(
        data_quality_score=95,
        privacy_risk_score=20,
        critical_rule_failures=0,
        freshness_status="stale",
        schema_contract_status="passed",
        has_sensitive_data_without_protection=False,
    )

    assert warning_result.decision == "Needs Review"
    assert stale_result.decision == "Needs Review"
    assert warning_result.severity == "Medium"
    assert stale_result.severity == "High"
    assert any(
        "Freshness status requires attention" in reason
        for reason in warning_result.reasons
    )
    assert any(
        "Freshness status requires attention" in reason
        for reason in stale_result.reasons
    )


def test_returned_object_contains_required_fields() -> None:
    result = evaluate_publication_readiness(
        data_quality_score=95,
        privacy_risk_score=20,
        critical_rule_failures=0,
        freshness_status="fresh",
        schema_contract_status="passed",
        has_sensitive_data_without_protection=False,
    )
    assert hasattr(result, "decision")
    assert hasattr(result, "severity")
    assert hasattr(result, "reasons")
    assert hasattr(result, "required_actions")


def test_cli_publication_gate_rules_cover_approved_review_and_blocked() -> None:
    assert (
        evaluate_publication_gate(
            quality_score=92,
            lgpd_risk_score=45,
            critical_issues=0,
        )[0]
        == "Approved"
    )
    assert (
        evaluate_publication_gate(
            quality_score=75,
            lgpd_risk_score=70,
            critical_issues=0,
        )[0]
        == "Needs Review"
    )
    assert (
        evaluate_publication_gate(
            quality_score=60,
            lgpd_risk_score=85,
            critical_issues=2,
        )[0]
        == "Blocked"
    )


def test_postgres_cli_without_current_privacy_refuses_operational_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "publication_decisions.csv"
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
    monkeypatch.setattr(
        publication_gate_cli,
        "parse_args",
        lambda: argparse.Namespace(
            postgres_run_id=42,
            dataset_name="fact_orders_enriched",
            quality_score=None,
            lgpd_risk_score=0,
            critical_issues=0,
            execution_id="publication-current",
            approved_by="test",
            input_file=None,
            output_file=output_path,
        ),
    )

    with pytest.raises(RuntimeError, match="falta evidência current-run de privacy"):
        publication_gate_cli.main()

    assert not output_path.exists()


@pytest.mark.parametrize("suffix", [".json", ".csv"])
def test_historical_input_file_supplies_privacy_score_and_preserves_csv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, suffix: str,
) -> None:
    source = tmp_path / ("synthetic" + suffix)
    output = tmp_path / "decisions.csv"
    row = {"dataset_name": "synthetic", "quality_score": 95,
           "lgpd_risk_score": 20, "critical_issues": 0}
    if suffix == ".json":
        source.write_text(json.dumps(row), encoding="utf-8")
    else:
        with source.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
    header = ["execution_id", "dataset_name", "quality_score", "lgpd_risk_score",
              "critical_issues", "decision", "reason", "approved_by", "approved_at"]
    with output.open("w", encoding="utf-8", newline="") as stream:
        csv_writer = csv.writer(stream)
        csv_writer.writerow(header)
        csv_writer.writerow(["old", "synthetic", 95, 20, 0, "Approved", "test", "test", ""])
    before = output.read_bytes()
    monkeypatch.setattr(sys, "argv", ["run_publication_gate.py", "--input-file",
                                     str(source), "--output-file", str(output)])
    assert publication_gate_cli.main() == 0
    assert output.read_bytes().startswith(before)
    with output.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == header
    assert len(rows) == 2
    assert rows[1]["decision"] == "Approved"
    assert rows[1]["lgpd_risk_score"] == "20"
    assert None not in rows[1]


def test_historical_append_rejects_incompatible_header_without_writing(tmp_path: Path) -> None:
    output = tmp_path / "decisions.csv"
    output.write_text("execution_id,unexpected\nold,synthetic\n", encoding="utf-8")
    before = output.read_bytes()
    decision = publication_gate_cli.build_decision(
        publication_gate_cli.PublicationGateInput("synthetic", 95, 20, 0, "current", "test")
    )
    with pytest.raises(ValueError, match="header is incompatible"):
        publication_gate_cli.append_decisions([decision], output)
    assert output.read_bytes() == before


def test_explicit_historical_input_still_requires_privacy_score(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_publication_gate.py", "--dataset-name", "synthetic",
                                     "--quality-score", "95"])
    with pytest.raises(SystemExit, match="--lgpd-risk-score"):
        publication_gate_cli.build_inputs(publication_gate_cli.parse_args())
