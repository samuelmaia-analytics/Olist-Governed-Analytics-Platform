from importlib import import_module
from typing import TYPE_CHECKING

from src.publication_provenance.context import PipelineGovernanceContext
from src.publication_provenance.models import (
    EvidenceProvenance,
    EvidenceSource,
    ProvenancedPublicationEvidence,
    ProvenanceState,
    ProvenanceValidationResult,
)
from src.publication_provenance.validation import (
    SHADOW_REQUIRED_SOURCES,
    validate_evidence_provenance,
)

__all__ = [
    "DATASET_CONTENT_PROVENANCE_SCHEMA_VERSION",
    "DEFAULT_DATASET_CONTENT_PROVENANCE_PATH",
    "DatasetContentComparison",
    "DatasetContentProvenance",
    "EvidenceProvenance",
    "EvidenceSource",
    "PUBLISHED_CONTENT_KEY",
    "PipelineGovernanceContext",
    "ProvenancedPublicationEvidence",
    "ProvenanceState",
    "ProvenanceValidationResult",
    "SHADOW_REQUIRED_SOURCES",
    "SOURCE_CONTENT_KEY",
    "append_dataset_content_provenance",
    "build_dataset_content_provenance",
    "compare_dataset_content_provenance",
    "fingerprint_dataframe_content",
    "fingerprint_dataframe_schema",
    "load_dataset_content_provenance",
    "serialize_dataset_content_provenance",
    "validate_evidence_provenance",
]

if TYPE_CHECKING:
    from src.publication_provenance.content import (
        PUBLISHED_CONTENT_KEY,
        SOURCE_CONTENT_KEY,
        DatasetContentComparison,
        DatasetContentProvenance,
        build_dataset_content_provenance,
        compare_dataset_content_provenance,
        fingerprint_dataframe_content,
        fingerprint_dataframe_schema,
    )
    from src.publication_provenance.content_telemetry import (
        DATASET_CONTENT_PROVENANCE_SCHEMA_VERSION,
        DEFAULT_DATASET_CONTENT_PROVENANCE_PATH,
        append_dataset_content_provenance,
        load_dataset_content_provenance,
        serialize_dataset_content_provenance,
    )


_LAZY_MODULES = {
    "PUBLISHED_CONTENT_KEY": "src.publication_provenance.content",
    "SOURCE_CONTENT_KEY": "src.publication_provenance.content",
    "DatasetContentComparison": "src.publication_provenance.content",
    "DatasetContentProvenance": "src.publication_provenance.content",
    "build_dataset_content_provenance": "src.publication_provenance.content",
    "compare_dataset_content_provenance": "src.publication_provenance.content",
    "fingerprint_dataframe_content": "src.publication_provenance.content",
    "fingerprint_dataframe_schema": "src.publication_provenance.content",
    "DATASET_CONTENT_PROVENANCE_SCHEMA_VERSION": "src.publication_provenance.content_telemetry",
    "DEFAULT_DATASET_CONTENT_PROVENANCE_PATH": "src.publication_provenance.content_telemetry",
    "append_dataset_content_provenance": "src.publication_provenance.content_telemetry",
    "load_dataset_content_provenance": "src.publication_provenance.content_telemetry",
    "serialize_dataset_content_provenance": "src.publication_provenance.content_telemetry",
}


def __getattr__(name: str) -> object:
    module_name = _LAZY_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value: object = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
