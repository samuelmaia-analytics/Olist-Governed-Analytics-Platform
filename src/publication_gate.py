from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PublicationDecision = Literal["Approved", "Needs Review", "Blocked"]
PublicationSeverity = Literal["Low", "Medium", "High", "Critical"]
FreshnessStatus = Literal["fresh", "warning", "stale"]
SchemaContractStatus = Literal["passed", "failed"]
OperationalPublicationDecision = Literal[
    "APPROVED",
    "APPROVED_WITH_WARNINGS",
    "BLOCKED",
]

# Recommended thresholds (portfolio-grade defaults, easy to tune later)
MIN_DATA_QUALITY_SCORE_REVIEW = 80
PRIVACY_RISK_SCORE_REVIEW = 60
PRIVACY_RISK_SCORE_HIGH = 80


@dataclass(frozen=True)
class PublicationReadinessDecision:
    """Typed governance decision output for publication readiness."""

    decision: PublicationDecision
    severity: PublicationSeverity
    reasons: list[str]
    required_actions: list[str]


@dataclass(frozen=True)
class OperationalPublicationGateDecision:
    """Pre-publish decision derived from same-run Data Quality evidence."""

    decision: OperationalPublicationDecision
    reason: str
    total_checks: int
    pass_checks: int
    warn_checks: int
    fail_checks: int
    critical_failures: int
    quality_score: int
    privacy_failed_checks: int = 0


def evaluate_operational_publication_gate(
    *,
    total_checks: int,
    pass_checks: int,
    warn_checks: int,
    fail_checks: int,
    critical_failures: int,
    privacy_failed_checks: int = 0,
) -> OperationalPublicationGateDecision:
    """Evaluate the operational gate using current-run quality counts only."""

    counts = {
        "total_checks": total_checks,
        "pass_checks": pass_checks,
        "warn_checks": warn_checks,
        "fail_checks": fail_checks,
        "critical_failures": critical_failures,
        "privacy_failed_checks": privacy_failed_checks,
    }
    if any(value < 0 for value in counts.values()):
        raise ValueError("Publication Gate check counts must be non-negative.")

    quality_score = (
        round((pass_checks / total_checks) * 100)
        if total_checks > 0
        else 0
    )

    if total_checks == 0:
        decision: OperationalPublicationDecision = "BLOCKED"
        reason = (
            "Nenhum resultado de qualidade da execução atual está disponível."
        )
    elif pass_checks + warn_checks + fail_checks != total_checks:
        decision = "BLOCKED"
        reason = (
            "As contagens de qualidade da execução atual são inconsistentes."
        )
    elif fail_checks > 0 or critical_failures > 0:
        decision = "BLOCKED"
        reason = (
            "Publicação bloqueada porque a execução atual contém checks "
            "de qualidade reprovados ou falhas críticas."
        )
    elif privacy_failed_checks > 0:
        decision = "BLOCKED"
        reason = (
            "Publicação bloqueada porque a execução atual contém controles "
            "de privacidade reprovados."
        )
    elif warn_checks > 0:
        decision = "APPROVED_WITH_WARNINGS"
        reason = (
            "Publicação autorizada com warnings porque a execução atual "
            "não contém checks reprovados nem falhas críticas."
        )
    else:
        decision = "APPROVED"
        reason = (
            "Publicação autorizada porque todos os checks de qualidade "
            "da execução atual foram aprovados."
        )

    return OperationalPublicationGateDecision(
        decision=decision,
        reason=reason,
        total_checks=total_checks,
        pass_checks=pass_checks,
        warn_checks=warn_checks,
        fail_checks=fail_checks,
        critical_failures=critical_failures,
        quality_score=quality_score,
        privacy_failed_checks=privacy_failed_checks,
    )


def evaluate_publication_readiness(
    *,
    data_quality_score: int,
    privacy_risk_score: int,
    critical_rule_failures: int,
    freshness_status: FreshnessStatus,
    schema_contract_status: SchemaContractStatus,
    has_sensitive_data_without_protection: bool,
) -> PublicationReadinessDecision:
    """
    Evaluate whether a dataset is ready for publication.

    Decision policy:
    - Blocked:
      - critical rule failures > 0
      - sensitive data without protection
      - schema contract failed
    - Needs Review:
      - quality score below recommended threshold
      - elevated privacy risk
      - freshness warning/stale
    - Approved:
      - all quality/privacy/freshness/contract checks acceptable
    """
    reasons: list[str] = []
    required_actions: list[str] = []

    blocked = False
    needs_review = False
    severity_rank = 1  # Low=1, Medium=2, High=3, Critical=4

    if critical_rule_failures > 0:
        blocked = True
        severity_rank = max(severity_rank, 4)
        reasons.append(f"Critical rule failures detected: {critical_rule_failures}.")
        required_actions.append(
            "Resolve critical quality rule failures before publication."
        )

    if has_sensitive_data_without_protection:
        blocked = True
        severity_rank = max(severity_rank, 4)
        reasons.append("Sensitive data found without masking/anonymization.")
        required_actions.append(
            "Mask, anonymize, or remove sensitive data before publication."
        )

    if schema_contract_status == "failed":
        blocked = True
        severity_rank = max(severity_rank, 4)
        reasons.append("Schema contract validation failed.")
        required_actions.append("Fix schema contract violations and revalidate.")

    if data_quality_score < MIN_DATA_QUALITY_SCORE_REVIEW:
        needs_review = True
        severity_rank = max(severity_rank, 2)
        reasons.append(
            f"Data quality score below recommended threshold "
            f"({data_quality_score} < {MIN_DATA_QUALITY_SCORE_REVIEW})."
        )
        required_actions.append(
            "Investigate failed checks and improve data quality score."
        )

    if privacy_risk_score >= PRIVACY_RISK_SCORE_REVIEW:
        needs_review = True
        severity_rank = max(severity_rank, 2)
        reasons.append(
            f"Privacy risk score is elevated ({privacy_risk_score} >= {PRIVACY_RISK_SCORE_REVIEW})."
        )
        required_actions.append("Review privacy controls and mitigation actions.")
    if privacy_risk_score >= PRIVACY_RISK_SCORE_HIGH:
        severity_rank = max(severity_rank, 3)

    if freshness_status in {"warning", "stale"}:
        needs_review = True
        severity_rank = max(severity_rank, 2)
        reasons.append(f"Freshness status requires attention: {freshness_status}.")
        required_actions.append("Refresh dataset and confirm SLA/freshness compliance.")
        if freshness_status == "stale":
            severity_rank = max(severity_rank, 3)

    if blocked:
        decision: PublicationDecision = "Blocked"
    elif needs_review:
        decision = "Needs Review"
    else:
        decision = "Approved"
        reasons.append("All publication controls are within acceptable thresholds.")
        required_actions.append("Proceed with publication and keep routine monitoring.")

    severity_by_rank: dict[int, PublicationSeverity] = {
        1: "Low",
        2: "Medium",
        3: "High",
        4: "Critical",
    }
    severity = severity_by_rank[severity_rank]

    return PublicationReadinessDecision(
        decision=decision,
        severity=severity,
        reasons=reasons,
        required_actions=required_actions,
    )
