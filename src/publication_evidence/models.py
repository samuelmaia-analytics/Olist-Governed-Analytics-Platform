from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.governance_types import FreshnessStatus

EvidenceStatus = Literal["PASS", "WARN", "FAIL", "missing", "unknown"]


@dataclass(frozen=True)
class PublicationEvidence:
    quality_status: EvidenceStatus
    quality_score: int | None
    quality_failed_checks: int | None
    quality_warning_checks: int | None
    critical_quality_failures: int | None
    schema_status: EvidenceStatus
    business_rules_status: EvidenceStatus
    business_rule_failed_checks: int | None
    privacy_risk_score: int | None
    privacy_controls_status: EvidenceStatus
    privacy_failed_checks: int | None
    sensitive_data_protected: bool | None
    freshness_status: FreshnessStatus
    monitoring_status: EvidenceStatus
    monitoring_failed_checks: int | None
    observability_status: EvidenceStatus
    observability_failed_checks: int | None
    observability_insufficient_history_checks: int | None
