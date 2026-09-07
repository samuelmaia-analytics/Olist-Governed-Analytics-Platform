from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, cast

import pandas as pd

from src.lgpd_policy import load_policy, validate_policy_shape


def pseudonymize(value: object, prefix: str) -> object:
    if cast(Callable[[object], bool], pd.isna)(value):
        return pd.NA
    digest = hashlib.sha256(f"{prefix}:{value}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def load_domain_policy(contract: dict[str, Any]) -> dict[str, Any]:
    domain = str(contract.get("policy_domain", "")).strip()
    if not domain:
        raise ValueError("Contrato de privacidade sem `policy_domain`.")
    raw_version = contract.get("policy_version")
    version = int(raw_version) if raw_version is not None else None
    policy = load_policy(domain=domain, version=version)
    validate_policy_shape(policy)
    return policy


def build_published_dashboard_table(
    df: pd.DataFrame,
    *,
    pseudonymized_columns: dict[str, str],
    published_columns: list[str],
) -> pd.DataFrame:
    published = df.copy()

    for source_column, prefix in pseudonymized_columns.items():
        published[source_column] = published[source_column].map(
            lambda value: pseudonymize(value, prefix)
        )
    if "seller_id" in published.columns:
        published["seller_key"] = published["seller_id"].map(
            lambda value: pseudonymize(value, "seller_id")
        )

    existing_columns = [
        column for column in published_columns if column in published.columns
    ]
    published = published[existing_columns].copy()

    published["customer_state"] = published["customer_state"].fillna("NA")
    published["seller_state"] = published["seller_state"].fillna("NA")
    published["order_status"] = published["order_status"].fillna("unknown")
    published["payment_type_mode"] = published["payment_type_mode"].fillna("unknown")
    if "seller_volume_tier" in published.columns:
        published["seller_volume_tier"] = published["seller_volume_tier"].fillna(
            "long_tail"
        )

    return published
