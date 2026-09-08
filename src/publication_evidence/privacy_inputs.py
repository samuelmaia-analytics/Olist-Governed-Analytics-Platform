from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.governance_types import PrivacyRiskResult
from src.lgpd_classifier import classify_dataframe_columns
from src.publish_components.models import PrivacyCheck
from src.risk_scoring import calculate_privacy_risk_score


@dataclass(frozen=True)
class SensitiveDataProtectionResult:
    protected: bool | None
    evaluated: bool


@dataclass(frozen=True)
class CurrentPrivacyInputs:
    """Same-run privacy diagnostics before and after publication controls.

    ``risk_result`` and ``classification`` remain temporary compatibility aliases
    for the inherent/source calculation until a future, explicit policy cutover.
    The residual score is diagnostic and uses the unchanged classifier/scorer on
    the published candidate, whose current false positives remain characterized.
    """

    classification: pd.DataFrame | None
    risk_result: PrivacyRiskResult | None
    protection: SensitiveDataProtectionResult
    inherent_classification: pd.DataFrame | None
    residual_classification: pd.DataFrame | None
    inherent_privacy_risk_score: int | None
    residual_privacy_risk_score: int | None


def calculate_current_privacy_risk(
    classification_df: pd.DataFrame | None,
    *,
    total_rows: int,
) -> PrivacyRiskResult | None:
    required = {"column_name", "lgpd_classification"}
    if (
        classification_df is None
        or classification_df.empty
        or not required.issubset(classification_df.columns)
    ):
        return None
    return calculate_privacy_risk_score(classification_df, total_rows)


def evaluate_sensitive_data_protection(
    published_df: pd.DataFrame | None,
    classification_df: pd.DataFrame | None,
    privacy_checks: list[PrivacyCheck] | tuple[PrivacyCheck, ...] | None,
) -> SensitiveDataProtectionResult:
    required_classification = {
        "column_name",
        "lgpd_classification",
        "recommended_action",
    }
    if (
        published_df is None
        or classification_df is None
        or classification_df.empty
        or privacy_checks is None
        or not required_classification.issubset(classification_df.columns)
    ):
        return SensitiveDataProtectionResult(None, False)

    statuses = {check.check_name: check.status for check in privacy_checks}
    material_checks = ("forbidden_columns_absent", "classification_leakage")
    if any(name not in statuses for name in material_checks):
        return SensitiveDataProtectionResult(None, False)
    if any(statuses[name] != "PASS" for name in material_checks):
        return SensitiveDataProtectionResult(False, True)

    protected_rows = classification_df[
        classification_df["recommended_action"]
        .astype(str)
        .isin({"mask", "anonymize", "remove"})
    ]
    for row in protected_rows.itertuples(index=False):
        column = str(row.column_name)
        if column not in published_df.columns:
            continue
        pseudonymization_status = statuses.get(f"pseudonymized__{column}")
        if pseudonymization_status != "PASS":
            return SensitiveDataProtectionResult(False, True)

    return SensitiveDataProtectionResult(True, True)


def build_current_privacy_inputs(
    source_df: pd.DataFrame | None,
    published_df: pd.DataFrame | None,
    privacy_checks: list[PrivacyCheck] | tuple[PrivacyCheck, ...] | None,
) -> CurrentPrivacyInputs:
    inherent_classification = (
        classify_dataframe_columns(source_df)
        if source_df is not None and not source_df.empty
        else None
    )
    residual_classification = (
        classify_dataframe_columns(published_df)
        if published_df is not None and not published_df.empty
        else None
    )
    inherent_risk_result = calculate_current_privacy_risk(
        inherent_classification,
        total_rows=len(source_df) if source_df is not None else 0,
    )
    residual_risk_result = calculate_current_privacy_risk(
        residual_classification,
        total_rows=len(published_df) if published_df is not None else 0,
    )
    protection = evaluate_sensitive_data_protection(
        published_df,
        inherent_classification,
        privacy_checks,
    )
    return CurrentPrivacyInputs(
        classification=inherent_classification,
        risk_result=inherent_risk_result,
        protection=protection,
        inherent_classification=inherent_classification,
        residual_classification=residual_classification,
        inherent_privacy_risk_score=(
            int(inherent_risk_result["score"])
            if inherent_risk_result is not None
            else None
        ),
        residual_privacy_risk_score=(
            int(residual_risk_result["score"])
            if residual_risk_result is not None
            else None
        ),
    )
