from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.publication_provenance.content import DatasetContentProvenance
from src.publication_provenance.content_telemetry import (
    DATASET_CONTENT_PROVENANCE_SCHEMA_VERSION,
    append_dataset_content_provenance,
    load_dataset_content_provenance,
    serialize_dataset_content_provenance,
)

TIMESTAMP = datetime(2026, 8, 15, 3, 0, tzinfo=UTC)


def _provenance(run_id: str = "run-a") -> DatasetContentProvenance:
    return DatasetContentProvenance(
        run_id=run_id,
        source_row_count=2,
        source_column_count=6,
        published_row_count=2,
        published_column_count=4,
        source_schema_fingerprint="a" * 64,
        published_schema_fingerprint="b" * 64,
        source_content_fingerprint="c" * 64,
        published_content_fingerprint="d" * 64,
    )


def test_serialization_contains_version_timestamp_counts_and_fingerprints() -> None:
    record = serialize_dataset_content_provenance(
        _provenance(),
        timestamp_utc=TIMESTAMP,
    )

    assert record == {
        "schema_version": DATASET_CONTENT_PROVENANCE_SCHEMA_VERSION,
        "run_id": "run-a",
        "timestamp_utc": "2026-08-15T03:00:00+00:00",
        "source_row_count": 2,
        "source_column_count": 6,
        "published_row_count": 2,
        "published_column_count": 4,
        "source_schema_fingerprint": "a" * 64,
        "published_schema_fingerprint": "b" * 64,
        "source_content_fingerprint": "c" * 64,
        "published_content_fingerprint": "d" * 64,
    }


def test_serialization_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        serialize_dataset_content_provenance(
            _provenance(),
            timestamp_utc=datetime(2026, 8, 15, 3, 0),
        )


def test_append_keeps_two_utf8_runs_and_reader_restores_comparable_models(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "monitoring" / "content.jsonl"
    first = _provenance("execução-á")
    second = _provenance("run-b")

    append_dataset_content_provenance(
        first,
        timestamp_utc=TIMESTAMP,
        output_path=output_path,
    )
    append_dataset_content_provenance(
        second,
        timestamp_utc=TIMESTAMP,
        output_path=output_path,
    )

    raw = output_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in raw.splitlines()]
    assert "execução-á" in raw
    assert len(records) == 2
    assert [record["run_id"] for record in records] == ["execução-á", "run-b"]
    assert load_dataset_content_provenance(output_path) == (first, second)


def test_append_reports_invalid_output_path(tmp_path: Path) -> None:
    output_path = tmp_path / "content.jsonl"
    output_path.mkdir()

    with pytest.raises(OSError):
        append_dataset_content_provenance(
            _provenance(),
            timestamp_utc=TIMESTAMP,
            output_path=output_path,
        )
