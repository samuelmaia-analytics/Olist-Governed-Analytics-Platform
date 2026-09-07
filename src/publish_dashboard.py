from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import (
    ANALYTICS_DIR,
    DOCS_DIR,
    PUBLISHED_DASHBOARD_DIR,
    QUALITY_DIR,
    ROOT_DIR,
)
from src.data_classification import CLASSIFICATION_ROWS
from src.ingest import configure_logging
from src.publish_components import outputs as _outputs
from src.publish_components import pipeline as _pipeline
from src.publish_components import privacy as _privacy
from src.publish_components import transformation as _transformation
from src.publish_components.models import (
    PrivacyCheck,
    PrivacyPreflightResult,
    PublishedArtifacts,
)

LOGGER = logging.getLogger(__name__)
SOURCE_FACT_PATH = ANALYTICS_DIR / "fact_orders_enriched.parquet"
PUBLISHED_PARQUET_PATH = PUBLISHED_DASHBOARD_DIR / "fact_orders_dashboard.parquet"
PUBLISHED_CSV_PATH = PUBLISHED_DASHBOARD_DIR / "fact_orders_dashboard.csv"
REPORT_PATH = DOCS_DIR / "privacy_governance.md"
PRIVACY_RESULTS_PATH = QUALITY_DIR / "privacy_governance_results.csv"
PRIVACY_CONTRACT_PATH = (
    ROOT_DIR / "contracts" / "governance" / "privacy_governance.json"
)

PSEUDONYMIZED_COLUMNS = {
    "order_id": "order_id",
    "customer_unique_id": "customer_unique_id",
}

PUBLISHED_COLUMNS = [
    "order_id",
    "order_item_id",
    "customer_unique_id",
    "order_status",
    "order_purchase_timestamp",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
    "order_date",
    "order_year",
    "order_month",
    "purchase_cohort_month",
    "cohort_order_month_number",
    "customer_order_sequence",
    "is_first_order",
    "seller_key",
    "seller_volume_tier",
    "seller_order_count",
    "seller_avg_delivery_days",
    "seller_delay_rate",
    "delivery_time_days",
    "seller_dispatch_time_days",
    "carrier_delivery_time_days",
    "estimated_delay_days",
    "is_delayed",
    "price",
    "freight_value",
    "freight_to_price_ratio",
    "total_item_value",
    "payment_type_mode",
    "review_score_mean",
    "product_category_name",
    "product_category_name_english",
    "customer_state",
    "seller_state",
]

REMOVED_SENSITIVE_COLUMNS = [
    "customer_id",
    "product_id",
    "seller_id",
    "customer_zip_code_prefix",
    "customer_city",
    "seller_zip_code_prefix",
    "seller_city",
    "latest_review_creation_date",
    "latest_review_answer_timestamp",
    "shipping_limit_date",
    "order_delivered_carrier_date",
    "order_approved_at",
    "payment_count",
    "total_payment_value",
    "max_payment_installments",
    "review_count",
    "review_score_max",
    "review_score_min",
    "has_review_comment",
]


def to_project_relative_path(path: Path) -> str:
    project_root = Path(__file__).resolve().parent.parent
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def pseudonymize(value: object, prefix: str) -> object:
    return _transformation.pseudonymize(value, prefix)


def load_internal_fact() -> pd.DataFrame:
    if not SOURCE_FACT_PATH.exists():
        raise FileNotFoundError(
            f"Tabela analítica interna não encontrada: {SOURCE_FACT_PATH}"
        )
    df = pd.read_parquet(SOURCE_FACT_PATH)
    LOGGER.info(
        "Tabela interna carregada para publicação segura | shape=(%s, %s)", *df.shape
    )
    return df


def load_privacy_contract(path: Path = PRIVACY_CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_domain_policy(contract: dict[str, Any]) -> dict[str, Any]:
    return _transformation.load_domain_policy(contract)


def build_published_dashboard_table(df: pd.DataFrame) -> pd.DataFrame:
    return _transformation.build_published_dashboard_table(
        df,
        pseudonymized_columns=PSEUDONYMIZED_COLUMNS,
        published_columns=PUBLISHED_COLUMNS,
    )


def validate_privacy_controls(
    df: pd.DataFrame,
    contract: dict[str, Any],
    policy: dict[str, Any],
    source_df: pd.DataFrame | None = None,
) -> list[PrivacyCheck]:
    return _privacy.validate_privacy_controls(
        df,
        contract,
        policy,
        source_df,
        classification_rows=CLASSIFICATION_ROWS,
    )


def save_privacy_results(checks: list[PrivacyCheck]) -> Path:
    return _outputs.save_privacy_results(
        checks,
        quality_dir=QUALITY_DIR,
        results_path=PRIVACY_RESULTS_PATH,
        logger=LOGGER,
    )


def save_outputs(df: pd.DataFrame) -> PublishedArtifacts:
    return _outputs.save_outputs(
        df,
        published_dir=PUBLISHED_DASHBOARD_DIR,
        parquet_path=PUBLISHED_PARQUET_PATH,
        csv_path=PUBLISHED_CSV_PATH,
        logger=LOGGER,
    )


def render_report(
    artifacts: PublishedArtifacts,
    contract: dict[str, Any],
    policy: dict[str, Any],
    checks: list[PrivacyCheck],
) -> str:
    return _outputs.render_report(
        artifacts,
        contract,
        policy,
        checks,
        removed_sensitive_columns=REMOVED_SENSITIVE_COLUMNS,
        published_parquet_path=PUBLISHED_PARQUET_PATH,
        published_csv_path=PUBLISHED_CSV_PATH,
        privacy_results_path=PRIVACY_RESULTS_PATH,
        to_relative_path_fn=to_project_relative_path,
    )


def save_report(
    artifacts: PublishedArtifacts,
    contract: dict[str, Any],
    policy: dict[str, Any],
    checks: list[PrivacyCheck],
) -> Path:
    return _outputs.save_report(
        render_report(artifacts, contract, policy, checks),
        docs_dir=DOCS_DIR,
        report_path=REPORT_PATH,
        logger=LOGGER,
    )


def run_privacy_preflight() -> PrivacyPreflightResult:
    """Evaluate the current publish candidate without writing any artifacts."""

    return _pipeline.evaluate_privacy_preflight(
        load_internal_fact_fn=load_internal_fact,
        build_published_fn=build_published_dashboard_table,
        load_contract_fn=load_privacy_contract,
        load_policy_fn=load_domain_policy,
        validate_privacy_fn=validate_privacy_controls,
    )


def run_publish_dashboard(
    *,
    capture_privacy_results_fn: Callable[[list[PrivacyCheck]], None] | None = None,
    capture_privacy_material_fn: Callable[
        [pd.DataFrame, pd.DataFrame, list[PrivacyCheck]], None
    ]
    | None = None,
) -> PublishedArtifacts:
    if capture_privacy_results_fn is None and capture_privacy_material_fn is None:
        return _pipeline.run_publish_dashboard(
            load_internal_fact_fn=load_internal_fact,
            build_published_fn=build_published_dashboard_table,
            load_contract_fn=load_privacy_contract,
            load_policy_fn=load_domain_policy,
            validate_privacy_fn=validate_privacy_controls,
            save_privacy_results_fn=save_privacy_results,
            save_outputs_fn=save_outputs,
            save_report_fn=save_report,
        )
    return _pipeline.run_publish_dashboard(
        load_internal_fact_fn=load_internal_fact,
        build_published_fn=build_published_dashboard_table,
        load_contract_fn=load_privacy_contract,
        load_policy_fn=load_domain_policy,
        validate_privacy_fn=validate_privacy_controls,
        save_privacy_results_fn=save_privacy_results,
        save_outputs_fn=save_outputs,
        save_report_fn=save_report,
        capture_privacy_results_fn=capture_privacy_results_fn,
        capture_privacy_material_fn=capture_privacy_material_fn,
    )


if __name__ == "__main__":
    configure_logging()
    run_publish_dashboard()
