from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import pandas as pd
from pandas.api import types as pandas_types

if TYPE_CHECKING:
    import numpy as np
    from pandas.api.extensions import ExtensionDtype

SOURCE_CONTENT_KEY: Final[tuple[str, ...]] = (
    "order_id",
    "order_item_id",
    "product_id",
    "seller_id",
)
PUBLISHED_CONTENT_KEY: Final[tuple[str, ...]] = ("order_id", "order_item_id")

_CONTENT_FINGERPRINT_VERSION: Final[bytes] = b"dataset-content-v1\0"
_NULL_HASH: Final[int] = 0


class DatasetContentComparison(StrEnum):
    SAME_CONTENT = "same_content"
    SOURCE_CHANGED = "source_changed"
    PUBLISHED_CHANGED = "published_changed"
    BOTH_CHANGED = "both_changed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DatasetContentProvenance:
    run_id: str
    source_row_count: int
    source_column_count: int
    published_row_count: int
    published_column_count: int
    source_schema_fingerprint: str
    published_schema_fingerprint: str
    source_content_fingerprint: str
    published_content_fingerprint: str

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must not be empty")


def _normalized_dtype(dtype: np.dtype[np.generic] | ExtensionDtype) -> str:
    if isinstance(dtype, pd.DatetimeTZDtype):
        return f"datetime64[ns,{dtype.tz}]"
    if pandas_types.is_datetime64_any_dtype(dtype):
        return "datetime64[ns]"
    if pandas_types.is_timedelta64_dtype(dtype):
        return "timedelta64[ns]"
    if pandas_types.is_bool_dtype(dtype):
        return "boolean"
    if pandas_types.is_integer_dtype(dtype):
        return "integer"
    if pandas_types.is_float_dtype(dtype):
        return "floating"
    if pandas_types.is_complex_dtype(dtype):
        return "complex"
    if isinstance(dtype, pd.StringDtype):
        return "string"
    if isinstance(dtype, pd.CategoricalDtype):
        return f"category[ordered={str(dtype.ordered).lower()}]"
    if pandas_types.is_object_dtype(dtype):
        return "object"
    return str(dtype).strip().lower()


def _validated_columns(frame: pd.DataFrame) -> tuple[str, ...]:
    if not frame.columns.is_unique:
        raise ValueError("dataset columns must be unique")
    if not all(isinstance(column, str) for column in frame.columns):
        raise ValueError("dataset column names must be strings")
    return tuple(frame.columns)


def fingerprint_dataframe_schema(frame: pd.DataFrame) -> str:
    columns = _validated_columns(frame)
    schema = [
        {"name": column, "type": _normalized_dtype(frame[column].dtype)}
        for column in columns
    ]
    payload = json.dumps(
        schema,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_row_positions(
    frame: pd.DataFrame,
    *,
    stable_key: tuple[str, ...],
) -> pd.Index:
    missing = [column for column in stable_key if column not in frame.columns]
    if missing:
        raise ValueError(f"stable key columns missing: {missing}")
    if bool(frame.loc[:, list(stable_key)].isna().any(axis=None)):
        raise ValueError(f"stable key contains null values: {list(stable_key)}")
    if bool(frame.duplicated(subset=list(stable_key), keep=False).any()):
        raise ValueError(f"stable key contains duplicate values: {list(stable_key)}")

    key_values = frame.loc[:, list(stable_key)].reset_index(drop=True)
    return key_values.sort_values(
        list(stable_key),
        kind="mergesort",
        na_position="first",
    ).index


def fingerprint_dataframe_content(
    frame: pd.DataFrame,
    *,
    stable_key: tuple[str, ...],
) -> str:
    columns = _validated_columns(frame)
    schema_fingerprint = fingerprint_dataframe_schema(frame)
    row_positions = _canonical_row_positions(frame, stable_key=stable_key)

    digest = hashlib.sha256()
    digest.update(_CONTENT_FINGERPRINT_VERSION)
    digest.update(schema_fingerprint.encode("ascii"))
    digest.update(len(frame).to_bytes(8, byteorder="big", signed=False))

    for position, column in enumerate(columns):
        column_name = column.encode("utf-8")
        digest.update(len(column_name).to_bytes(4, byteorder="big", signed=False))
        digest.update(column_name)
        ordered = frame.iloc[row_positions, position]
        null_mask = ordered.isna().to_numpy()
        value_hashes = pd.util.hash_pandas_object(
            ordered,
            index=False,
            categorize=True,
        ).to_numpy(dtype="uint64", copy=True)
        value_hashes[null_mask] = _NULL_HASH
        digest.update(value_hashes.astype("<u8", copy=False).tobytes())

    return digest.hexdigest()


def build_dataset_content_provenance(
    *,
    run_id: str,
    source: pd.DataFrame,
    published: pd.DataFrame,
) -> DatasetContentProvenance:
    return DatasetContentProvenance(
        run_id=run_id,
        source_row_count=len(source),
        source_column_count=len(source.columns),
        published_row_count=len(published),
        published_column_count=len(published.columns),
        source_schema_fingerprint=fingerprint_dataframe_schema(source),
        published_schema_fingerprint=fingerprint_dataframe_schema(published),
        source_content_fingerprint=fingerprint_dataframe_content(
            source,
            stable_key=SOURCE_CONTENT_KEY,
        ),
        published_content_fingerprint=fingerprint_dataframe_content(
            published,
            stable_key=PUBLISHED_CONTENT_KEY,
        ),
    )


def _source_changed(
    first: DatasetContentProvenance,
    second: DatasetContentProvenance,
) -> bool:
    return (
        first.source_row_count != second.source_row_count
        or first.source_column_count != second.source_column_count
        or first.source_schema_fingerprint != second.source_schema_fingerprint
        or first.source_content_fingerprint != second.source_content_fingerprint
    )


def _published_changed(
    first: DatasetContentProvenance,
    second: DatasetContentProvenance,
) -> bool:
    return (
        first.published_row_count != second.published_row_count
        or first.published_column_count != second.published_column_count
        or first.published_schema_fingerprint != second.published_schema_fingerprint
        or first.published_content_fingerprint != second.published_content_fingerprint
    )


def compare_dataset_content_provenance(
    first: DatasetContentProvenance | None,
    second: DatasetContentProvenance | None,
) -> DatasetContentComparison:
    if first is None or second is None:
        return DatasetContentComparison.UNAVAILABLE

    source_changed = _source_changed(first, second)
    published_changed = _published_changed(first, second)
    if source_changed and published_changed:
        return DatasetContentComparison.BOTH_CHANGED
    if source_changed:
        return DatasetContentComparison.SOURCE_CHANGED
    if published_changed:
        return DatasetContentComparison.PUBLISHED_CHANGED
    return DatasetContentComparison.SAME_CONTENT
