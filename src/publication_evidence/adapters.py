from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias, TypeVar, cast

import pandas as pd

from src.business_rule_components.models import BusinessRuleResult
from src.governance_types import FreshnessStatus, PrivacyRiskResult
from src.monitoring_components.models import MonitoringCheckResult
from src.observability_components.models import ObservabilityCheck
from src.publication_evidence.models import EvidenceStatus, PublicationEvidence
from src.publication_evidence.privacy_inputs import SensitiveDataProtectionResult
from src.publish_components.models import PrivacyCheck
from src.quality_components.models import QualityCheckResult
from src.schema_contract_components.models import ContractCheck

T = TypeVar("T")
Rows: TypeAlias = Sequence[T] | pd.DataFrame | None


@dataclass(frozen=True)
class QualityEvidence:
    status: EvidenceStatus
    score: int | None
    failed_checks: int | None
    warning_checks: int | None
    critical_failures: int | None


@dataclass(frozen=True)
class CheckCollectionEvidence:
    status: EvidenceStatus
    failed_checks: int | None


@dataclass(frozen=True)
class PrivacyEvidence:
    risk_score: int | None
    controls_status: EvidenceStatus
    failed_checks: int | None
    sensitive_data_protected: bool | None


@dataclass(frozen=True)
class MonitoringEvidence:
    status: EvidenceStatus
    failed_checks: int | None
    freshness_status: FreshnessStatus


@dataclass(frozen=True)
class ObservabilityEvidence:
    status: EvidenceStatus
    failed_checks: int | None
    insufficient_history_checks: int | None


def _records(rows: Rows[T]) -> list[T | Mapping[str, Any]] | None:
    if rows is None:
        return None
    if isinstance(rows, pd.DataFrame):
        return cast(
            list[T | Mapping[str, Any]], rows.to_dict(orient="records")
        )
    return list(rows)


def _value(record: object, field: str, default: object = None) -> object:
    if isinstance(record, Mapping):
        return record.get(field, default)
    return getattr(record, field, default)


def _normalized_status(record: object) -> str:
    return str(_value(record, "status", "")).strip().upper()


def _aggregate_status(records: list[object]) -> EvidenceStatus:
    statuses = [_normalized_status(record) for record in records]
    if not statuses or any(status not in {"PASS", "WARN", "FAIL"} for status in statuses):
        return "unknown"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def adapt_operational_quality(
    results: Rows[QualityCheckResult],
) -> QualityEvidence:
    records = _records(results)
    if records is None:
        return QualityEvidence("missing", None, None, None, None)
    if not records:
        return QualityEvidence("unknown", None, 0, 0, 0)

    failed = sum(_normalized_status(record) == "FAIL" for record in records)
    warnings = sum(_normalized_status(record) == "WARN" for record in records)
    critical = sum(
        _normalized_status(record) == "FAIL"
        and str(_value(record, "severity", "")).strip().lower()
        in {"high", "critical"}
        for record in records
    )
    return QualityEvidence(
        status=_aggregate_status(cast(list[object], records)),
        score=max(0, 100 - (failed * 10)),
        failed_checks=failed,
        warning_checks=warnings,
        critical_failures=critical,
    )


def _adapt_check_collection(results: Rows[T]) -> CheckCollectionEvidence:
    records = _records(results)
    if records is None:
        return CheckCollectionEvidence("missing", None)
    if not records:
        return CheckCollectionEvidence("unknown", 0)
    failed = sum(_normalized_status(record) == "FAIL" for record in records)
    return CheckCollectionEvidence(
        _aggregate_status(cast(list[object], records)), failed
    )


def adapt_schema_contracts(
    results: Rows[ContractCheck],
) -> CheckCollectionEvidence:
    return _adapt_check_collection(results)


def adapt_business_rules(
    results: Rows[BusinessRuleResult],
) -> CheckCollectionEvidence:
    return _adapt_check_collection(results)


def _privacy_score(risk_result: PrivacyRiskResult | Mapping[str, object] | None) -> int | None:
    if risk_result is None:
        return None
    value = risk_result.get("score")
    if value is None:
        return None
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _sensitive_data_protected(classification_df: pd.DataFrame | None) -> bool | None:
    if classification_df is None or classification_df.empty:
        return None
    required = {"lgpd_classification", "recommended_action"}
    if not required.issubset(classification_df.columns):
        return None
    sensitive = classification_df[
        classification_df["lgpd_classification"].astype(str)
        == "sensitive_personal_data"
    ]
    if sensitive.empty:
        return True
    return bool(
        sensitive["recommended_action"]
        .astype(str)
        .isin(["anonymize", "remove"])
        .all()
    )


def adapt_privacy(
    *,
    controls: Rows[PrivacyCheck],
    risk_result: PrivacyRiskResult | Mapping[str, object] | None,
    classification_df: pd.DataFrame | None,
    protection_result: SensitiveDataProtectionResult | None = None,
) -> PrivacyEvidence:
    control_evidence = _adapt_check_collection(controls)
    return PrivacyEvidence(
        risk_score=_privacy_score(risk_result),
        controls_status=control_evidence.status,
        failed_checks=control_evidence.failed_checks,
        sensitive_data_protected=(
            protection_result.protected
            if protection_result is not None
            else _sensitive_data_protected(classification_df)
        ),
    )


def _freshness_from_monitoring(records: list[object]) -> FreshnessStatus:
    freshness = next(
        (
            record
            for record in records
            if str(_value(record, "check_name", ""))
            == "published_file_freshness_hours"
        ),
        None,
    )
    if freshness is None:
        return "unknown"
    if _normalized_status(freshness) == "PASS":
        return "fresh"
    metric = pd.to_numeric(
        cast(float | str, _value(freshness, "metric_value")), errors="coerce"
    )
    threshold = pd.to_numeric(
        cast(float | str, _value(freshness, "threshold")), errors="coerce"
    )
    if (
        pd.notna(metric)
        and pd.notna(threshold)
        and float(metric) <= float(threshold) * 1.5
    ):
        return "warning"
    if _normalized_status(freshness) == "FAIL":
        return "stale"
    return "unknown"


def adapt_monitoring(
    results: Rows[MonitoringCheckResult],
) -> MonitoringEvidence:
    records = _records(results)
    if records is None:
        return MonitoringEvidence("missing", None, "unknown")
    if not records:
        return MonitoringEvidence("unknown", 0, "unknown")
    objects = cast(list[object], records)
    return MonitoringEvidence(
        status=_aggregate_status(objects),
        failed_checks=sum(_normalized_status(record) == "FAIL" for record in objects),
        freshness_status=_freshness_from_monitoring(objects),
    )


def adapt_observability(
    results: Rows[ObservabilityCheck],
) -> ObservabilityEvidence:
    records = _records(results)
    if records is None:
        return ObservabilityEvidence("missing", None, None)
    if not records:
        return ObservabilityEvidence("unknown", 0, 0)
    objects = cast(list[object], records)
    return ObservabilityEvidence(
        status=_aggregate_status(objects),
        failed_checks=sum(_normalized_status(record) == "FAIL" for record in objects),
        insufficient_history_checks=sum(
            str(_value(record, "metric_value", "")) == "insufficient_history"
            for record in objects
        ),
    )


def build_publication_evidence(
    *,
    quality_results: Rows[QualityCheckResult] = None,
    schema_results: Rows[ContractCheck] = None,
    business_rule_results: Rows[BusinessRuleResult] = None,
    privacy_controls: Rows[PrivacyCheck] = None,
    privacy_risk_result: PrivacyRiskResult | Mapping[str, object] | None = None,
    classification_df: pd.DataFrame | None = None,
    sensitive_data_protection: SensitiveDataProtectionResult | None = None,
    monitoring_results: Rows[MonitoringCheckResult] = None,
    observability_results: Rows[ObservabilityCheck] = None,
) -> PublicationEvidence:
    quality = adapt_operational_quality(quality_results)
    schema = adapt_schema_contracts(schema_results)
    business_rules = adapt_business_rules(business_rule_results)
    privacy = adapt_privacy(
        controls=privacy_controls,
        risk_result=privacy_risk_result,
        classification_df=classification_df,
        protection_result=sensitive_data_protection,
    )
    monitoring = adapt_monitoring(monitoring_results)
    observability = adapt_observability(observability_results)
    return PublicationEvidence(
        quality_status=quality.status,
        quality_score=quality.score,
        quality_failed_checks=quality.failed_checks,
        quality_warning_checks=quality.warning_checks,
        critical_quality_failures=quality.critical_failures,
        schema_status=schema.status,
        business_rules_status=business_rules.status,
        business_rule_failed_checks=business_rules.failed_checks,
        privacy_risk_score=privacy.risk_score,
        privacy_controls_status=privacy.controls_status,
        privacy_failed_checks=privacy.failed_checks,
        sensitive_data_protected=privacy.sensitive_data_protected,
        freshness_status=monitoring.freshness_status,
        monitoring_status=monitoring.status,
        monitoring_failed_checks=monitoring.failed_checks,
        observability_status=observability.status,
        observability_failed_checks=observability.failed_checks,
        observability_insufficient_history_checks=(
            observability.insufficient_history_checks
        ),
    )
