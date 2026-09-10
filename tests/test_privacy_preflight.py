from __future__ import annotations

from typing import TypeVar

import pandas as pd

import src.publish_dashboard as facade
from src.publish_components.models import PrivacyCheck
from src.publish_components.pipeline import evaluate_privacy_preflight

T = TypeVar("T")


def test_privacy_preflight_builds_current_candidate_without_writes() -> None:
    calls: list[str] = []
    source = pd.DataFrame({"order_id": ["raw"]})
    candidate = pd.DataFrame({"order_id": ["order_id_token"]})
    contract: dict[str, object] = {"policy_domain": "commerce"}
    policy: dict[str, object] = {"version": 1}
    checks = [PrivacyCheck("forbidden_columns_absent", "FAIL", "current")]

    def record_call(label: str, result: T) -> T:
        calls.append(label)
        return result

    result = evaluate_privacy_preflight(
        load_internal_fact_fn=lambda: record_call("load", source),
        build_published_fn=lambda frame: record_call("build", candidate),
        load_contract_fn=lambda: record_call("contract", contract),
        load_policy_fn=lambda value: record_call("policy", policy),
        validate_privacy_fn=(
            lambda *args, **kwargs: record_call("validate", checks)
        ),
    )

    assert calls == ["load", "build", "contract", "policy", "validate"]
    assert result.source_df is source
    assert result.published_candidate is candidate
    assert result.contract is contract
    assert result.policy is policy
    assert result.checks is checks
    assert result.failed_checks == 1
    assert result.blocked is True


def test_preflight_facade_cannot_write_publish_artifacts(monkeypatch) -> None:
    source = pd.DataFrame({"order_id": ["raw"]})
    candidate = pd.DataFrame({"order_id": ["order_id_token"]})
    checks = [
        PrivacyCheck("forbidden_columns_absent", "PASS", "current"),
        PrivacyCheck("classification_leakage", "PASS", "current"),
    ]
    writes: list[str] = []

    monkeypatch.setattr(facade, "load_internal_fact", lambda: source)
    monkeypatch.setattr(facade, "build_published_dashboard_table", lambda _df: candidate)
    monkeypatch.setattr(facade, "load_privacy_contract", lambda: {})
    monkeypatch.setattr(facade, "load_domain_policy", lambda _contract: {})
    monkeypatch.setattr(
        facade,
        "validate_privacy_controls",
        lambda *_args, **_kwargs: checks,
    )
    monkeypatch.setattr(
        facade,
        "save_privacy_results",
        lambda *_args, **_kwargs: writes.append("privacy_csv"),
    )
    monkeypatch.setattr(
        facade,
        "save_outputs",
        lambda *_args, **_kwargs: writes.append("published_outputs"),
    )
    monkeypatch.setattr(
        facade,
        "save_report",
        lambda *_args, **_kwargs: writes.append("report"),
    )

    result = facade.run_privacy_preflight()

    assert result.source_df is source
    assert result.published_candidate is candidate
    assert result.checks is checks
    assert result.failed_checks == 0
    assert writes == []
