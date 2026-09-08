from __future__ import annotations

import builtins
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from src.business_rule_components.models import BusinessRuleResult
from src.monitoring_components.models import MonitoringCheckResult
from src.observability_components.models import ObservabilityCheck
from src.publication_evidence.adapters import (
    adapt_business_rules,
    adapt_monitoring,
    adapt_observability,
    adapt_operational_quality,
    adapt_privacy,
    adapt_schema_contracts,
    build_publication_evidence,
)
from src.publish_components.models import PrivacyCheck
from src.quality_components.models import QualityCheckResult
from src.schema_contract_components.models import ContractCheck


def quality(status: str, severity: str = "medium") -> QualityCheckResult:
    return QualityCheckResult("quality", status, 0.0, 0.0, severity, "details")


def monitoring(
    name: str, status: str, metric: float = 0.0, threshold: float = 36.0
) -> MonitoringCheckResult:
    return MonitoringCheckResult(name, status, metric, threshold, "high", "details")


def observability(
    name: str, status: str, metric: float | str = 0.0
) -> ObservabilityCheck:
    return ObservabilityCheck(name, status, "low", metric, 0.0, "details")


@pytest.mark.parametrize(
    ("results", "status", "score", "failed", "warnings", "critical"),
    [
        ([quality("PASS")], "PASS", 100, 0, 0, 0),
        ([quality("WARN")], "WARN", 100, 0, 1, 0),
        ([quality("FAIL")], "FAIL", 90, 1, 0, 0),
        ([quality("FAIL", "high")], "FAIL", 90, 1, 0, 1),
        ([], "unknown", None, 0, 0, 0),
        (None, "missing", None, None, None, None),
    ],
)
def test_operational_quality_adapter(
    results, status, score, failed, warnings, critical
) -> None:
    result = adapt_operational_quality(results)
    assert (
        result.status,
        result.score,
        result.failed_checks,
        result.warning_checks,
        result.critical_failures,
    ) == (status, score, failed, warnings, critical)


def test_quality_adapter_accepts_materialized_dataframe() -> None:
    result = adapt_operational_quality(
        pd.DataFrame(
            [
                {"status": "WARN", "severity": "medium"},
                {"status": "FAIL", "severity": "critical"},
            ]
        )
    )
    assert (result.status, result.score, result.critical_failures) == ("FAIL", 90, 1)


@pytest.mark.parametrize(
    ("results", "status", "failed"),
    [
        ([ContractCheck("d", "l", "c", "PASS", "ok")], "PASS", 0),
        ([ContractCheck("d", "l", "c", "FAIL", "bad")], "FAIL", 1),
        ([], "unknown", 0),
        (None, "missing", None),
    ],
)
def test_schema_adapter(results, status, failed) -> None:
    result = adapt_schema_contracts(results)
    assert (result.status, result.failed_checks) == (status, failed)


def test_business_rule_adapter_preserves_residual_pass() -> None:
    residual = BusinessRuleResult("rule", "PASS", "high", 8, 0.0071, "tolerated")
    failed = BusinessRuleResult("bad", "FAIL", "medium", 10, 2.0, "failed")

    assert adapt_business_rules([residual]).status == "PASS"
    assert adapt_business_rules([residual]).failed_checks == 0
    assert adapt_business_rules([residual, failed]).status == "FAIL"
    assert adapt_business_rules(None).status == "missing"


def test_privacy_adapter_keeps_risk_controls_and_protection_separate() -> None:
    controls = [
        PrivacyCheck("one", "PASS", "ok"),
        PrivacyCheck("two", "FAIL", "bad"),
    ]
    classification = pd.DataFrame(
        {
            "lgpd_classification": ["sensitive_personal_data", "personal_data"],
            "recommended_action": ["review", "mask"],
        }
    )

    result = adapt_privacy(
        controls=controls,
        risk_result={"score": 22},
        classification_df=classification,
    )

    assert result.risk_score == 22
    assert result.controls_status == "FAIL"
    assert result.failed_checks == 1
    assert result.sensitive_data_protected is False


def test_privacy_adapter_recognizes_protection_and_missing_sources() -> None:
    protected = pd.DataFrame(
        {
            "lgpd_classification": ["sensitive_personal_data"],
            "recommended_action": ["anonymize"],
        }
    )
    result = adapt_privacy(
        controls=[PrivacyCheck("one", "PASS", "ok")],
        risk_result={"score": 60},
        classification_df=protected,
    )
    missing = adapt_privacy(
        controls=None, risk_result=None, classification_df=None
    )

    assert result.sensitive_data_protected is True
    assert result.controls_status == "PASS"
    assert missing.risk_score is None
    assert missing.controls_status == "missing"
    assert missing.sensitive_data_protected is None


def test_monitoring_adapter_aggregates_checks_and_freshness() -> None:
    passed = [monitoring("published_file_freshness_hours", "PASS")] + [
        monitoring(f"check_{index}", "PASS") for index in range(11)
    ]
    warning = [monitoring("published_file_freshness_hours", "FAIL", 45.0, 36.0)]
    stale = [monitoring("published_file_freshness_hours", "FAIL", 60.0, 36.0)]

    assert adapt_monitoring(passed).status == "PASS"
    assert adapt_monitoring(passed).freshness_status == "fresh"
    assert adapt_monitoring(warning).freshness_status == "warning"
    assert adapt_monitoring(stale).freshness_status == "stale"
    assert adapt_monitoring(stale).failed_checks == 1
    assert adapt_monitoring(None).status == "missing"
    assert adapt_monitoring(None).freshness_status == "unknown"


def test_observability_adapter_preserves_insufficient_history_as_pass() -> None:
    insufficient = [
        observability("row_count_anomaly", "PASS", "insufficient_history"),
        observability("null_rate_drift", "PASS", "insufficient_history"),
    ]
    failed = insufficient + [observability("quality_score_trend", "FAIL", -11.0)]

    assert adapt_observability(insufficient).status == "PASS"
    assert adapt_observability(insufficient).insufficient_history_checks == 2
    assert adapt_observability(failed).status == "FAIL"
    assert adapt_observability(failed).failed_checks == 1
    assert adapt_observability(None).status == "missing"


def test_composite_is_deterministic_pure_and_does_not_mutate_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quality_results = [quality("WARN")]
    schema_results = pd.DataFrame([{"status": "PASS"}])
    business_results = [
        BusinessRuleResult("rule", "PASS", "high", 8, 0.0071, "tolerated")
    ]
    privacy_controls = [PrivacyCheck("privacy", "FAIL", "current baseline")]
    classification = pd.DataFrame(
        {
            "lgpd_classification": ["sensitive_personal_data"],
            "recommended_action": ["remove"],
        }
    )
    monitoring_results = [monitoring("published_file_freshness_hours", "PASS")]
    observability_results = [
        observability("row_count_anomaly", "PASS", "insufficient_history")
    ]
    originals = (
        deepcopy(quality_results),
        schema_results.copy(deep=True),
        deepcopy(business_results),
        deepcopy(privacy_controls),
        classification.copy(deep=True),
        deepcopy(monitoring_results),
        deepcopy(observability_results),
    )

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("evidence adapter attempted I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)

    kwargs = {
        "quality_results": quality_results,
        "schema_results": schema_results,
        "business_rule_results": business_results,
        "privacy_controls": privacy_controls,
        "privacy_risk_result": {"score": 22},
        "classification_df": classification,
        "monitoring_results": monitoring_results,
        "observability_results": observability_results,
    }
    first = build_publication_evidence(**kwargs)  # type: ignore[arg-type]
    second = build_publication_evidence(**kwargs)  # type: ignore[arg-type]

    assert first == second
    assert first.quality_status == "WARN"
    assert first.schema_status == "PASS"
    assert first.business_rules_status == "PASS"
    assert first.privacy_controls_status == "FAIL"
    assert first.sensitive_data_protected is True
    assert first.monitoring_status == "PASS"
    assert first.observability_status == "PASS"
    assert quality_results == originals[0]
    pd.testing.assert_frame_equal(schema_results, originals[1])
    assert business_results == originals[2]
    assert privacy_controls == originals[3]
    pd.testing.assert_frame_equal(classification, originals[4])
    assert monitoring_results == originals[5]
    assert observability_results == originals[6]


def test_composite_defaults_represent_all_sources_as_missing() -> None:
    evidence = build_publication_evidence()

    assert evidence.quality_status == "missing"
    assert evidence.schema_status == "missing"
    assert evidence.business_rules_status == "missing"
    assert evidence.privacy_controls_status == "missing"
    assert evidence.monitoring_status == "missing"
    assert evidence.observability_status == "missing"
    assert evidence.freshness_status == "unknown"
