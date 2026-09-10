from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, fields
from typing import get_args

import pytest

from src.publication_evidence.models import EvidenceStatus, PublicationEvidence

EXPECTED_FIELDS = [
    "quality_status",
    "quality_score",
    "quality_failed_checks",
    "quality_warning_checks",
    "critical_quality_failures",
    "schema_status",
    "business_rules_status",
    "business_rule_failed_checks",
    "privacy_risk_score",
    "privacy_controls_status",
    "privacy_failed_checks",
    "sensitive_data_protected",
    "freshness_status",
    "monitoring_status",
    "monitoring_failed_checks",
    "observability_status",
    "observability_failed_checks",
    "observability_insufficient_history_checks",
]


def _missing_evidence() -> PublicationEvidence:
    return PublicationEvidence(
        quality_status="missing",
        quality_score=None,
        quality_failed_checks=None,
        quality_warning_checks=None,
        critical_quality_failures=None,
        schema_status="missing",
        business_rules_status="missing",
        business_rule_failed_checks=None,
        privacy_risk_score=None,
        privacy_controls_status="missing",
        privacy_failed_checks=None,
        sensitive_data_protected=None,
        freshness_status="unknown",
        monitoring_status="missing",
        monitoring_failed_checks=None,
        observability_status="missing",
        observability_failed_checks=None,
        observability_insufficient_history_checks=None,
    )


def test_model_fields_status_vocabulary_and_explicit_absence() -> None:
    evidence = _missing_evidence()

    assert [field.name for field in fields(evidence)] == EXPECTED_FIELDS
    assert get_args(EvidenceStatus) == ("PASS", "WARN", "FAIL", "missing", "unknown")
    assert evidence.quality_score is None
    assert evidence.sensitive_data_protected is None
    assert evidence.freshness_status == "unknown"


def test_model_is_frozen_equal_and_serializable() -> None:
    evidence = _missing_evidence()

    assert evidence == _missing_evidence()
    assert list(asdict(evidence)) == EXPECTED_FIELDS
    with pytest.raises(FrozenInstanceError):
        evidence.quality_status = "PASS"  # type: ignore[misc]
