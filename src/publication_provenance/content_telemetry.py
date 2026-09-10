from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import PUBLISHED_MONITORING_DIR
from src.publication_provenance.content import DatasetContentProvenance

DATASET_CONTENT_PROVENANCE_SCHEMA_VERSION = "v1"
DEFAULT_DATASET_CONTENT_PROVENANCE_PATH = (
    PUBLISHED_MONITORING_DIR / "dataset_content_provenance.jsonl"
)


def serialize_dataset_content_provenance(
    provenance: DatasetContentProvenance,
    *,
    timestamp_utc: datetime,
) -> dict[str, Any]:
    if timestamp_utc.utcoffset() is None:
        raise ValueError("timestamp_utc must be timezone-aware")
    return {
        "schema_version": DATASET_CONTENT_PROVENANCE_SCHEMA_VERSION,
        "run_id": provenance.run_id,
        "timestamp_utc": timestamp_utc.isoformat(),
        "source_row_count": provenance.source_row_count,
        "source_column_count": provenance.source_column_count,
        "published_row_count": provenance.published_row_count,
        "published_column_count": provenance.published_column_count,
        "source_schema_fingerprint": provenance.source_schema_fingerprint,
        "published_schema_fingerprint": provenance.published_schema_fingerprint,
        "source_content_fingerprint": provenance.source_content_fingerprint,
        "published_content_fingerprint": provenance.published_content_fingerprint,
    }


def append_dataset_content_provenance(
    provenance: DatasetContentProvenance,
    *,
    timestamp_utc: datetime,
    output_path: Path,
) -> Path:
    record = serialize_dataset_content_provenance(
        provenance,
        timestamp_utc=timestamp_utc,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return output_path


def load_dataset_content_provenance(
    input_path: Path,
) -> tuple[DatasetContentProvenance, ...]:
    if not input_path.exists():
        return ()

    provenances: list[DatasetContentProvenance] = []
    with input_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            schema_version = record.get("schema_version")
            if schema_version != DATASET_CONTENT_PROVENANCE_SCHEMA_VERSION:
                raise ValueError(
                    "unsupported dataset content provenance schema_version "
                    f"at line {line_number}: {schema_version!r}"
                )
            provenances.append(
                DatasetContentProvenance(
                    run_id=str(record["run_id"]),
                    source_row_count=int(record["source_row_count"]),
                    source_column_count=int(record["source_column_count"]),
                    published_row_count=int(record["published_row_count"]),
                    published_column_count=int(record["published_column_count"]),
                    source_schema_fingerprint=str(
                        record["source_schema_fingerprint"]
                    ),
                    published_schema_fingerprint=str(
                        record["published_schema_fingerprint"]
                    ),
                    source_content_fingerprint=str(
                        record["source_content_fingerprint"]
                    ),
                    published_content_fingerprint=str(
                        record["published_content_fingerprint"]
                    ),
                )
            )
    return tuple(provenances)
