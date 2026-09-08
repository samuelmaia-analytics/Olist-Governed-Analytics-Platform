from __future__ import annotations

from collections.abc import Iterable

from src.publication_provenance.models import (
    EvidenceSource,
    ProvenancedPublicationEvidence,
    ProvenanceValidationResult,
)

SHADOW_REQUIRED_SOURCES = frozenset(
    {
        EvidenceSource.OPERATIONAL_QUALITY,
        EvidenceSource.SCHEMA_CONTRACTS,
        EvidenceSource.PRIVACY,
        EvidenceSource.CLASSIFICATION,
        EvidenceSource.MONITORING,
    }
)


def validate_evidence_provenance(
    envelope: ProvenancedPublicationEvidence,
    required_sources: Iterable[EvidenceSource],
) -> ProvenanceValidationResult:
    required = set(required_sources)
    current: list[EvidenceSource] = []
    missing: list[EvidenceSource] = []
    foreign: list[EvidenceSource] = []
    unknown: list[EvidenceSource] = []
    reasons: list[str] = []

    for source in EvidenceSource:
        if source not in required:
            continue
        provenance = envelope.provenance.get(source)
        if provenance is None:
            missing.append(source)
            reasons.append(f"{source.value}: missing")
        elif provenance.run_id is None:
            unknown.append(source)
            reasons.append(f"{source.value}: unknown run_id")
        elif provenance.run_id != envelope.current_run_id:
            foreign.append(source)
            reasons.append(
                f"{source.value}: foreign run_id {provenance.run_id!r} "
                f"(current {envelope.current_run_id!r})"
            )
        else:
            current.append(source)

    return ProvenanceValidationResult(
        valid=not (missing or foreign or unknown),
        current_run_id=envelope.current_run_id,
        current_sources=tuple(current),
        missing_sources=tuple(missing),
        foreign_run_sources=tuple(foreign),
        unknown_sources=tuple(unknown),
        reasons=tuple(reasons),
    )
