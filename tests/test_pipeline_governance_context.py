from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.monitoring_components.models import MonitoringCheckResult
from src.publication_provenance import EvidenceSource, PipelineGovernanceContext
from src.quality_components.models import QualityCheckResult


@pytest.mark.parametrize(
    "module_name",
    [
        "src.publication_provenance",
        "src.publication_provenance.context",
        "src.publication_evidence",
    ],
)
def test_minimal_import_keeps_diagnostic_exports_lazy(module_name: str) -> None:
    # A fresh interpreter avoids modules already loaded during pytest collection.
    code = """
import importlib
import sys

importlib.import_module(sys.argv[1])
for name in (
    'src.publication_provenance.content',
    'src.publication_provenance.content_telemetry',
    'src.publication_shadow',
    'src.run_platform_pipeline',
    'scripts.run_governance_pipeline',
):
    assert not any(key == name or key.startswith(name + '.') for key in sys.modules), name

import src.publication_provenance as provenance
from src.publication_provenance import fingerprint_dataframe_schema
assert 'src.publication_provenance.content' in sys.modules
assert 'src.publication_provenance.content_telemetry' not in sys.modules
assert fingerprint_dataframe_schema is provenance.fingerprint_dataframe_schema

from src.publication_provenance import serialize_dataset_content_provenance
assert 'src.publication_provenance.content_telemetry' in sys.modules
assert serialize_dataset_content_provenance is provenance.serialize_dataset_content_provenance
for name in provenance.__all__:
    assert getattr(provenance, name) is not None
try:
    provenance.nonexistent_export
except AttributeError:
    pass
else:
    raise AssertionError('Unknown exports must raise AttributeError')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, module_name],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_context_registers_current_results_incrementally_without_io() -> None:
    context = PipelineGovernanceContext("run-x")
    produced_at = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    quality = [QualityCheckResult("quality", "PASS", 0, 0, "high", "ok")]
    monitoring = [
        MonitoringCheckResult(
            "published_file_freshness_hours", "PASS", 1, 36, "high", "ok"
        )
    ]

    context.record_quality(quality, produced_at=produced_at)
    assert EvidenceSource.SCHEMA_CONTRACTS not in context.provenance
    context.record_monitoring(monitoring, produced_at=produced_at)

    assert context.quality_results == tuple(quality)
    assert context.monitoring_results == tuple(monitoring)
    assert all(item.run_id == "run-x" for item in context.provenance.values())
    assert context.provenance[EvidenceSource.OPERATIONAL_QUALITY].produced_at == produced_at


def test_context_copies_classification_and_builds_isolated_envelope() -> None:
    context = PipelineGovernanceContext("run-x")
    classification = pd.DataFrame(
        {
            "lgpd_classification": ["sensitive_personal_data"],
            "recommended_action": ["remove"],
        }
    )
    context.record_classification(classification)
    classification.loc[0, "recommended_action"] = "keep"

    envelope = context.build_provenanced_evidence()

    assert envelope.current_run_id == "run-x"
    assert envelope.evidence.sensitive_data_protected is True
    assert EvidenceSource.CLASSIFICATION in envelope.provenance


def test_context_instances_do_not_share_results_or_provenance() -> None:
    first = PipelineGovernanceContext("run-a")
    second = PipelineGovernanceContext("run-b")
    first.record_monitoring([])

    assert second.monitoring_results is None
    assert second.provenance == {}
