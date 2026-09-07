from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import pandas as pd

import src.publish_dashboard as facade
from src.publish_components.models import PrivacyCheck, PublishedArtifacts

T = TypeVar("T")


def test_facade_models_are_the_canonical_component_types() -> None:
    assert facade.PrivacyCheck is PrivacyCheck
    assert facade.PublishedArtifacts is PublishedArtifacts


def test_transformation_and_privacy_wrappers_delegate_dynamically(monkeypatch) -> None:
    frame = pd.DataFrame({"x": [1]})
    transformed = pd.DataFrame({"published": [1]})
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        facade._transformation,
        "pseudonymize",
        lambda value, prefix: observed.update(value=value, prefix=prefix) or "token",
    )

    def fake_build(df: pd.DataFrame, **kwargs: object) -> pd.DataFrame:
        observed["frame"] = df
        observed.update(kwargs)
        return transformed

    monkeypatch.setattr(
        facade._transformation, "build_published_dashboard_table", fake_build
    )
    monkeypatch.setattr(
        facade._privacy,
        "validate_privacy_controls",
        lambda *args, **kwargs: observed.update(privacy=(args, kwargs)) or [],
    )

    assert facade.pseudonymize("raw", "prefix") == "token"
    assert facade.build_published_dashboard_table(frame) is transformed
    assert facade.validate_privacy_controls(frame, {}, {}) == []
    assert observed["frame"] is frame
    assert observed["published_columns"] is facade.PUBLISHED_COLUMNS
    assert observed["pseudonymized_columns"] is facade.PSEUDONYMIZED_COLUMNS


def test_run_wrapper_passes_historic_facade_symbols_to_component(
    tmp_path: Path, monkeypatch
) -> None:
    artifacts = PublishedArtifacts(tmp_path / "x.parquet", tmp_path / "x.csv", 1, 1)
    captured: dict[str, object] = {}

    def fake_pipeline(**kwargs: object) -> PublishedArtifacts:
        captured.update(kwargs)
        return artifacts

    monkeypatch.setattr(facade._pipeline, "run_publish_dashboard", fake_pipeline)

    returned = facade.run_publish_dashboard()

    assert returned is artifacts
    assert captured == {
        "load_internal_fact_fn": facade.load_internal_fact,
        "build_published_fn": facade.build_published_dashboard_table,
        "load_contract_fn": facade.load_privacy_contract,
        "load_policy_fn": facade.load_domain_policy,
        "validate_privacy_fn": facade.validate_privacy_controls,
        "save_privacy_results_fn": facade.save_privacy_results,
        "save_outputs_fn": facade.save_outputs,
        "save_report_fn": facade.save_report,
    }


def test_historical_monkeypatches_on_facade_are_observed(monkeypatch) -> None:
    calls: list[str] = []
    internal = pd.DataFrame({"a": [1]})
    published = pd.DataFrame({"b": [1]})
    checks = [PrivacyCheck("privacy", "PASS", "ok")]
    artifacts = PublishedArtifacts(Path("x.parquet"), Path("x.csv"), 1, 1)

    def record_call(label: str, result: T) -> T:
        calls.append(label)
        return result

    monkeypatch.setattr(facade, "load_internal_fact", lambda: record_call("load", internal))
    monkeypatch.setattr(
        facade,
        "build_published_dashboard_table",
        lambda value: record_call("build", published),
    )
    monkeypatch.setattr(
        facade, "load_privacy_contract", lambda: record_call("contract", {})
    )
    monkeypatch.setattr(
        facade, "load_domain_policy", lambda value: record_call("policy", {})
    )
    monkeypatch.setattr(
        facade,
        "validate_privacy_controls",
        lambda *args, **kwargs: record_call("validate", checks),
    )
    monkeypatch.setattr(
        facade, "save_privacy_results", lambda value: calls.append("privacy")
    )
    monkeypatch.setattr(
        facade, "save_outputs", lambda value: record_call("outputs", artifacts)
    )
    monkeypatch.setattr(
        facade, "save_report", lambda *args: calls.append("report")
    )

    assert facade.run_publish_dashboard() is artifacts
    assert calls == [
        "load",
        "build",
        "contract",
        "policy",
        "validate",
        "privacy",
        "outputs",
        "report",
    ]


def test_historical_public_api_remains_available() -> None:
    names = {
        "PrivacyCheck",
        "PublishedArtifacts",
        "pseudonymize",
        "build_published_dashboard_table",
        "load_domain_policy",
        "load_internal_fact",
        "load_privacy_contract",
        "validate_privacy_controls",
        "save_privacy_results",
        "save_outputs",
        "render_report",
        "save_report",
        "run_publish_dashboard",
    }
    assert all(callable(getattr(facade, name)) for name in names)
