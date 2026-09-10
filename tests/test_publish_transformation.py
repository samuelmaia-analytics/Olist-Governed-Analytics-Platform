from __future__ import annotations

from typing import Protocol, cast

import pandas as pd

from src.publish_components import transformation
from src.publish_dashboard import PSEUDONYMIZED_COLUMNS, PUBLISHED_COLUMNS


class _StringRowSelection(Protocol):
    def __getitem__(self, key: tuple[int, list[str]]) -> pd.Series[str]: ...


def _source_frame() -> pd.DataFrame:
    values: dict[str, list[int | str | None]] = {
        column: [1]
        for column in PUBLISHED_COLUMNS
        if column not in {"seller_key"}
    }
    values.update(
        {
            "order_id": ["order-1"],
            "customer_unique_id": ["customer-1"],
            "seller_id": ["seller-1"],
            "customer_id": ["raw-customer"],
            "customer_city": ["city"],
            "order_status": [None],
            "payment_type_mode": [None],
            "seller_volume_tier": [None],
            "customer_state": [None],
            "seller_state": [None],
        }
    )
    return pd.DataFrame(values)


def test_pseudonymize_is_deterministic_and_preserves_na() -> None:
    assert transformation.pseudonymize("abc", "order_id") == (
        "order_id_6fb07f174b0fea0e"
    )
    assert transformation.pseudonymize(pd.NA, "order_id") is pd.NA


def test_build_published_table_preserves_schema_defaults_and_minimization() -> None:
    published = transformation.build_published_dashboard_table(
        _source_frame(),
        pseudonymized_columns=PSEUDONYMIZED_COLUMNS,
        published_columns=PUBLISHED_COLUMNS,
    )

    assert published.shape == (1, 34)
    assert list(published.columns) == PUBLISHED_COLUMNS
    assert cast(str, published.at[0, "order_id"]).startswith("order_id_")
    assert cast(str, published.at[0, "customer_unique_id"]).startswith("customer_unique_id_")
    assert cast(str, published.at[0, "seller_key"]).startswith("seller_id_")
    assert {"customer_id", "customer_city", "seller_id"}.isdisjoint(
        published.columns
    )
    string_rows = cast(_StringRowSelection, published.loc)
    assert string_rows[0, ["customer_state", "seller_state"]].tolist() == [
        "NA",
        "NA",
    ]
    assert string_rows[0, ["order_status", "payment_type_mode"]].tolist() == [
        "unknown",
        "unknown",
    ]
    assert published.at[0, "seller_volume_tier"] == "long_tail"


def test_load_domain_policy_preserves_missing_domain_error() -> None:
    try:
        transformation.load_domain_policy({})
    except ValueError as error:
        assert str(error) == "Contrato de privacidade sem `policy_domain`."
    else:
        raise AssertionError("Expected missing policy domain to raise ValueError")
