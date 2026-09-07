from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from src.publish_components.models import PrivacyCheck


def _validate_prefixed_tokens(series: pd.Series, prefix: str) -> bool:
    non_null = series.dropna()
    if non_null.empty:
        return True
    return all(
        isinstance(value, str) and value.startswith(prefix) for value in non_null
    )


def validate_privacy_controls(
    df: pd.DataFrame,
    contract: dict[str, Any],
    policy: dict[str, Any],
    source_df: pd.DataFrame | None = None,
    *,
    classification_rows: Iterable[Mapping[str, object]],
) -> list[PrivacyCheck]:
    checks: list[PrivacyCheck] = []
    actual_columns = set(df.columns)
    required_columns = set(contract.get("required_columns", []))
    forbidden_columns = set(contract.get("forbidden_columns", []))
    unexpected_columns = sorted(actual_columns - required_columns)
    missing_columns = sorted(required_columns - actual_columns)
    forbidden_exposed = sorted(actual_columns & forbidden_columns)

    checks.append(
        PrivacyCheck(
            check_name="required_columns",
            status="PASS" if not missing_columns else "FAIL",
            details=f"Ausentes: {missing_columns if missing_columns else 'nenhuma'}",
        )
    )
    checks.append(
        PrivacyCheck(
            check_name="forbidden_columns_absent",
            status="PASS" if not forbidden_exposed else "FAIL",
            details=f"Presentes indevidas: {forbidden_exposed if forbidden_exposed else 'nenhuma'}",
        )
    )
    checks.append(
        PrivacyCheck(
            check_name="unexpected_columns",
            status="PASS" if not unexpected_columns else "FAIL",
            details=f"Inesperadas: {unexpected_columns if unexpected_columns else 'nenhuma'}",
        )
    )

    pseudonymized_columns = contract.get("pseudonymized_columns", {})
    if isinstance(pseudonymized_columns, dict):
        for column, prefix in pseudonymized_columns.items():
            if column not in df.columns:
                checks.append(
                    PrivacyCheck(
                        f"pseudonymized__{column}",
                        "FAIL",
                        "Coluna obrigatória ausente.",
                    )
                )
                continue
            checks.append(
                PrivacyCheck(
                    check_name=f"pseudonymized__{column}",
                    status=(
                        "PASS"
                        if _validate_prefixed_tokens(df[column], str(prefix))
                        else "FAIL"
                    ),
                    details=f"Prefixo esperado: `{prefix}`",
                )
            )

    default_fill_values = contract.get("default_fill_values", {})
    if isinstance(default_fill_values, dict):
        for column, default_value in default_fill_values.items():
            if column not in df.columns:
                checks.append(
                    PrivacyCheck(
                        f"default_fill__{column}",
                        "FAIL",
                        "Coluna obrigatória ausente.",
                    )
                )
                continue
            null_count = int(df[column].isna().sum())
            has_default = bool(df[column].eq(default_value).any())
            if source_df is not None and column in source_df.columns:
                source_null_mask = source_df[column].isna()
                default_applied = (
                    bool(df.loc[source_null_mask, column].eq(default_value).all())
                    if bool(source_null_mask.any())
                    else True
                )
            else:
                default_applied = has_default or null_count == 0
            checks.append(
                PrivacyCheck(
                    check_name=f"default_fill__{column}",
                    status="PASS" if null_count == 0 and default_applied else "FAIL",
                    details=(
                        f"nulls={null_count} | default_observado={has_default} | "
                        f"default_aplicado={default_applied}"
                    ),
                )
            )

    protected_source_columns = sorted(
        str(row["column"])
        for row in classification_rows
        if row.get("asset") == "fact_orders_enriched"
        and row.get("publication_allowed") is False
        and row.get("published_action") in {"remove", "aggregate_or_remove"}
    )
    leaked_columns = [
        column for column in protected_source_columns if column in actual_columns
    ]
    checks.append(
        PrivacyCheck(
            check_name="classification_leakage",
            status="PASS" if not leaked_columns else "FAIL",
            details=(
                "Colunas sensíveis expostas: "
                f"{leaked_columns if leaked_columns else 'nenhuma'}"
            ),
        )
    )

    policy_required = set(policy.get("required_columns", []))
    policy_forbidden = set(policy.get("forbidden_columns", []))
    policy_pseudonymized = policy.get("pseudonymized_columns", {})
    policy_defaults = policy.get("default_fill_values", {})
    checks.append(
        PrivacyCheck(
            check_name="policy_required_columns_alignment",
            status="PASS" if required_columns == policy_required else "FAIL",
            details=(
                "Contrato e política LGPD devem ter as mesmas colunas obrigatórias."
            ),
        )
    )
    checks.append(
        PrivacyCheck(
            check_name="policy_forbidden_columns_alignment",
            status="PASS" if forbidden_columns == policy_forbidden else "FAIL",
            details=(
                "Contrato e política LGPD devem ter as mesmas colunas proibidas."
            ),
        )
    )
    checks.append(
        PrivacyCheck(
            check_name="policy_pseudonymization_alignment",
            status="PASS" if pseudonymized_columns == policy_pseudonymized else "FAIL",
            details=(
                "Contrato e política LGPD devem ter o mesmo mapeamento de "
                "pseudonimização."
            ),
        )
    )
    checks.append(
        PrivacyCheck(
            check_name="policy_default_fill_alignment",
            status="PASS" if default_fill_values == policy_defaults else "FAIL",
            details=(
                "Contrato e política LGPD devem ter os mesmos defaults de "
                "preenchimento."
            ),
        )
    )

    return checks
