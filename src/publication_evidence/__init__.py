"""Typed, side-effect-free publication evidence normalization."""

from src.publication_evidence.adapters import build_publication_evidence
from src.publication_evidence.models import EvidenceStatus, PublicationEvidence
from src.publication_evidence.privacy_inputs import (
    CurrentPrivacyInputs,
    SensitiveDataProtectionResult,
    build_current_privacy_inputs,
    calculate_current_privacy_risk,
    evaluate_sensitive_data_protection,
)

__all__ = [
    "CurrentPrivacyInputs",
    "EvidenceStatus",
    "PublicationEvidence",
    "SensitiveDataProtectionResult",
    "build_current_privacy_inputs",
    "build_publication_evidence",
    "calculate_current_privacy_risk",
    "evaluate_sensitive_data_protection",
]
