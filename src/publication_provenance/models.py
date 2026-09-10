from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from src.publication_evidence.models import PublicationEvidence


class EvidenceSource(StrEnum):
    OPERATIONAL_QUALITY = "operational_quality"
    SCHEMA_CONTRACTS = "schema_contracts"
    BUSINESS_RULES = "business_rules"
    PRIVACY = "privacy"
    MONITORING = "monitoring"
    OBSERVABILITY = "observability"
    CLASSIFICATION = "classification"


class ProvenanceState(StrEnum):
    CURRENT = "current"
    MISSING = "missing"
    FOREIGN_RUN = "foreign_run"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvidenceProvenance:
    source: EvidenceSource
    run_id: str | None
    produced_at: datetime | None = None
    execution_step: str | None = None
    dataset_name: str | None = None

    def __post_init__(self) -> None:
        if self.produced_at is not None and self.produced_at.utcoffset() is None:
            raise ValueError("produced_at must be timezone-aware")


@dataclass(frozen=True)
class ProvenancedPublicationEvidence:
    evidence: PublicationEvidence
    current_run_id: str
    provenance: Mapping[EvidenceSource, EvidenceProvenance]

    def __post_init__(self) -> None:
        if not self.current_run_id:
            raise ValueError("current_run_id must not be empty")
        copied = {
            source: self.provenance[source]
            for source in EvidenceSource
            if source in self.provenance
        }
        object.__setattr__(self, "provenance", MappingProxyType(copied))


@dataclass(frozen=True)
class ProvenanceValidationResult:
    valid: bool
    current_run_id: str
    current_sources: tuple[EvidenceSource, ...]
    missing_sources: tuple[EvidenceSource, ...]
    foreign_run_sources: tuple[EvidenceSource, ...]
    unknown_sources: tuple[EvidenceSource, ...]
    reasons: tuple[str, ...]
