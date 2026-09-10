from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

import src.quality as quality
import src.run_platform_pipeline as pipeline
from src.publication_provenance import EvidenceSource, PipelineGovernanceContext
from src.quality_components.models import QualityCheckResult


def test_pipeline_reuses_metadata_run_id_for_in_memory_context(monkeypatch: pytest.MonkeyPatch) -> None:
    started_at = datetime(2026, 8, 13, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(pipeline, "resolve_git_commit", lambda: "abc123")
    context = PipelineGovernanceContext(pipeline.build_pipeline_run_id(started_at))

    metadata = pipeline.build_run_metadata(
        started_at, datetime(2026, 8, 13, 12, 31, tzinfo=UTC)
    )

    assert context.run_id == metadata.run_id == "run-20260813T123000Z"


def test_quality_step_captures_current_results_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame({"order_id": ["current-order"]})
    results = [QualityCheckResult("current", "PASS", 1, 1, "high", "ok")]
    saved: list[object] = []
    monkeypatch.setattr(pipeline, "load_fact_table", lambda: frame)
    monkeypatch.setattr(pipeline, "run_quality_checks", lambda _frame: results)
    monkeypatch.setattr(pipeline, "save_quality_results", saved.append)
    monkeypatch.setattr(
        pipeline, "save_quality_report", lambda _frame, _results: None
    )
    context = PipelineGovernanceContext("run-current")

    with pipeline.activate_pipeline_governance_context(context):
        pipeline.execute_step("quality")

    assert quality.QualityCheckResult is QualityCheckResult
    assert context.quality_results == tuple(results)
    assert context.quality_results[0] is results[0]
    assert saved == [results]
    provenance = context.provenance[EvidenceSource.OPERATIONAL_QUALITY]
    assert provenance.run_id == "run-current"
    assert provenance.execution_step == "quality"
    assert provenance.produced_at is not None
    assert provenance.dataset_name == "fact_orders_enriched"


def test_context_activation_restores_previous_context_after_failure() -> None:
    previous = pipeline._ACTIVE_GOVERNANCE_CONTEXT.get()
    outer = PipelineGovernanceContext("run-outer")
    inner = PipelineGovernanceContext("run-inner")

    with pipeline.activate_pipeline_governance_context(outer):
        with pytest.raises(RuntimeError, match="step failed"):
            with pipeline.activate_pipeline_governance_context(inner):
                assert pipeline._ACTIVE_GOVERNANCE_CONTEXT.get() is inner
                raise RuntimeError("step failed")
        assert pipeline._ACTIVE_GOVERNANCE_CONTEXT.get() is outer

    assert pipeline._ACTIVE_GOVERNANCE_CONTEXT.get() is previous
