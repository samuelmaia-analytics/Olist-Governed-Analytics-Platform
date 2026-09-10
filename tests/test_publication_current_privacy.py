from __future__ import annotations

from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from src.lgpd_classifier import classify_dataframe_columns
from src.publication_evidence.privacy_inputs import (
    SensitiveDataProtectionResult,
    build_current_privacy_inputs,
    calculate_current_privacy_risk,
    evaluate_sensitive_data_protection,
)
from src.publication_provenance.context import PipelineGovernanceContext
from src.publication_provenance.models import EvidenceSource
from src.publication_provenance.validation import (
    validate_evidence_provenance,
)
from src.publish_components.models import PrivacyCheck
from src.risk_scoring import calculate_privacy_risk_score


def _checks(*, material_status: str = "PASS") -> list[PrivacyCheck]:
    return [
        PrivacyCheck("forbidden_columns_absent", material_status, "material"),
        PrivacyCheck("classification_leakage", material_status, "material"),
        PrivacyCheck("pseudonymized__customer_unique_id", "PASS", "token"),
    ]


def test_current_privacy_risk_reuses_canonical_scoring_semantics() -> None:
    source = pd.DataFrame(
        {
            "customer_unique_id": ["customer-1"],
            "health_note": ["restricted"],
            "cpf": ["123.456.789-00"],
            "metric": [1],
        }
    )
    classification = classify_dataframe_columns(source)

    current = calculate_current_privacy_risk(classification, total_rows=len(source))
    canonical = calculate_privacy_risk_score(classification, len(source))

    assert current == canonical
    assert current is not None
    assert current["score"] > 30


@pytest.mark.parametrize("classification", [None, pd.DataFrame()])
def test_current_privacy_risk_keeps_absent_or_empty_input_unknown(
    classification: pd.DataFrame | None,
) -> None:
    assert calculate_current_privacy_risk(classification, total_rows=0) is None


def test_material_protection_accepts_removed_and_validly_pseudonymized_data() -> None:
    classification = pd.DataFrame(
        {
            "column_name": ["cpf", "customer_unique_id"],
            "lgpd_classification": ["personal_data", "personal_data"],
            "recommended_action": ["remove", "mask"],
        }
    )
    published = pd.DataFrame({"customer_unique_id": ["cust_token"]})

    result = evaluate_sensitive_data_protection(
        published, classification, _checks()
    )

    assert result == SensitiveDataProtectionResult(True, True)


def test_material_protection_rejects_exposed_sensitive_data() -> None:
    classification = pd.DataFrame(
        {
            "column_name": ["health_note"],
            "lgpd_classification": ["sensitive_personal_data"],
            "recommended_action": ["remove"],
        }
    )
    published = pd.DataFrame({"health_note": ["restricted"]})

    result = evaluate_sensitive_data_protection(
        published, classification, _checks()
    )

    assert result == SensitiveDataProtectionResult(False, True)


def test_material_protection_does_not_treat_recommendation_as_proof() -> None:
    classification = pd.DataFrame(
        {
            "column_name": ["customer_unique_id"],
            "lgpd_classification": ["personal_data"],
            "recommended_action": ["mask"],
        }
    )
    published = pd.DataFrame({"customer_unique_id": ["raw-customer"]})

    result = evaluate_sensitive_data_protection(
        published,
        classification,
        _checks()[:-1],
    )

    assert result == SensitiveDataProtectionResult(False, True)


@pytest.mark.parametrize(
    ("published", "classification", "checks"),
    [
        (None, pd.DataFrame({"column_name": ["cpf"]}), _checks()),
        (pd.DataFrame(), None, _checks()),
        (pd.DataFrame(), pd.DataFrame(), _checks()),
        (pd.DataFrame(), pd.DataFrame({"column_name": ["cpf"]}), None),
    ],
)
def test_material_protection_preserves_insufficient_evidence_as_unknown(
    published: pd.DataFrame | None,
    classification: pd.DataFrame | None,
    checks: list[PrivacyCheck] | None,
) -> None:
    assert evaluate_sensitive_data_protection(
        published, classification, checks
    ) == SensitiveDataProtectionResult(None, False)


def test_current_privacy_inputs_are_frozen_and_do_not_read_history() -> None:
    source = pd.DataFrame({"customer_unique_id": ["customer-1"]})
    published = pd.DataFrame({"customer_unique_id": ["cust_token"]})

    current = build_current_privacy_inputs(source, published, _checks())

    assert current.risk_result is not None
    assert current.protection.protected is True
    with pytest.raises(FrozenInstanceError):
        current.protection.protected = False  # type: ignore[misc]


def test_same_run_privacy_and_classification_enable_provenance() -> None:
    context = PipelineGovernanceContext("run-x")
    source = pd.DataFrame({"customer_unique_id": ["customer-1"]})
    published = pd.DataFrame({"customer_unique_id": ["cust_token"]})
    context.record_current_privacy(source, published, _checks())

    validation = validate_evidence_provenance(
        context.build_provenanced_evidence(),
        {EvidenceSource.PRIVACY, EvidenceSource.CLASSIFICATION},
    )

    assert validation.valid is True
    assert context.build_provenanced_evidence().evidence.privacy_risk_score is not None
    assert (
        context.build_provenanced_evidence().evidence.sensitive_data_protected
        is True
    )
