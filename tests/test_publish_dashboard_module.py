from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import src.publish_dashboard as publish_dashboard


def build_source_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["order-1"],
            "order_item_id": [1],
            "customer_id": ["cust-1"],
            "customer_unique_id": ["uniq-1"],
            "product_id": ["product-1"],
            "seller_id": ["seller-1"],
            "order_status": [None],
            "order_purchase_timestamp": [pd.Timestamp("2018-01-01")],
            "order_delivered_customer_date": [pd.Timestamp("2018-01-05")],
            "order_estimated_delivery_date": [pd.Timestamp("2018-01-04")],
            "order_date": [pd.Timestamp("2018-01-01").date()],
            "order_year": [2018],
            "order_month": [1],
            "purchase_cohort_month": ["2018-01"],
            "cohort_order_month_number": [0],
            "customer_order_sequence": [1],
            "is_first_order": [True],
            "seller_volume_tier": [None],
            "seller_order_count": [10],
            "seller_avg_delivery_days": [4.0],
            "seller_delay_rate": [0.1],
            "delivery_time_days": [4.0],
            "seller_dispatch_time_days": [1.0],
            "carrier_delivery_time_days": [3.0],
            "estimated_delay_days": [1.0],
            "is_delayed": [True],
            "price": [100.0],
            "freight_value": [10.0],
            "freight_to_price_ratio": [0.1],
            "total_item_value": [110.0],
            "payment_type_mode": [None],
            "review_score_mean": [4.5],
            "product_category_name": ["cat_a"],
            "product_category_name_english": ["cat a"],
            "customer_state": [None],
            "seller_state": [None],
        }
    )


def test_pseudonymize_returns_stable_prefix_and_preserves_na() -> None:
    pseudonymized = publish_dashboard.pseudonymize("abc", "order_id")

    assert isinstance(pseudonymized, str)
    assert pseudonymized.startswith("order_id_")
    assert publish_dashboard.pseudonymize(pd.NA, "order_id") is pd.NA


def test_build_published_dashboard_table_applies_defaults() -> None:
    published = publish_dashboard.build_published_dashboard_table(build_source_df())

    assert published.loc[0, "customer_state"] == "NA"
    assert published.loc[0, "seller_state"] == "NA"
    assert published.loc[0, "order_status"] == "unknown"
    assert published.loc[0, "payment_type_mode"] == "unknown"
    assert published.loc[0, "seller_volume_tier"] == "long_tail"
    assert str(published.loc[0, "seller_key"]).startswith("seller_id_")


def test_validate_privacy_controls_passes_for_compliant_published_table() -> None:
    source_df = build_source_df()
    published = publish_dashboard.build_published_dashboard_table(source_df)
    contract = publish_dashboard.load_privacy_contract()
    policy = publish_dashboard.load_domain_policy(contract)

    checks = publish_dashboard.validate_privacy_controls(
        published, contract, policy, source_df=source_df
    )

    assert checks
    assert all(check.status == "PASS" for check in checks)


def test_validate_privacy_controls_detects_forbidden_column_exposure() -> None:
    source_df = build_source_df()
    published = publish_dashboard.build_published_dashboard_table(source_df)
    published["customer_city"] = "sao paulo"
    contract = publish_dashboard.load_privacy_contract()
    policy = publish_dashboard.load_domain_policy(contract)

    checks = publish_dashboard.validate_privacy_controls(
        published, contract, policy, source_df=source_df
    )

    failed = {check.check_name for check in checks if check.status == "FAIL"}
    assert "forbidden_columns_absent" in failed
    assert "classification_leakage" in failed


def test_validate_privacy_controls_detects_wrong_default_for_source_nulls() -> None:
    source_df = build_source_df()
    published = publish_dashboard.build_published_dashboard_table(source_df)
    published["order_status"] = "invalid_default"
    contract = publish_dashboard.load_privacy_contract()
    policy = publish_dashboard.load_domain_policy(contract)

    checks = publish_dashboard.validate_privacy_controls(
        published, contract, policy, source_df=source_df
    )

    failed = {check.check_name for check in checks if check.status == "FAIL"}
    assert "default_fill__order_status" in failed


def test_save_outputs_save_report_and_run_publish_dashboard(
    tmp_path: Path, monkeypatch
) -> None:
    output_dir = tmp_path / "published"
    docs_dir = tmp_path / "docs"
    quality_dir = tmp_path / "quality"
    contract_path = tmp_path / "privacy_governance.json"
    contract_path.write_text(
        Path(publish_dashboard.PRIVACY_CONTRACT_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(publish_dashboard, "PUBLISHED_DASHBOARD_DIR", output_dir)
    monkeypatch.setattr(publish_dashboard, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(publish_dashboard, "QUALITY_DIR", quality_dir)
    monkeypatch.setattr(
        publish_dashboard,
        "PUBLISHED_PARQUET_PATH",
        output_dir / "fact_orders_dashboard.parquet",
    )
    monkeypatch.setattr(
        publish_dashboard,
        "PUBLISHED_CSV_PATH",
        output_dir / "fact_orders_dashboard.csv",
    )
    monkeypatch.setattr(
        publish_dashboard, "REPORT_PATH", docs_dir / "privacy_governance.md"
    )
    monkeypatch.setattr(
        publish_dashboard,
        "PRIVACY_RESULTS_PATH",
        quality_dir / "privacy_governance_results.csv",
    )
    monkeypatch.setattr(publish_dashboard, "PRIVACY_CONTRACT_PATH", contract_path)
    monkeypatch.setattr(publish_dashboard, "load_internal_fact", build_source_df)

    artifacts = publish_dashboard.run_publish_dashboard()
    report_text = docs_dir.joinpath("privacy_governance.md").read_text(encoding="utf-8")
    results_df = pd.read_csv(quality_dir / "privacy_governance_results.csv")

    assert artifacts.parquet_path.exists()
    assert artifacts.csv_path.exists()
    assert "Arquivo publicado para upload manual" in report_text
    assert "Controles Alinhados à LGPD" in report_text
    assert "necessidade" in report_text
    assert not results_df.empty
    assert set(results_df["status"]) == {"PASS"}


def test_run_publish_dashboard_fails_when_privacy_validation_breaks(
    tmp_path: Path, monkeypatch
) -> None:
    quality_dir = tmp_path / "quality"
    privacy_results_path = quality_dir / "privacy_governance_results.csv"
    contract_path = tmp_path / "privacy_governance.json"
    contract_path.write_text(
        Path(publish_dashboard.PRIVACY_CONTRACT_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    broken_df = build_source_df()
    broken_df["customer_city"] = ["sao paulo"]

    monkeypatch.setattr(publish_dashboard, "QUALITY_DIR", quality_dir)
    monkeypatch.setattr(publish_dashboard, "PRIVACY_CONTRACT_PATH", contract_path)
    monkeypatch.setattr(
        publish_dashboard,
        "PRIVACY_RESULTS_PATH",
        privacy_results_path,
    )
    monkeypatch.setattr(publish_dashboard, "load_internal_fact", lambda: broken_df)
    monkeypatch.setattr(
        publish_dashboard,
        "build_published_dashboard_table",
        lambda df: df,
    )

    with pytest.raises(RuntimeError, match="Validação LGPD/governança falhou"):
        publish_dashboard.run_publish_dashboard()

    assert privacy_results_path.exists()
