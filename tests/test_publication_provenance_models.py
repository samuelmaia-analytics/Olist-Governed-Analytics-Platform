from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from src.publication_evidence import build_publication_evidence
from src.publication_provenance.models import (
    EvidenceProvenance,
    EvidenceSource,
    ProvenancedPublicationEvidence,
    ProvenanceState,
    ProvenanceValidationResult,
)


def test_source_and_state_are_closed_string_enums() -> None:
    assert [source.value for source in EvidenceSource] == [
        "operational_quality",
        "schema_contracts",
        "business_rules",
        "privacy",
        "monitoring",
        "observability",
        "classification",
    ]
    assert [state.value for state in ProvenanceState] == [
        "current",
        "missing",
        "foreign_run",
        "unknown",
    ]


def test_evidence_provenance_is_frozen_equal_and_requires_aware_timestamp() -> None:
    produced_at = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    provenance = EvidenceProvenance(
        EvidenceSource.PRIVACY,
        "run-x",
        produced_at,
        "publish",
        "fact_orders_dashboard",
    )

    assert provenance == replace(provenance)
    with pytest.raises(FrozenInstanceError):
        provenance.run_id = "run-y"  # type: ignore[misc]
    with pytest.raises(ValueError, match="timezone-aware"):
        EvidenceProvenance(
            EvidenceSource.PRIVACY,
            "run-x",
            datetime(2026, 8, 13, 12, 0),
        )


def test_envelope_is_frozen_and_copies_provenance_mapping() -> None:
    evidence = build_publication_evidence()
    source_mapping = {
        EvidenceSource.MONITORING: EvidenceProvenance(
            EvidenceSource.MONITORING, "run-x"
        )
    }
    envelope = ProvenancedPublicationEvidence(evidence, "run-x", source_mapping)
    source_mapping.clear()

    assert tuple(envelope.provenance) == (EvidenceSource.MONITORING,)
    with pytest.raises(TypeError):
        envelope.provenance[EvidenceSource.PRIVACY] = EvidenceProvenance(  # type: ignore[index]
            EvidenceSource.PRIVACY, "run-x"
        )
    with pytest.raises(FrozenInstanceError):
        envelope.current_run_id = "run-y"  # type: ignore[misc]


def test_validation_result_is_frozen_and_has_deterministic_tuple_fields() -> None:
    result = ProvenanceValidationResult(
        False,
        "run-x",
        (EvidenceSource.MONITORING,),
        (EvidenceSource.PRIVACY,),
        (),
        (),
        ("privacy: missing",),
    )

    assert result.current_sources == (EvidenceSource.MONITORING,)
    assert result.reasons == ("privacy: missing",)
    with pytest.raises(FrozenInstanceError):
        result.valid = True  # type: ignore[misc]
