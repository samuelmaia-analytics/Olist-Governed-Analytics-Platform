from __future__ import annotations

from src.publication_evidence import build_publication_evidence
from src.publication_provenance.models import (
    EvidenceProvenance,
    EvidenceSource,
    ProvenancedPublicationEvidence,
)
from src.publication_provenance.validation import validate_evidence_provenance

REQUIRED = frozenset(
    {
        EvidenceSource.OPERATIONAL_QUALITY,
        EvidenceSource.SCHEMA_CONTRACTS,
        EvidenceSource.PRIVACY,
    }
)


def envelope(
    provenance: dict[EvidenceSource, EvidenceProvenance],
) -> ProvenancedPublicationEvidence:
    return ProvenancedPublicationEvidence(
        build_publication_evidence(), "run-current", provenance
    )


def current(source: EvidenceSource) -> EvidenceProvenance:
    return EvidenceProvenance(source, "run-current")


def test_all_required_sources_from_current_run_are_valid() -> None:
    result = validate_evidence_provenance(
        envelope({source: current(source) for source in REQUIRED}), REQUIRED
    )

    assert result.valid is True
    assert result.current_sources == (
        EvidenceSource.OPERATIONAL_QUALITY,
        EvidenceSource.SCHEMA_CONTRACTS,
        EvidenceSource.PRIVACY,
    )
    assert result.reasons == ()


def test_missing_foreign_and_unknown_are_distinct_and_deterministic() -> None:
    result = validate_evidence_provenance(
        envelope(
            {
                EvidenceSource.SCHEMA_CONTRACTS: EvidenceProvenance(
                    EvidenceSource.SCHEMA_CONTRACTS, "run-foreign"
                ),
                EvidenceSource.PRIVACY: EvidenceProvenance(
                    EvidenceSource.PRIVACY, None
                ),
            }
        ),
        REQUIRED,
    )

    assert result.valid is False
    assert result.missing_sources == (EvidenceSource.OPERATIONAL_QUALITY,)
    assert result.foreign_run_sources == (EvidenceSource.SCHEMA_CONTRACTS,)
    assert result.unknown_sources == (EvidenceSource.PRIVACY,)
    assert result.reasons == (
        "operational_quality: missing",
        "schema_contracts: foreign run_id 'run-foreign' (current 'run-current')",
        "privacy: unknown run_id",
    )


def test_missing_non_required_source_does_not_invalidate_result() -> None:
    required = frozenset({EvidenceSource.MONITORING})
    result = validate_evidence_provenance(
        envelope({EvidenceSource.MONITORING: current(EvidenceSource.MONITORING)}),
        required,
    )

    assert result.valid is True
    assert result.missing_sources == ()
