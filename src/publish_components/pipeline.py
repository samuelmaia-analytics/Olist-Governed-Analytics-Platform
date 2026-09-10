from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from src.publish_components.models import (
    PrivacyCheck,
    PrivacyPreflightResult,
    PublishedArtifacts,
)


def evaluate_privacy_preflight(
    *,
    load_internal_fact_fn: Callable[[], pd.DataFrame],
    build_published_fn: Callable[[pd.DataFrame], pd.DataFrame],
    load_contract_fn: Callable[[], dict[str, Any]],
    load_policy_fn: Callable[[dict[str, Any]], dict[str, Any]],
    validate_privacy_fn: Callable[..., list[PrivacyCheck]],
) -> PrivacyPreflightResult:
    """Evaluate the existing publish privacy controls entirely in memory."""

    internal_df = load_internal_fact_fn()
    published_df = build_published_fn(internal_df)
    contract = load_contract_fn()
    policy = load_policy_fn(contract)
    checks = validate_privacy_fn(
        published_df, contract, policy, source_df=internal_df
    )
    return PrivacyPreflightResult(
        source_df=internal_df,
        published_candidate=published_df,
        contract=contract,
        policy=policy,
        checks=checks,
    )


def run_publish_dashboard(
    *,
    load_internal_fact_fn: Callable[[], pd.DataFrame],
    build_published_fn: Callable[[pd.DataFrame], pd.DataFrame],
    load_contract_fn: Callable[[], dict[str, Any]],
    load_policy_fn: Callable[[dict[str, Any]], dict[str, Any]],
    validate_privacy_fn: Callable[..., list[PrivacyCheck]],
    save_privacy_results_fn: Callable[[list[PrivacyCheck]], object],
    save_outputs_fn: Callable[[pd.DataFrame], PublishedArtifacts],
    save_report_fn: Callable[
        [PublishedArtifacts, dict[str, Any], dict[str, Any], list[PrivacyCheck]], object
    ],
    capture_privacy_results_fn: Callable[[list[PrivacyCheck]], None] | None = None,
    capture_privacy_material_fn: Callable[
        [pd.DataFrame, pd.DataFrame, list[PrivacyCheck]], None
    ]
    | None = None,
) -> PublishedArtifacts:
    preflight = evaluate_privacy_preflight(
        load_internal_fact_fn=load_internal_fact_fn,
        build_published_fn=build_published_fn,
        load_contract_fn=load_contract_fn,
        load_policy_fn=load_policy_fn,
        validate_privacy_fn=validate_privacy_fn,
    )
    internal_df = preflight.source_df
    published_df = preflight.published_candidate
    contract = preflight.contract
    policy = preflight.policy
    checks = preflight.checks
    if capture_privacy_results_fn is not None:
        capture_privacy_results_fn(checks)
    if capture_privacy_material_fn is not None:
        capture_privacy_material_fn(internal_df, published_df, checks)
    save_privacy_results_fn(checks)
    failures = [check for check in checks if check.status == "FAIL"]
    if failures:
        failed_names = ", ".join(check.check_name for check in failures)
        raise RuntimeError(
            "Validação LGPD/governança falhou na camada publicada: "
            f"{failed_names}"
        )
    artifacts = save_outputs_fn(published_df)
    save_report_fn(artifacts, contract, policy, checks)
    return artifacts
