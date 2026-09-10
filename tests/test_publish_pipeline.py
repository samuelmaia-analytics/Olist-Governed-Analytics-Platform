from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from src.publish_components.models import PrivacyCheck, PublishedArtifacts
from src.publish_components.pipeline import run_publish_dashboard


def _dependencies(*, privacy_status: str = "PASS"):
    calls: list[str] = []
    internal = pd.DataFrame({"source": [1]})
    published = pd.DataFrame({"published": [1]})
    contract: dict[str, object] = {"contract": True}
    policy: dict[str, object] = {"policy": True}
    checks = [PrivacyCheck("privacy", privacy_status, "details")]
    artifacts = PublishedArtifacts(Path("x.parquet"), Path("x.csv"), 1, 1)

    def load_fact() -> pd.DataFrame:
        calls.append("load")
        return internal

    def build(frame: pd.DataFrame) -> pd.DataFrame:
        calls.append("build")
        assert frame is internal
        return published

    def load_contract() -> dict[str, object]:
        calls.append("contract")
        return contract

    def load_policy(value: dict[str, object]) -> dict[str, object]:
        calls.append("policy")
        assert value is contract
        return policy

    def validate(*args: object, **kwargs: object) -> list[PrivacyCheck]:
        calls.append("validate")
        assert args == (published, contract, policy)
        assert kwargs == {"source_df": internal}
        return checks

    def save_privacy(value: list[PrivacyCheck]) -> None:
        calls.append("save_privacy")
        assert value is checks

    def save_outputs(frame: pd.DataFrame) -> PublishedArtifacts:
        calls.append("save_outputs")
        assert frame is published
        return artifacts

    def save_report(*args: object) -> None:
        calls.append("save_report")
        assert args == (artifacts, contract, policy, checks)

    dependencies = {
        "load_internal_fact_fn": load_fact,
        "build_published_fn": build,
        "load_contract_fn": load_contract,
        "load_policy_fn": load_policy,
        "validate_privacy_fn": validate,
        "save_privacy_results_fn": save_privacy,
        "save_outputs_fn": save_outputs,
        "save_report_fn": save_report,
    }
    return calls, artifacts, dependencies


def test_pipeline_preserves_order_identity_and_return_value() -> None:
    calls, artifacts, dependencies = _dependencies()

    returned = run_publish_dashboard(**dependencies)  # type: ignore[arg-type]

    assert returned is artifacts
    assert calls == [
        "load",
        "build",
        "contract",
        "policy",
        "validate",
        "save_privacy",
        "save_outputs",
        "save_report",
    ]


def test_pipeline_exposes_current_privacy_material_without_copying() -> None:
    calls, _, dependencies = _dependencies()
    captured: list[object] = []

    dependencies["capture_privacy_material_fn"] = (
        lambda source, published, checks: captured.extend(
            [source, published, checks]
        )
    )

    run_publish_dashboard(**dependencies)  # type: ignore[arg-type]

    assert captured[0] is not captured[1]
    assert cast(pd.DataFrame, captured[0]).columns.tolist() == ["source"]
    assert cast(pd.DataFrame, captured[1]).columns.tolist() == ["published"]
    assert cast(list[PrivacyCheck], captured[2])[0].check_name == "privacy"
    assert calls.index("validate") < calls.index("save_privacy")


def test_pipeline_saves_privacy_before_block_and_skips_published_outputs() -> None:
    calls, _, dependencies = _dependencies(privacy_status="FAIL")

    with pytest.raises(
        RuntimeError,
        match="Validação LGPD/governança falhou na camada publicada: privacy",
    ):
        run_publish_dashboard(**dependencies)  # type: ignore[arg-type]

    assert calls == [
        "load",
        "build",
        "contract",
        "policy",
        "validate",
        "save_privacy",
    ]


@pytest.mark.parametrize("failing_step", ["load", "build", "validate", "save_privacy"])
def test_pipeline_propagates_dependency_errors(failing_step: str) -> None:
    calls, _, dependencies = _dependencies()

    def fail(*args: object, **kwargs: object) -> None:
        raise LookupError(failing_step)

    key = {
        "load": "load_internal_fact_fn",
        "build": "build_published_fn",
        "validate": "validate_privacy_fn",
        "save_privacy": "save_privacy_results_fn",
    }[failing_step]
    dependencies[key] = fail

    with pytest.raises(LookupError, match=failing_step):
        run_publish_dashboard(**dependencies)  # type: ignore[arg-type]

    assert "save_report" not in calls
