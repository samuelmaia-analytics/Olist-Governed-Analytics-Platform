from __future__ import annotations

import pandas as pd
import pytest

from src.publication_provenance.content import (
    PUBLISHED_CONTENT_KEY,
    SOURCE_CONTENT_KEY,
    DatasetContentComparison,
    build_dataset_content_provenance,
    compare_dataset_content_provenance,
    fingerprint_dataframe_content,
    fingerprint_dataframe_schema,
)


def _source() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["o1", "o2"],
            "order_item_id": [1, 1],
            "product_id": ["p1", "p2"],
            "seller_id": ["s1", "s2"],
            "price": [10.0, 20.0],
            "note": [None, "ok"],
        }
    )


def _published() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["order_a", "order_b"],
            "order_item_id": [1, 1],
            "seller_key": ["seller_a", "seller_b"],
            "price": [10.0, 20.0],
        }
    )


def _provenance(
    run_id: str,
    *,
    source: pd.DataFrame | None = None,
    published: pd.DataFrame | None = None,
):
    return build_dataset_content_provenance(
        run_id=run_id,
        source=_source() if source is None else source,
        published=_published() if published is None else published,
    )


def test_equal_frames_in_distinct_instances_have_equal_fingerprints() -> None:
    first = _source()
    second = _source().copy(deep=True)

    assert fingerprint_dataframe_schema(first) == fingerprint_dataframe_schema(second)
    assert fingerprint_dataframe_content(
        first, stable_key=SOURCE_CONTENT_KEY
    ) == fingerprint_dataframe_content(second, stable_key=SOURCE_CONTENT_KEY)


def test_row_order_does_not_change_content_fingerprint() -> None:
    original = _source()
    reordered = original.iloc[::-1].reset_index(drop=True)

    assert fingerprint_dataframe_content(
        original, stable_key=SOURCE_CONTENT_KEY
    ) == fingerprint_dataframe_content(reordered, stable_key=SOURCE_CONTENT_KEY)


def test_changed_cell_changes_content_fingerprint() -> None:
    original = _source()
    changed = original.copy()
    changed.loc[0, "price"] = 11.0

    assert fingerprint_dataframe_content(
        original, stable_key=SOURCE_CONTENT_KEY
    ) != fingerprint_dataframe_content(changed, stable_key=SOURCE_CONTENT_KEY)


def test_added_column_changes_schema_and_content_fingerprints() -> None:
    original = _source()
    changed = original.assign(new_column="value")

    assert fingerprint_dataframe_schema(original) != fingerprint_dataframe_schema(changed)
    assert fingerprint_dataframe_content(
        original, stable_key=SOURCE_CONTENT_KEY
    ) != fingerprint_dataframe_content(changed, stable_key=SOURCE_CONTENT_KEY)


def test_changed_type_changes_schema_and_content_fingerprints() -> None:
    original = _source()
    changed = original.copy()
    changed["price"] = changed["price"].astype("string")

    assert fingerprint_dataframe_schema(original) != fingerprint_dataframe_schema(changed)
    assert fingerprint_dataframe_content(
        original, stable_key=SOURCE_CONTENT_KEY
    ) != fingerprint_dataframe_content(changed, stable_key=SOURCE_CONTENT_KEY)


@pytest.mark.parametrize(
    ("source_changed", "published_changed", "expected"),
    [
        (False, False, DatasetContentComparison.SAME_CONTENT),
        (True, False, DatasetContentComparison.SOURCE_CHANGED),
        (False, True, DatasetContentComparison.PUBLISHED_CHANGED),
        (True, True, DatasetContentComparison.BOTH_CHANGED),
    ],
)
def test_comparison_classifies_source_and_published_changes(
    source_changed: bool,
    published_changed: bool,
    expected: DatasetContentComparison,
) -> None:
    source = _source()
    published = _published()
    first = _provenance("run-a", source=source, published=published)
    changed_source = source.copy()
    changed_published = published.copy()
    if source_changed:
        changed_source.loc[0, "price"] = 11.0
    if published_changed:
        changed_published.loc[0, "price"] = 11.0
    second = _provenance(
        "run-b",
        source=changed_source,
        published=changed_published,
    )

    assert compare_dataset_content_provenance(first, second) is expected


def test_comparison_is_unavailable_without_both_run_snapshots() -> None:
    assert (
        compare_dataset_content_provenance(_provenance("run-a"), None)
        is DatasetContentComparison.UNAVAILABLE
    )


def test_published_key_matches_the_characterized_published_grain() -> None:
    assert SOURCE_CONTENT_KEY == (
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
    )
    assert PUBLISHED_CONTENT_KEY == ("order_id", "order_item_id")


def test_duplicate_stable_key_is_rejected_instead_of_masked() -> None:
    duplicate = pd.concat([_source().iloc[[0]], _source().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="stable key contains duplicate values"):
        fingerprint_dataframe_content(duplicate, stable_key=SOURCE_CONTENT_KEY)
